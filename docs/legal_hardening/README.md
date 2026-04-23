# Legal Hardening Notes

This folder is a repo-local mirror for executor work when external knowledge-base files are unavailable in the workspace.

Use these notes as guardrails, not as a redesign brief.

- Preserve the canonical chain: `company -> site -> worker/person -> time events -> summaries -> payments/export`.
- Keep `CONTRACT` and `OVERTIME` separated at reporting and export boundaries.
- Keep tenant isolation and bot contour separation intact.
- Keep evidence, summaries, corrections, and audit records as separate concerns.
- Do not turn legal hardening into a payroll engine, large DATEV module, or HR suite.

Current implementation focus:

- token-gated dashboard and scoped dashboard APIs
- role isolation for finance/compliance/admin edges
- auditable mutations and manual correction traceability
- legal onboarding evidence and compliance visibility
- retention reporting and hold-safe execution
- ArbZG reporting support as warnings and review aids
