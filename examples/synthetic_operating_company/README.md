# SYNTHETIC operating company (offline example)

**SYNTHETIC DATA: no real company, no investment meaning.**

- Instrument `SYN000001.SZ` (fictitious). 16 quarters 2021Q1–2024Q4, CNY, unit `ten_thousand` (万元).
  Monthly closes from 2021-01 to 2025-06.
- Source `SYNTHETIC` is declared in `sources.yaml` as `CN_CUMULATIVE_YTD` + `FULL_HISTORY`.
  Flows are cumulative YTD; stocks are quarter-end balances.
- Publications are at 18:00 Asia/Shanghai, so a date-only as_of on the publication day excludes them.
- Built-in PIT scenarios:
  - **Restatement:** FY2022 revenue/gross_profit/ebit/parent_net_income are restated (`r1`) on 2023-08-28.
  - **Late publication:** the FY2023 annual report is published 2024-06-20, after Q1-2024 (2024-04-28).
  - **Corporate actions:** 10送3 bonus share (1.3) and a 0.50 cash dividend are announced 2024-06-20,
    ex-date 2024-07-10. The dividend is revised to 0.45 on 2024-07-01.
  - **Vendor adjusted_close** is 前复权 to the dataset end, so it embeds the future bonus share.
    Snapshots ignore it and recompute `pit_adjusted_close`.
  - `minority_interest` is explicitly missing every period.
- Seeded via `vms.seeding.stream_rng(seed, "synthetic_data")`; the same seed gives identical records.

```bash
python examples/synthetic_operating_company/generate_data.py --seed 42 --out /tmp/syn [--format parquet]
vms validate-data --input /tmp/syn --as-of 2024-05-15      # PASS_WITH_WARNINGS (MISSING_QUARTER 2023Q4)
vms build-snapshot --input /tmp/syn --ticker SYN000001.SZ --as-of 2024-07-05 --out /tmp/snap
vms demo --out /tmp/vms_demo --seed 42
```
