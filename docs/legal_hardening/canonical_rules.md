# Canonical Rules

- Preserve the core model: `company -> site -> worker/person -> time events -> summaries -> payments/export`.
- Preserve `CONTRACT` versus `OVERTIME` as separate business outputs.
- Preserve QR/GPS/bot-first operational flow.
- Preserve tenant isolation. No silent cross-company data bleed.
- Preserve bot contour separation. Shared, dedicated, and platform contexts must not collapse into one access path.
- Preserve data separation:
  - raw events are not summaries
  - corrections are not raw events
  - audit evidence is not operational summary state
- Hardening work should patch scope, traceability, retention, and compliance visibility.
- Hardening work should not rewrite the architecture for elegance.
- Hardening work should not expand into payroll, full DATEV accounting, or broad HR modules.
