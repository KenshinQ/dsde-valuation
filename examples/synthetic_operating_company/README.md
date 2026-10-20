# SYNTHETIC operating company (offline example)

**SYNTHETIC DATA — no real company, no investment meaning.**

- Instrument: `SYN000001.SZ` (fictitious), 16 quarters from 2021Q1, CNY, unit `ten_thousand` (万元).
- Flows are standalone-quarter (not cumulative); stocks are quarter-end balances.
- `published_at` follows A-share statutory lags (Q1/Q3 ≈ 28d, H1 ≈ 55d, annual ≈ 110d), 18:00 Asia/Shanghai.
- `minority_interest` is deliberately `null` with `quality_status=missing` to exercise missing-value handling.
- Seeded via `vms.seeding.stream_rng(seed, "synthetic_data")`; same seed ⇒ identical records.

```bash
python examples/synthetic_operating_company/generate_data.py --seed 42 --out /tmp/syn
vms validate-data --input /tmp/syn
vms demo --out /tmp/vms_demo --seed 42      # Phase 0 smoke: generates data internally
```
