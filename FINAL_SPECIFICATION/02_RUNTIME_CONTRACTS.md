# Runtime Contracts — Final

## Command envelope
Every command carries: command_id, trace_id, actor_id, actor_type, environment, issued_at_utc, schema_version, idempotency_key, authorization_scope and payload_hash.

## Event envelope
Every event carries: event_id, aggregate_type, aggregate_id, event_type, schema_version, occurred_at_utc, recorded_at_utc, producer, correlation_id, causation_id, environment, payload_hash and sequence.

## Order intent
Required: intent_id, intent_version, account_id, portfolio_id, market_id, instrument_id, side, quantity, order_type, price parameters, time_in_force, strategy_id/version, signal_id, risk_policy_version, environment, created_at, expires_at, idempotency_key and canonical intent hash.

## Risk approval
Contains approval_id, intent_hash, risk_policy_version, limits evaluated, exposure snapshot reference, data-quality snapshot reference, decision, reason_codes, approved_at, expires_at and risk_engine_version. Approval is valid only for the exact hash and expiry window.

## OMS instruction
OMS may create an execution instruction only from a currently valid risk approval. It must carry the approval_id and intent_hash.

## Broker execution
Adapters must be idempotent and expose submit/cancel/query order/query fills/query positions/query balances plus streaming events where supported. Provider identifiers are never used as canonical domain identifiers.

## Reconciliation
A reconciliation run compares expected state with provider state, records differences and emits a readiness decision. Unknown state is a blocking state for live mutation.
