# Profile fixtures (VMS-0.2 Phase 2)

Synthetic economic-profile inputs for the rule-based classifier. These are
**engineering fixtures**, not investment cases. Labels:
`INVESTMENT_VALUE_NOT_ESTABLISHED`.

| Fixture | Expected primary (or low confidence) |
|---|---|
| `mature_operating.json` | `MATURE_OPERATING` |
| `growth_negative_fcf.json` | `GROWTH_OR_REINVESTMENT_HEAVY` |
| `financial_institution.json` | `FINANCIAL_INSTITUTION` |
| `cyclical.json` | `CYCLICAL_OPERATING` (or low confidence with `HIGH_CYCLICALITY`) |
| `holding.json` | `HOLDING_OR_CONGLOMERATE` |

Run:

```bash
vms profile --fixture examples/profile_fixtures/mature_operating.json
vms route --fixture examples/profile_fixtures/financial_institution.json --target FUNDAMENTAL_VALUE_CURRENT
```
