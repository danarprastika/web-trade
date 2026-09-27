# Event Architecture

> Status: FINAL FROZEN BASELINE v1.0 — subordinate to FINAL_SPECIFICATION/.

## Purpose
Define event-driven foundations.

## Event classes

Use only the canonical identifiers defined in `FINAL_SPECIFICATION/04_EVENT_CATALOG.md`. This document does not define an independent event catalog.

## Envelope

event_id, event_type, schema_version, occurred_at, produced_at, source, correlation_id, causation_id, aggregate_id, payload_hash.

## Rule

Events are immutable facts. Commands request actions; events report facts.


> **FINAL BASELINE NOTICE:** This document is supporting documentation. Canonical event names and gate semantics are defined only by `FINAL_SPECIFICATION/`. Any older shorthand is descriptive and must not be used as an implementation identifier or gate authority.
