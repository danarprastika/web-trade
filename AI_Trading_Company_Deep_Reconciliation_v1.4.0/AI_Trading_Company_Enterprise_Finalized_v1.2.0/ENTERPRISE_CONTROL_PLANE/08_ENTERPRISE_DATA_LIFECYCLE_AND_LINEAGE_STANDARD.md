# Enterprise Data Lifecycle and Lineage Standard

## Status
Controlled data governance standard.

## Lifecycle
Acquire -> validate -> classify -> store -> transform -> use -> publish internally -> retain -> archive/delete according to approved policy.

## Lineage
Material trading and research outputs should be traceable to source data, transformation/version, timestamp/clock context, and consuming decision or report.

## Data Classes
Classification is determined by the applicable project policy; examples include public market data, proprietary research, credentials/secrets, operational telemetry, financial records, and audit evidence.

## Integrity
Canonical financial and audit records require stronger integrity guarantees than derived analytics.
