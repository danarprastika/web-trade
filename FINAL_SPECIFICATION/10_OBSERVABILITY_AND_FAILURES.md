# Observability and Failure Semantics — Final

Every request/task/order/event is correlated with trace_id, request_id/task_id, event_id and relevant strategy/experiment/incident identifiers.

Measure data freshness, provider latency, model latency, risk latency, OMS latency, broker acknowledgement latency, fill latency, reconciliation age, queue depth, error rate and resource saturation.

Unknown broker state, stale critical data, failed reconciliation, corrupted event sequence, missing risk approval or authorization ambiguity are fail-closed conditions for live mutation.

Recovery must be deterministic: detect → freeze affected scope → persist evidence → reconcile → restore/rollback → validate → resume through governed command.
