"""Tax-loss carryforward pool (TAX-CN-LCF-5Y-v1): FIFO, expiring after N years, no carry-back."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaxStep:
    taxable_before: float
    loss_generated: float
    loss_used: float
    loss_expired: float
    taxable_after: float
    pool_close: float


@dataclass
class TaxLossPool:
    carryforward_years: int
    vintages: dict[int, float] = field(default_factory=dict)   # origin year -> remaining loss (positive)

    @property
    def balance(self) -> float:
        return sum(self.vintages.values())

    def step(self, year: int, taxable: float) -> TaxStep:
        """Apply one year. Losses from year y may be used in years y+1 .. y+N."""
        expired = 0.0
        for y in sorted(self.vintages):
            if year - y > self.carryforward_years:
                expired += self.vintages.pop(y)
        used = 0.0
        generated = 0.0
        if taxable < 0:
            generated = -taxable
            self.vintages[year] = self.vintages.get(year, 0.0) + generated
            after = 0.0
        else:
            remaining = taxable
            for y in sorted(self.vintages):
                take = min(self.vintages[y], remaining)
                self.vintages[y] -= take
                remaining -= take
                used += take
                if self.vintages[y] <= 0:
                    del self.vintages[y]
                if remaining <= 0:
                    break
            after = remaining
        return TaxStep(taxable_before=taxable, loss_generated=generated, loss_used=used, loss_expired=expired,
                       taxable_after=after, pool_close=self.balance)


def reconstruct_pool(history: list[tuple[int, float]], carryforward_years: int) -> TaxLossPool:
    """Opening pool from historical (year, taxable) pairs (TAX-LOSS-POOL-FROM-BOOK-v1)."""
    pool = TaxLossPool(carryforward_years)
    for y, t in sorted(history):
        pool.step(y, t)
    return pool
