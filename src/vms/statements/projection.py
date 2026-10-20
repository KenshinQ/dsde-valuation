"""Generic operating-company profile: deterministic central-case statement projection (SPEC §9, §10).

Projection order per year (SPEC §9): revenue → COGS/gross profit → EBIT (+implied opex) →
interest, tax (loss pool), net income → working capital → D&A → capex/acquisitions → CFO/FCFF →
debt, cash, dividends, repurchases, issuance → shares/diluted shares.

Output label: DETERMINISTIC_CENTRAL_CASE_NOT_A_VALUATION. Phase 5 runs the same mechanics path-wise.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from vms.assumptions import ASSUMPTIONS, cite
from vms.capital_allocation.policies import AllocationState, Policy
from vms.drivers.estimate import DriverModel
from vms.drivers.history import AnnualHistory
from vms.drivers.profiles import ProfileResolution, SectorProfile, register_profile
from vms.pit.snapshot import PITSnapshot, local_date
from vms.schemas import PRICE_ADJUSTING_ACTIONS, SHARE_CHANGING_ACTIONS
from vms.schemas.config import ProjectionConfig
from vms.statements.cashflows import FCFESeries, FCFFSeries
from vms.statements.invariants import Violation, check_invariants
from vms.statements.ledger import Ledger, TracedValue, unresolved_refs
from vms.statements.tax import reconstruct_pool

PROJECTION_VERSION = "DET-PROJ-2"   # 2: t+1 dividends, announced-dividend base deduction, revolver/cash interest
LABEL = "DETERMINISTIC_CENTRAL_CASE_NOT_A_VALUATION"

REQUIRED_BASE = ("revenue", "cash", "interest_bearing_debt", "accounts_receivable", "inventory",
                 "accounts_payable", "total_assets", "total_liabilities", "total_equity")
_ADJUSTED_AT_BASE = ("cash", "total_assets", "total_equity")   # ANNOUNCED-DIVIDEND-BASE-v1
PROJECTION_DRIVERS = frozenset({
    "revenue_growth", "gross_margin", "ebit_margin", "effective_tax_rate", "parent_share_of_net_income",
    "receivables_to_revenue", "inventory_to_cogs", "payables_to_cogs", "capex_to_revenue", "da_to_revenue",
    "acquisitions_to_revenue", "cost_of_debt", "debt_to_revenue", "payout_ratio", "repurchases_to_net_income",
    "diluted_share_growth"})


class ProjectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str = LABEL
    projection_version: str = PROJECTION_VERSION
    status: Literal["VALID", "REJECTED", "INSUFFICIENT_DATA", "UNSUPPORTED_PROFILE"]
    instrument_id: str
    as_of: str
    profile: ProfileResolution
    policy: dict | None
    base_year: int | None
    years: list[int]
    items: dict[str, TracedValue]
    fcff: FCFFSeries | None
    fcfe: FCFESeries | None
    violations: list[Violation]
    missing_inputs: list[str]
    flags: list[str]
    warnings: list[str] = []
    assumptions: list[str]

    @property
    def usable(self) -> bool:
        return self.status == "VALID"


def _empty(status, snap, resolution, missing=(), flags=()) -> ProjectionResult:  # noqa: ANN001
    return ProjectionResult(status=status, instrument_id=snap.instrument_id, as_of=snap.as_of.isoformat(),
                            profile=resolution, policy=None, base_year=None, years=[], items={}, fcff=None,
                            fcfe=None, violations=[], missing_inputs=list(missing), flags=sorted(set(flags)),
                            assumptions=[])


@register_profile
class OperatingCompanyProfile(SectorProfile):
    profile_id = "operating_company"
    required_drivers = PROJECTION_DRIVERS

    def project(self, *, snapshot: PITSnapshot, history: AnnualHistory, drivers: DriverModel, policy: Policy,
                resolution: ProfileResolution, years: int, cfg: ProjectionConfig) -> ProjectionResult:
        snap = snapshot
        flags: set[str] = set(resolution.flags)
        if not history.years:
            return _empty("INSUFFICIENT_DATA", snap, resolution, ["no complete fiscal year with revenue"], flags)
        y0 = history.years[-1]
        L = Ledger()
        missing: list[str] = []
        warnings: list[str] = []
        for name in REQUIRED_BASE:
            p = history.point(y0, name)
            key = f"{name}_reported" if name in _ADJUSTED_AT_BASE else name
            if p is None or (p.value is None and p.status != "not_applicable"):
                missing.append(f"{name}@FY{y0}")
            elif p.value is None:   # explicit not_applicable => 0, labeled
                L.put(key, y0, 0.0, "not_applicable in source => 0", [p.ref])
                flags.add(f"BASE_{name.upper()}_NOT_APPLICABLE_AS_ZERO")
            else:
                L.put(key, y0, p.value, "observed (PIT snapshot, FY balance/flow)", [p.ref])
        gp, cogs = history.point(y0, "gross_profit"), history.point(y0, "cost_of_revenue")
        if cogs is not None and cogs.value is not None:
            pass
        elif gp is None or gp.value is None:
            missing.append(f"cost_of_revenue|gross_profit@FY{y0}")
        if not snap.market or snap.market[-1].shares_outstanding is None:
            missing.append("shares_outstanding@as_of")
        if missing:
            return _empty("INSUFFICIENT_DATA", snap, resolution, missing, flags)
        d = {k: e.value for k, e in drivers.estimates.items()}
        last = snap.market[-1]

        # ---- announced-but-unpaid cash dividends at the base balance-sheet date (ANNOUNCED-DIVIDEND-BASE-v1)
        fy_end = date(y0, 12, 31)
        divs = sorted((a.event for a in snap.corporate_actions
                       if a.event.action_type == "cash_dividend" and a.event.ex_date > fy_end and a.event.cash_per_share),
                      key=lambda e: e.ex_date)
        amount, dref = 0.0, ["assumption:ANNOUNCED-DIVIDEND-BASE-v1"]
        for e in divs:
            sh, refs = _shares_before(snap, e.ex_date)
            amount += e.cash_per_share * sh
            dref += [f"corporate_action:{e.action_id}#{e.revision_id or '-'}", *refs]
        L.put("announced_unpaid_dividends", y0, amount,
              "sum(cash_per_share x shares before ex_date) over cash dividends announced by as_of with ex_date > FY end",
              dref)
        for name in _ADJUSTED_AT_BASE:
            L.put(name, y0, L.v(f"{name}_reported", y0) - amount, f"{name}_reported - announced_unpaid_dividends",
                  [f"{name}_reported@{y0}", f"announced_unpaid_dividends@{y0}"])
        if len(divs) > 1:
            flags.add("MULTIPLE_ANNOUNCED_DIVIDENDS_AT_BASE")
        if L.v("cash", y0) < 0:
            flags.add("BASE_CASH_NEGATIVE_AFTER_DIVIDENDS")
        resid = L.put("balance_sheet_residual", y0,
                      L.v("total_assets", y0) - L.v("total_liabilities", y0) - L.v("total_equity", y0),
                      "total_assets - total_liabilities - total_equity (source definitions; held constant)",
                      [f"total_assets@{y0}", f"total_liabilities@{y0}", f"total_equity@{y0}",
                       "assumption:BS-RESIDUAL-WARN-v1", "config:bs_residual_warn_ratio"])
        ta0 = L.v("total_assets", y0)
        if abs(resid) > cfg.bs_residual_warn_ratio * abs(ta0):
            flags.add("BASE_BS_RESIDUAL_LARGE")
            warnings.append(f"BASE_BS_RESIDUAL_LARGE: |residual| {abs(resid):.6g} > {cfg.bs_residual_warn_ratio:g} x "
                            f"total_assets {ta0:.6g} (FY{y0})")

        # ---- base-year derived balances (BALANCE-PLUG-FREE-v1)
        rev0 = L.v("revenue", y0)
        if cogs is not None and cogs.value is not None:
            L.put("cost_of_revenue", y0, cogs.value, "observed (PIT snapshot)", [cogs.ref])
        else:
            L.put("cost_of_revenue", y0, rev0 - gp.value, "revenue - gross_profit", [f"revenue@{y0}", gp.ref])
        L.put("operating_nwc", y0, L.v("accounts_receivable", y0) + L.v("inventory", y0) - L.v("accounts_payable", y0),
              "accounts_receivable + inventory - accounts_payable",
              [f"accounts_receivable@{y0}", f"inventory@{y0}", f"accounts_payable@{y0}"])
        L.put("other_operating_assets", y0, L.v("total_assets", y0) - L.v("cash", y0) - L.v("accounts_receivable", y0)
              - L.v("inventory", y0), "total_assets - cash - accounts_receivable - inventory",
              [f"total_assets@{y0}", f"cash@{y0}", f"accounts_receivable@{y0}", f"inventory@{y0}",
               "assumption:BALANCE-PLUG-FREE-v1"])
        L.put("other_liabilities", y0, L.v("total_liabilities", y0) - L.v("accounts_payable", y0)
              - L.v("interest_bearing_debt", y0), "total_liabilities - accounts_payable - interest_bearing_debt",
              [f"total_liabilities@{y0}", f"accounts_payable@{y0}", f"interest_bearing_debt@{y0}"])
        L.put("shares_outstanding", y0, last.shares_outstanding,
              "shares outstanding at as_of (latest known market observation)",
              [f"snapshot:market:{last.source_id}@{last.timestamp.isoformat()}"])
        flags.add("BASE_SHARES_AT_AS_OF")
        L.put("revolver_balance", y0, 0.0, "0 at base (all reported debt treated as term debt)",
              ["assumption:REVOLVER-RATE-v1"])

        # ---- FY-base dividend declaration, paid in year 1 (DIVIDEND-T-PLUS-1-v1)
        pp = history.point(y0, "parent_net_income")
        if pp is not None and pp.value is not None:
            L.put("parent_net_income", y0, pp.value, "observed (PIT snapshot, FY flow)", [pp.ref])
        else:
            L.put("parent_net_income", y0, 0.0, "missing => 0 (no FY-base dividend declared)",
                  ["assumption:DIVIDEND-T-PLUS-1-v1"])
            flags.add("BASE_PARENT_NET_INCOME_MISSING")
        L.put("cash_available_for_distribution", y0, L.v("cash", y0), "base cash (after announced dividends)",
              [f"cash@{y0}"])
        if divs:
            L.put("dividends_declared", y0, 0.0, "FY-base dividend already announced and deducted from base cash",
                  [f"announced_unpaid_dividends@{y0}", "assumption:ANNOUNCED-DIVIDEND-BASE-v1"])
            flags.add("ANNOUNCED_DIVIDEND_DEDUCTED_AT_BASE")
        else:
            st0 = AllocationState(year=y0, revenue=rev0, parent_net_income=L.v("parent_net_income", y0),
                                  ebitda=0.0,   # not used by dividend rules
                                  cash_available_for_distribution=L.v("cash_available_for_distribution", y0),
                                  debt_open=L.v("interest_bearing_debt", y0))
            dv0 = policy.dividends(st0)
            L.put("dividends_declared", y0, dv0.value, dv0.formula + " (FY-base declaration, paid next year)",
                  dv0.inputs + ["assumption:DIVIDEND-T-PLUS-1-v1"])

        # ---- tax-loss pools reconstructed from history (TAX-LOSS-POOL-FROM-BOOK-v1)
        hist_pretax, hist_ebit = [], []
        for y in history.years:
            e, i = history.value(y, "ebit"), history.value(y, "interest_expense")
            if e is not None:
                hist_ebit.append((y, e))
                if i is not None:
                    hist_pretax.append((y, e - i))
        if len(hist_pretax) < len(history.years):
            flags.add("TAX_POOL_HISTORY_INCOMPLETE")
        book_pool = reconstruct_pool(hist_pretax, cfg.tax_loss_carryforward_years)
        op_pool = reconstruct_pool(hist_ebit, cfg.tax_loss_carryforward_years)
        L.put("book_tax_loss_pool", y0, book_pool.balance, "reconstructed from historical pre-tax income",
              ["assumption:TAX-LOSS-POOL-FROM-BOOK-v1", "config:tax_loss_carryforward_years"])
        L.put("operating_tax_loss_pool", y0, op_pool.balance, "reconstructed from historical EBIT",
              ["assumption:TAX-LOSS-POOL-FROM-BOOK-v1", "config:tax_loss_carryforward_years"])

        # ---- known pending share-changing corporate actions (PENDING-CA-v1)
        pending = [a.event for a in snap.corporate_actions
                   if a.status == "pending" and a.event.action_type in SHARE_CHANGING_ACTIONS]
        base_price = last.raw_close
        tax_rate = d["effective_tax_rate"]
        yrs = list(range(y0 + 1, y0 + 1 + years))
        price_factor = 1.0
        for y in yrs:
            p = y - 1
            # 1. revenue
            rev = L.put("revenue", y, L.v("revenue", p) * (1 + d["revenue_growth"]), "revenue[y-1] x (1 + revenue_growth)",
                        [f"revenue@{p}", "driver:revenue_growth"])
            # 2. COGS & gross profit
            gp_ = L.put("gross_profit", y, rev * d["gross_margin"], "revenue x gross_margin",
                        [f"revenue@{y}", "driver:gross_margin"])
            cogs_ = L.put("cost_of_revenue", y, rev - gp_, "revenue - gross_profit", [f"revenue@{y}", f"gross_profit@{y}"])
            # 3. EBIT, implied opex, one-offs
            ebit = L.put("ebit", y, rev * d["ebit_margin"], "revenue x ebit_margin (recurring)",
                         [f"revenue@{y}", "driver:ebit_margin", "assumption:EBIT-MARGIN-PRIMARY-v1"])
            L.put("operating_expenses", y, gp_ - ebit, "gross_profit - ebit (implied)",
                  [f"gross_profit@{y}", f"ebit@{y}", "assumption:EBIT-MARGIN-PRIMARY-v1"])
            L.put("one_off_items", y, 0.0, "0 (no one-offs projected)", ["assumption:ONE-OFFS-v1"])
            # 4. interest, tax, net income
            rev_open = L.v("revolver_balance", p)
            term_open = L.v("interest_bearing_debt", p) - rev_open
            interest = L.put("interest_expense", y,
                             d["cost_of_debt"] * term_open + (d["cost_of_debt"] + cfg.revolver_spread) * rev_open,
                             "cost_of_debt x (opening debt - opening revolver) + (cost_of_debt + revolver_spread) x "
                             "opening revolver",
                             ["driver:cost_of_debt", f"interest_bearing_debt@{p}", f"revolver_balance@{p}",
                              "config:revolver_spread", "assumption:INTEREST-OPENING-DEBT-v2",
                              "assumption:REVOLVER-RATE-v1"])
            ii = L.put("interest_income", y, cfg.cash_interest_rate * max(L.v("cash", p), 0.0),
                       "cash_interest_rate x max(opening cash, 0)",
                       ["config:cash_interest_rate", f"cash@{p}", "assumption:CASH-INTEREST-ZERO-v1"])
            pretax = L.put("pre_tax_income", y, ebit - interest + ii, "ebit - interest_expense + interest_income",
                           [f"ebit@{y}", f"interest_expense@{y}", f"interest_income@{y}"])
            bs = book_pool.step(y, pretax)
            L.put("book_tax_loss_used", y, bs.loss_used, "FIFO use of book tax-loss pool",
                  [f"book_tax_loss_pool@{p}", f"pre_tax_income@{y}", "assumption:TAX-CN-LCF-5Y-v1"])
            L.put("book_tax_loss_expired", y, bs.loss_expired, "losses older than carryforward window expire",
                  [f"book_tax_loss_pool@{p}", "config:tax_loss_carryforward_years"])
            L.put("book_tax_loss_pool", y, bs.pool_close,
                  "pool[y-1] + max(-pre_tax_income, 0) - loss_used - loss_expired",
                  [f"book_tax_loss_pool@{p}", f"pre_tax_income@{y}", f"book_tax_loss_used@{y}",
                   f"book_tax_loss_expired@{y}"])
            L.put("taxable_income", y, bs.taxable_after, "max(pre_tax_income, 0) - book_tax_loss_used",
                  [f"pre_tax_income@{y}", f"book_tax_loss_used@{y}"])
            tax = L.put("tax_expense", y, tax_rate * bs.taxable_after, "effective_tax_rate x taxable_income",
                        ["driver:effective_tax_rate", f"taxable_income@{y}"])
            ni = L.put("net_income", y, pretax - tax, "pre_tax_income - tax_expense",
                       [f"pre_tax_income@{y}", f"tax_expense@{y}"])
            pni = L.put("parent_net_income", y, ni * d["parent_share_of_net_income"],
                        "net_income x parent_share_of_net_income",
                        [f"net_income@{y}", "driver:parent_share_of_net_income", "assumption:MINORITY-SHARE-v1"])
            L.put("minority_net_income", y, ni - pni, "net_income - parent_net_income",
                  [f"net_income@{y}", f"parent_net_income@{y}"])
            # 5. working capital
            ar = L.put("accounts_receivable", y, rev * d["receivables_to_revenue"], "revenue x receivables_to_revenue",
                       [f"revenue@{y}", "driver:receivables_to_revenue"])
            inv = L.put("inventory", y, cogs_ * d["inventory_to_cogs"], "cost_of_revenue x inventory_to_cogs",
                        [f"cost_of_revenue@{y}", "driver:inventory_to_cogs"])
            ap = L.put("accounts_payable", y, cogs_ * d["payables_to_cogs"], "cost_of_revenue x payables_to_cogs",
                       [f"cost_of_revenue@{y}", "driver:payables_to_cogs"])
            onwc = L.put("operating_nwc", y, ar + inv - ap, "accounts_receivable + inventory - accounts_payable",
                         [f"accounts_receivable@{y}", f"inventory@{y}", f"accounts_payable@{y}",
                          "assumption:NWC-OPERATING-v1"])
            dnwc = L.put("delta_operating_nwc", y, onwc - L.v("operating_nwc", p), "operating_nwc[y] - operating_nwc[y-1]",
                         [f"operating_nwc@{y}", f"operating_nwc@{p}"])
            # 6. D&A
            da = L.put("depreciation_amortization", y, rev * d["da_to_revenue"], "revenue x da_to_revenue",
                       [f"revenue@{y}", "driver:da_to_revenue"])
            ebitda = L.put("ebitda", y, ebit + da, "ebit + depreciation_amortization",
                           [f"ebit@{y}", f"depreciation_amortization@{y}"])
            # 7. capex & acquisitions (separate)
            capex = L.put("capex", y, rev * d["capex_to_revenue"], "revenue x capex_to_revenue",
                          [f"revenue@{y}", "driver:capex_to_revenue"])
            a = policy.acquisitions(rev, y)
            acq = L.put("acquisitions", y, a.value, a.formula, a.inputs + ["assumption:ACQUISITIONS-SEPARATE-v1"])
            L.put("other_operating_assets", y, L.v("other_operating_assets", p) + capex + acq - da,
                  "other_operating_assets[y-1] + capex + acquisitions - depreciation_amortization",
                  [f"other_operating_assets@{p}", f"capex@{y}", f"acquisitions@{y}", f"depreciation_amortization@{y}"])
            # 8. operating tax (unlevered, own loss pool), NOPAT, FCFF, CFO
            os_ = op_pool.step(y, ebit)
            L.put("operating_tax_loss_pool", y, os_.pool_close, "operating pool rolled with EBIT (FIFO, expiry)",
                  [f"operating_tax_loss_pool@{p}", f"ebit@{y}", "assumption:TAX-CN-LCF-5Y-v1",
                   "assumption:NEGATIVE-EBIT-v1"])
            optax = L.put("operating_tax", y, tax_rate * os_.taxable_after,
                          "effective_tax_rate x max(ebit - operating loss used, 0)",
                          ["driver:effective_tax_rate", f"ebit@{y}", f"operating_tax_loss_pool@{p}"])
            nopat = L.put("nopat", y, ebit - optax, "ebit - operating_tax", [f"ebit@{y}", f"operating_tax@{y}"])
            fcff = L.put("fcff", y, nopat + da - capex - dnwc - acq,
                         "nopat + D&A - capex - delta_operating_nwc - acquisitions",
                         [f"nopat@{y}", f"depreciation_amortization@{y}", f"capex@{y}", f"delta_operating_nwc@{y}",
                          f"acquisitions@{y}", "assumption:LEASES-EXCLUDED-v1", "assumption:SBC-IN-EBIT-v1"])
            cfo = L.put("cash_flow_from_operations", y, ni + da - dnwc, "net_income + D&A - delta_operating_nwc",
                        [f"net_income@{y}", f"depreciation_amortization@{y}", f"delta_operating_nwc@{y}"])
            # 9. capital allocation: dividends, repurchases, issuance, debt, revolver, cash
            cbd = L.put("cash_before_distributions", y, L.v("cash", p) + cfo - capex - acq,
                        "cash[y-1] + CFO - capex - acquisitions",
                        [f"cash@{p}", f"cash_flow_from_operations@{y}", f"capex@{y}", f"acquisitions@{y}"])
            div = L.put("dividends", y, L.v("dividends_declared", p),
                        "dividends_declared[y-1] (paid the year after the FY)",
                        [f"dividends_declared@{p}", "assumption:DIVIDEND-T-PLUS-1-v1"])
            cad = L.put("cash_available_for_distribution", y, cbd - div, "cash_before_distributions - dividends paid",
                        [f"cash_before_distributions@{y}", f"dividends@{y}"])
            st = AllocationState(year=y, revenue=rev, parent_net_income=pni, ebitda=ebitda,
                                 cash_available_for_distribution=cad, debt_open=L.v("interest_bearing_debt", p))
            dv, rp, ic, dt = policy.dividends(st), policy.repurchases(st), policy.issuance_cash(st), policy.debt_target(st)
            L.put("dividends_declared", y, dv.value, dv.formula + " (declared on FY y, paid y+1)",
                  dv.inputs + ["assumption:DIVIDEND-T-PLUS-1-v1"])
            rep = L.put("share_repurchases", y, rp.value, rp.formula, rp.inputs)
            iss = L.put("share_issuance_proceeds", y, ic.value, ic.formula, ic.inputs)
            L.put("debt_target", y, max(dt.value, 0.0), dt.formula + " (floored at 0)", dt.inputs)
            delta_debt = max(dt.value, 0.0) - L.v("interest_bearing_debt", p)
            di = L.put("debt_issuance", y, max(delta_debt, 0.0), "max(debt_target - debt[y-1], 0)",
                       [f"debt_target@{y}", f"interest_bearing_debt@{p}"])
            dr = L.put("debt_repayment", y, max(-delta_debt, 0.0), "max(debt[y-1] - debt_target, 0)",
                       [f"debt_target@{y}", f"interest_bearing_debt@{p}"])
            cash_pre = cbd + di - dr - div - rep + iss
            floor = cfg.min_cash_to_revenue * rev
            rv = L.put("revolver_draw", y, max(floor - cash_pre, 0.0),
                       "max(min_cash_to_revenue x revenue - cash before revolver, 0)",
                       ["config:min_cash_to_revenue", f"revenue@{y}", f"cash_before_distributions@{y}",
                        f"debt_issuance@{y}", f"debt_repayment@{y}", f"dividends@{y}", f"share_repurchases@{y}",
                        f"share_issuance_proceeds@{y}", "assumption:REVOLVER-MIN-CASH-v1"])
            if rv > 0:
                flags.add("REVOLVER_DRAW")
            nb = L.put("net_borrowing", y, di + rv - dr, "debt_issuance + revolver_draw - debt_repayment",
                       [f"debt_issuance@{y}", f"revolver_draw@{y}", f"debt_repayment@{y}"])
            L.put("interest_bearing_debt", y, L.v("interest_bearing_debt", p) + nb, "debt[y-1] + net_borrowing",
                  [f"interest_bearing_debt@{p}", f"net_borrowing@{y}"])
            L.put("revolver_balance", y, max(rev_open - dr, 0.0) + rv,
                  "max(revolver[y-1] - debt_repayment, 0) + revolver_draw (repayments retire the revolver first)",
                  [f"revolver_balance@{p}", f"debt_repayment@{y}", f"revolver_draw@{y}", "assumption:REVOLVER-RATE-v1"])
            cash = L.put("cash", y, cash_pre + rv,
                         "cash_before_distributions + debt_issuance - debt_repayment - dividends - repurchases + "
                         "issuance + revolver_draw",
                         [f"cash_before_distributions@{y}", f"debt_issuance@{y}", f"debt_repayment@{y}",
                          f"dividends@{y}", f"share_repurchases@{y}", f"share_issuance_proceeds@{y}",
                          f"revolver_draw@{y}"])
            L.put("fcfe", y, cfo - capex - acq + nb, "CFO - capex - acquisitions + net_borrowing",
                  [f"cash_flow_from_operations@{y}", f"capex@{y}", f"acquisitions@{y}", f"net_borrowing@{y}"])
            dist = L.put("distributions_to_shareholders", y, div + rep, "dividends + share_repurchases",
                         [f"dividends@{y}", f"share_repurchases@{y}"])
            L.put("total_equity", y, L.v("total_equity", p) + ni - dist + iss,
                  "equity[y-1] + net_income - distributions_to_shareholders + issuance",
                  [f"total_equity@{p}", f"net_income@{y}", f"distributions_to_shareholders@{y}",
                   f"share_issuance_proceeds@{y}", "assumption:MINORITY-SHARE-v1"])
            L.put("other_liabilities", y, L.v("other_liabilities", p), "held at base level",
                  [f"other_liabilities@{p}", "assumption:BALANCE-PLUG-FREE-v1"])
            L.put("total_assets", y, cash + ar + inv + L.v("other_operating_assets", y),
                  "cash + accounts_receivable + inventory + other_operating_assets",
                  [f"cash@{y}", f"accounts_receivable@{y}", f"inventory@{y}", f"other_operating_assets@{y}"])
            L.put("total_liabilities", y, ap + L.v("interest_bearing_debt", y) + L.v("other_liabilities", y),
                  "accounts_payable + interest_bearing_debt + other_liabilities",
                  [f"accounts_payable@{y}", f"interest_bearing_debt@{y}", f"other_liabilities@{y}"])
            # 10. shares & diluted shares
            ratio, ca_refs = 1.0, []
            for e in pending:
                if e.ex_date.year == y:
                    ratio *= e.share_ratio
                    ca_refs.append(f"corporate_action:{e.action_id}#{e.revision_id or '-'}")
                    if e.action_type in PRICE_ADJUSTING_ACTIONS:
                        price_factor *= e.share_ratio
                    flags.add("PENDING_CORPORATE_ACTION_APPLIED")
            L.put("pending_share_ratio", y, ratio, "product of known pending share ratios with ex_date in year",
                  ca_refs + ["assumption:PENDING-CA-v1"])
            sh_open = L.v("shares_outstanding", p) * ratio
            price = L.put("transaction_price", y, base_price / price_factor,
                          "last known close / cumulative pending bonus-split ratio",
                          [f"snapshot:market:{last.source_id}@{last.timestamp.isoformat()}",
                           "assumption:BUYBACK-PRICE-v1"] + ca_refs)
            dil = L.put("shares_dilution", y, sh_open * d["diluted_share_growth"],
                        "shares[y-1] x pending_share_ratio x diluted_share_growth",
                        [f"shares_outstanding@{p}", f"pending_share_ratio@{y}", "driver:diluted_share_growth"])
            srep = L.put("shares_repurchased", y, rep / price, "share_repurchases / transaction_price",
                         [f"share_repurchases@{y}", f"transaction_price@{y}"])
            siss = L.put("shares_issued", y, iss / price, "share_issuance_proceeds / transaction_price",
                         [f"share_issuance_proceeds@{y}", f"transaction_price@{y}"])
            sh = L.put("shares_outstanding", y, sh_open + dil - srep + siss,
                       "shares[y-1] x pending_share_ratio + dilution - repurchased + issued",
                       [f"shares_outstanding@{p}", f"pending_share_ratio@{y}", f"shares_dilution@{y}",
                        f"shares_repurchased@{y}", f"shares_issued@{y}"])
            L.put("diluted_shares", y, sh, "= shares_outstanding (no dilutive-security data)",
                  [f"shares_outstanding@{y}", "assumption:DILUTED-SHARES-BASIC-v1"])
            if ni < 0:
                flags.add("NEGATIVE_NET_INCOME")
            if ebit < 0:
                flags.add("NEGATIVE_EBIT")
            if bs.loss_used > 0 or os_.loss_used > 0:
                flags.add("TAX_LOSS_CARRYFORWARD_USED")
            if bs.loss_expired > 0 or os_.loss_expired > 0:
                flags.add("TAX_LOSS_EXPIRED")

        for e in drivers.estimates.values():
            if e.low_confidence:
                flags.add("LOW_CONFIDENCE_DRIVERS")
        assumptions = cite("ANNUAL-BASE-v1", "EBIT-MARGIN-PRIMARY-v1", "ONE-OFFS-v1", "TAX-CN-LCF-5Y-v1",
                           "TAX-LOSS-POOL-FROM-BOOK-v1", "NEGATIVE-EBIT-v1", "NWC-OPERATING-v1",
                           "ACQUISITIONS-SEPARATE-v1", "LEASES-EXCLUDED-v1", "SBC-IN-EBIT-v1",
                           "INTEREST-OPENING-DEBT-v2", "MINORITY-SHARE-v1", "BALANCE-PLUG-FREE-v1",
                           "REVOLVER-MIN-CASH-v1", "BUYBACK-PRICE-v1", "DILUTED-SHARES-BASIC-v1", "PENDING-CA-v1",
                           "DIVIDEND-T-PLUS-1-v1", "ANNOUNCED-DIVIDEND-BASE-v1", "REVOLVER-RATE-v1",
                           "CASH-INTEREST-ZERO-v1", "BS-RESIDUAL-WARN-v1", "ANNUAL-BASE-STALENESS-v1",
                           *drivers.assumptions, *resolution.assumptions)
        violations = check_invariants(L.items, y0, yrs, tol=cfg.invariant_abs_tol,
                                      min_cash_to_revenue=cfg.min_cash_to_revenue)
        trace_bad = unresolved_refs(L.items, drivers=set(drivers.estimates), policy=set(policy.params),
                                    config=set(ProjectionConfig.model_fields), assumptions=set(ASSUMPTIONS))
        violations += [Violation(code="TRACE_UNRESOLVED", year=y0, detail=b) for b in trace_bad]
        fcff = FCFFSeries(years=yrs, values=[L.v("fcff", y) for y in yrs])
        fcfe = FCFESeries(years=yrs, values=[L.v("fcfe", y) for y in yrs])
        return ProjectionResult(
            status="REJECTED" if violations else "VALID", instrument_id=snap.instrument_id,
            as_of=snap.as_of.isoformat(), profile=resolution, policy=policy.describe(), base_year=y0, years=yrs,
            items=L.items, fcff=fcff, fcfe=fcfe, violations=violations, missing_inputs=[], flags=sorted(flags),
            warnings=warnings, assumptions=assumptions)


def _shares_before(snap: PITSnapshot, ex_date: date) -> tuple[float, list[str]]:
    """Shares entitled to a dividend: last known market shares before ex_date x known share-changing
    ratios with ex_date strictly between that observation and the dividend ex_date."""
    obs = [m for m in snap.market if m.shares_outstanding is not None and local_date(m.timestamp) < ex_date]
    if not obs:
        obs = [m for m in snap.market if m.shares_outstanding is not None]
    m = obs[-1]
    od = local_date(m.timestamp)
    refs = [f"snapshot:market:{m.source_id}@{m.timestamp.isoformat()}"]
    ratio = 1.0
    for a in snap.corporate_actions:
        e = a.event
        if e.action_type in SHARE_CHANGING_ACTIONS and od < e.ex_date < ex_date:
            ratio *= e.share_ratio
            refs.append(f"corporate_action:{e.action_id}#{e.revision_id or '-'}")
    return m.shares_outstanding * ratio, refs
