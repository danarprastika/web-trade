# IMPLEMENTATION REPOSITORY LAYOUT
## Recommended Evidence-Oriented Structure

Status: NORMATIVE GUIDANCE

This document defines a recommended organization for implementation artifacts. It does not mandate a specific programming language or framework.

## 1. Separation

Keep these concerns distinguishable:

- domain/core;
- application/use cases;
- infrastructure/adapters;
- persistence;
- eventing;
- security;
- configuration;
- observability;
- tests;
- gate evidence.

## 2. Suggested Evidence Tree

`audit/implementation/`
- `gates/G1/`
- `gates/G2/`
- `gates/G3/`
- ...
- `gates/G11/`
- `change_requests/`
- `security/`
- `reproducibility/`

## 3. Evidence Naming

Prefer:
`G<n>_<STATUS>_<YYYYMMDD>.md`

Example:
`G1_PASS_20260924.md`

## 4. Generated Artifacts

Generated build/test artifacts must not replace normative documentation.

## 5. Secrets

Never store:
- API keys;
- broker credentials;
- Telegram bot secrets;
- private keys;
- production tokens

inside source, tests, documentation, or gate evidence.

Use the project's approved secret mechanism when the relevant gate authorizes it.
