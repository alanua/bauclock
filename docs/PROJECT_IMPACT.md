# Project impact and current stage

BauClock is an early-stage open-source construction time-tracking and compliance-support project for small teams in Germany. It is designed around a practical problem: recording working time and corrections without losing site, company, role, and audit boundaries.

This document does not claim external adoption, customer counts, download numbers, or legal certification that the project cannot substantiate.

## What the project is for

BauClock combines a FastAPI backend, Telegram-facing workflows, persistent time events, role/site/company access rules, manual correction history, compliance-support checks, and reporting foundations.

The project is deliberately narrower than payroll or general HR software. It can support German ArbZG-oriented workflows, but it does not provide legal advice and does not replace payroll, tax, or legal review.

## Why maintenance is security-sensitive

Time-tracking data can affect workers, employers, payroll inputs, and compliance records. Small authorization errors can become cross-company disclosure or unauthorized correction bugs. Maintenance therefore emphasizes:

- tenant/company/site isolation;
- explicit role checks;
- regression tests for manual corrections;
- auditable correction history;
- migration review;
- secret separation;
- synthetic public fixtures instead of production worker data.

## Maintainer workflow

The repository is maintained through scoped issues and pull requests, CI-backed pytest validation, access-control regression tests, review, and explicit merge decisions. AI tools may assist with implementation or review, but the maintainer remains responsible for the final diff and any deployment.

Skeleton may be used as an external engineering control plane for bounded task routing, review, and audit. BauClock remains a separate application repository and does not delegate application authorization semantics to Skeleton.

## Current maturity

BauClock is under active development. The public repository is suitable for code review and local development, but production deployments remain environment-specific and require their own data-protection, operational, legal, and security review.
