# Current Priorities

Priority order for Germany-focused hardening:

1. Access control on dashboard and privileged APIs.
2. Role isolation for owner, accountant, objektmanager, worker, and subcontractor boundaries.
3. Audit logging for sensitive mutations.
4. Manual correction traceability with actor and reason.
5. ArbZG support as warning and reporting signals, not hard legal adjudication.
6. Retention and privacy controls with dry-run reporting and retention holds.
7. DATEV and payroll-facing export boundaries with `CONTRACT`-only enforcement.
8. Legal onboarding evidence with versioned acceptance and acknowledgement logs.

Implementation reminders:

- Keep routes thin where possible and move sensitive policy checks into services.
- Use canonical writes for new compliance fields, while keeping compatibility layers where the branch already contains legacy fields.
- Prefer narrow migrations and additive patches over refactors.
