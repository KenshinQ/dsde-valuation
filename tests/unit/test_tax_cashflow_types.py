import pytest
from pydantic import ValidationError

from vms.statements.cashflows import (CashFlowTypeError, CostOfEquity, FCFESeries, FCFFSeries, WACC,
                                      present_value)
from vms.statements.tax import TaxLossPool, reconstruct_pool


# ---------------------------------------------------------------- tax losses (TAX-CN-LCF-5Y-v1)
def test_loss_carryforward_fifo_and_no_negative_tax():
    p = TaxLossPool(5)
    s = p.step(2020, -100)
    assert s.taxable_after == 0 and s.loss_generated == 100 and p.balance == 100
    s = p.step(2021, -50)
    s = p.step(2022, 120)          # uses 100 from 2020 first, then 20 from 2021
    assert s.loss_used == 120 and s.taxable_after == 0 and p.vintages == {2021: 30}
    s = p.step(2023, 50)
    assert s.loss_used == 30 and s.taxable_after == 20 and p.balance == 0


def test_loss_expires_after_five_years():
    p = TaxLossPool(5)
    p.step(2020, -100)
    assert p.step(2025, 0).loss_expired == 0 and p.balance == 100     # 2025 = 2020 + 5: still usable
    s = p.step(2026, 80)
    assert s.loss_expired == 100 and s.loss_used == 0 and s.taxable_after == 80


def test_reconstruct_pool_from_history():
    p = reconstruct_pool([(2019, -10), (2020, -20), (2021, 5)], 5)
    assert p.vintages == {2019: 5, 2020: 20} and p.balance == 25


# ---------------------------------------------------------------- FCFF vs FCFE types
FCFF = FCFFSeries(years=[2025, 2026], values=[100.0, 110.0])
FCFE = FCFESeries(years=[2025, 2026], values=[90.0, 95.0])


def test_matching_pairs_discount():
    assert present_value(FCFF, WACC(rate=0.1)) == pytest.approx(100 / 1.1 + 110 / 1.21)
    assert present_value(FCFE, CostOfEquity(rate=0.1)) == pytest.approx(90 / 1.1 + 95 / 1.21)


@pytest.mark.parametrize("cf,rate", [(FCFF, CostOfEquity(rate=0.1)), (FCFE, WACC(rate=0.1))])
def test_mixing_rejected(cf, rate):
    with pytest.raises(CashFlowTypeError, match="must be discounted with"):
        present_value(cf, rate)


def test_no_arithmetic_or_cross_validation():
    with pytest.raises(CashFlowTypeError):
        FCFF + FCFE  # noqa: B018
    with pytest.raises(CashFlowTypeError):
        FCFF + FCFF  # noqa: B018
    with pytest.raises(ValidationError):
        FCFESeries.model_validate(FCFF.model_dump())
    with pytest.raises(ValidationError):
        WACC.model_validate(CostOfEquity(rate=0.1).model_dump())
    with pytest.raises(ValidationError):
        FCFFSeries(years=[1], values=[float("nan")])
    assert not issubclass(FCFFSeries, FCFESeries) and not issubclass(FCFESeries, FCFFSeries)
