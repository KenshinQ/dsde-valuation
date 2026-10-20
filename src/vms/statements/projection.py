"""Generic operating-company profile: deterministic central-case statement projection (SPEC §9, §10).

Projection order per year (SPEC §9): revenue → COGS/gross profit → EBIT (+implied opex) →
interest, tax (loss pool), net income → working capital → D&A → capex/acquisitions → CFO/FCFF →
debt, cash, dividends, repurchases, issuance → shares/diluted shares.

Output label: DETERMINISTIC_CENTRAL_CASE_NOT_A_VALUATION. Phase 5 runs the same mechanics path-wise.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from vms.assumptions import ASSUMPTIONS, cite
from vms.capital_allocation.policies import AllocationState, Policy
from vms.drivers.estimate import DriverModel
from vms.drivers.history import AnnualHistory
from vms.drivers.profiles import ProfileResolution, SectorProfile, register_profile
from vms.pit.snapshot import PITSnapshot
from vms.schemas import PRICE_ADJUSTING_ACTIONS, SHARE_CHANGING_ACTIONS
from vms.schemas.config import ProjectionConfig
from vms.statements.cashflows import FCFESeries, FCFFSeries
from vms.statements.invariants import Violation, check_invariants
from vms.statements.ledger import Ledger, TracedValue, unresolved_refs
from vms.statements.tax import reconstruct_pool

PROJECTION_VERSION = "DET-PROJ-1"
LABEL = "DETERMINISTIC_CENTRAL_CASE_NOT_A_VALUATION"

REQUIRED_BASE = ("revenue", "cash", "interest_bearing_debt", "accounts_receivable", "inventory",
                 "accounts_payable", "total_assets", "total_liabilities", "total_equity")
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
        for name in REQUIRED_BASE:
            p = history.point(y0, name)
            if p is None or (p.value is None and p.status != "not_applicable"):
                missing.append(f"{name}@FY{y0}")
            elif p.value is None:   # explicit not_applicable => 0, labeled
                L.put(name, y0, 0.0, "not_applicable in source => 0", [p.ref])
                flags.add(f"BASE_{name.upper()}_NOT_APPLICABLE_AS_ZERO")
            else:
                L.put(name, y0, p.value, "observed (PIT snapshot, FY balance/flow)", [p.ref])
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
            interest = L.put("interest_expense", y, d["cost_of_debt"] * L.v("interest_bearing_debt", p),
                             "cost_of_debt x opening interest_bearing_debt",
                             ["driver:cost_of_debt", f"interest_bearing_debt@{p}", "assumption:INTEREST-OPENING-DEBT-v1"])
            pretax = L.put("pre_tax_income", y, ebit - interest, "ebit - interest_expense",
                           [f"ebit@{y}", f"interest_expense@{y}"])
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
            st = AllocationState(year=y, revenue=rev, parent_net_income=pni, ebitda=ebitda,
                                 cash_before_distributions=cbd, debt_open=L.v("interest_bearing_debt", p))
            dv, rp, ic, dt = policy.dividends(st), policy.repurchases(st), policy.issuance_cash(st), policy.debt_target(st)
            div = L.put("dividends", y, dv.value, dv.formula, dv.inputs)
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
                           "INTEREST-OPENING-DEBT-v1", "MINORITY-SHARE-v1", "BALANCE-PLUG-FREE-v1",
                           "REVOLVER-MIN-CASH-v1", "BUYBACK-PRICE-v1", "DILUTED-SHARES-BASIC-v1", "PENDING-CA-v1",
                           "PAYOUT-SAME-YEAR-v1", *drivers.assumptions, *resolution.assumptions)
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
            assumptions=assumptions)
