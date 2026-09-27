# Risk and Live Gate — Final

Live order mutation is permitted only when ALL are true:
1. Environment = LIVE and deployment is production-approved.
2. Strategy version is approved, active and immutable.
3. Instrument/venue/provider is production-approved.
4. Market data passes freshness/quality rules.
5. Reconciliation is HEALTHY.
6. Risk policy version is active.
7. Exact order intent has a non-expired RiskApproved decision.
8. Portfolio/global/market/strategy/trade limits pass.
9. Kill switches are clear for all applicable scopes.
10. Account/balance/position state is known.
11. Credentials are available only to the execution boundary.
12. Idempotency protection is active.

If any condition becomes unknown or false before submission, the OMS must not submit.

Kill hierarchy: SYSTEM → MARKET → PORTFOLIO → STRATEGY → AGENT → TASK. Higher-level kill state dominates lower-level resume.
