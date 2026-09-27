# Authority and Permission Matrix — Final / Frozen

| Actor/component | Propose | Approve risk | Create OMS instruction | Execute provider mutation | Reconcile | Promote strategy | Access live secrets |
|---|---:|---:|---:|---:|---:|---:|---:|
| Strategy/Research AI | Yes | No | No | No | No | No | No |
| Risk Engine | Evaluate | Yes | No | No | Read required state | No | No |
| OMS | No | No | Yes, from valid approval | No | No | No | No |
| Execution Adapter | No | No | No | Yes, OMS instruction only | Provider query | No | Execution boundary only |
| Reconciliation | No | No | No | No | Yes | No | No |
| Runtime Master AI | Coordinate | No | No | No | Read governed results | No | No |
| Human Owner | Governed commands/emergency controls | Per policy | Through governed path | Through governed path | No direct state writes | Approval authority where specified | Never by default |
| Kilo Code | Development only | No | No | No | Test environment only | No | No |

All permissions are deny-by-default and scoped by environment, market, resource, action and actor identity.
