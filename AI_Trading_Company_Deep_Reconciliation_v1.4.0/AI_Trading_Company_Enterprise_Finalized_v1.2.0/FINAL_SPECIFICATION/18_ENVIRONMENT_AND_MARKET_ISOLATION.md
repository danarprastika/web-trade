# Environment and Market Isolation — Final / Frozen

## Environments
Research, Test, Staging, Shadow, Demo and Live are separate first-class environments. Development is a workspace, not a substitute for runtime isolation.

## Market modules
Crypto, Forex, Stocks and Commodities are independently configurable market modules. Each module has its own provider configuration, instruments, strategy scope, data quality state, risk constraints, portfolios/accounts where applicable, adapters and failure domain.

## Isolation invariants
- A disabled/degraded market cannot mutate unrelated markets.
- Market-specific kill state dominates that market only unless a higher-level kill applies.
- Credentials are environment- and provider-scoped.
- Research cannot inherit live credentials through shared configuration, memory, prompts or tooling.
- Cross-market portfolio controls may exist only in the governed risk/capital layer and must not bypass market boundaries.
