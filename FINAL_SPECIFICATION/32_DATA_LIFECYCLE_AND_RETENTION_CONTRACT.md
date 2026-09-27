# DATA LIFECYCLE AND RETENTION CONTRACT
## Data Integrity From Ingestion to Deletion

Status: NORMATIVE IMPLEMENTATION CONTROL

## Lifecycle

For important datasets, establish:
ingestion → validation → normalization → versioning → use → archival/retention → controlled disposal.

## Required properties

Where applicable:
- provenance;
- source identity;
- timestamp semantics;
- schema version;
- dataset version;
- quality status;
- lineage;
- retention class;
- access policy.

## Trading/research separation

Research datasets must be versioned and frozen where required by the research governance.

Live/production data must not be retroactively altered to make historical results appear better.

## Deletion

Deletion/retention operations must respect audit, financial/trading history, security and legal/operational requirements applicable to the deployment.
