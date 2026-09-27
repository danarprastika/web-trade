# Runtime Architecture

> Status: FINAL FROZEN BASELINE v1.0 — subordinate to FINAL_SPECIFICATION/.

## Purpose
Define runtime dependencies and critical paths.

## Critical path

Market event → normalized state → signal → risk → OMS → execution → fill → reconciliation.

## Control path

Owner/Web/Telegram → governed command service → authorization → task/control action → audit.

## Research path

Data snapshot → experiment → evaluation → immutable evidence → promotion request.
