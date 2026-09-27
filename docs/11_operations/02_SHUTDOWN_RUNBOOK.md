# Shutdown Runbook

> Status: FINAL FROZEN BASELINE v1.0 — subordinate to FINAL_SPECIFICATION/.

## Purpose
Safely stop the system.

## Flow

Disable new trading → handle/cancel governed open orders → reconcile → persist state → stop services.
