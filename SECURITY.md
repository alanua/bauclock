# Security Policy

BauClock processes work-time and employment-related data, so authorization, tenant isolation, correction history, exports, and secret handling are security-sensitive.

## Supported code

Security fixes target the current `main` branch and any explicitly documented supported deployment line. Old snapshots or unmaintained forks should not be assumed supported.

## Reporting a vulnerability

Do **not** post exploitable details, personal data, production records, tokens, database credentials, encryption material, or a working proof-of-concept in a public issue.

Preferred route:

1. Use GitHub private vulnerability reporting / Security Advisories for this repository when available.
2. If that route is unavailable, contact the primary maintainer `@alanua` through the GitHub profile and request a private reporting channel. A public issue may be used only to request contact, without sensitive details.

Please include the affected component, impact, prerequisites, reproduction outline, and any mitigation you have identified.

## High-sensitivity areas

Pay particular attention to:

- cross-company or cross-site data access;
- role/permission escalation;
- manual correction authorization bypasses;
- exposure of worker/time data;
- insecure exports or reports;
- secret/configuration leakage;
- audit-history or retention bypasses;
- unsafe migration behavior affecting tenant boundaries.

## Coordinated handling

The maintainer will validate the report, identify affected versions/paths, prepare a bounded fix and regression coverage, and coordinate disclosure after a repair is available. No fixed response-time SLA is promised at the current project stage.
