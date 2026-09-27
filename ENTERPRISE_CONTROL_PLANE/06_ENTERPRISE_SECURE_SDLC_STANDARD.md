# Enterprise Secure SDLC Standard

## Status
Controlled engineering standard.

## Lifecycle
Plan -> design review -> implementation -> automated validation -> peer review -> security validation -> release approval -> deployment -> verification -> monitoring.

## Required Practices
- least privilege
- dependency and supply-chain review
- secret scanning and secure secret handling
- input validation
- authorization at trust boundaries
- reproducible builds where required
- security-focused tests for security-sensitive changes
- rollback or containment procedure for production-impacting releases

No document here grants production deployment authority.
