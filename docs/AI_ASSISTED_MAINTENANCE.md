# AI-Assisted Maintenance

BauClock uses AI-assisted engineering as part of a maintainer-controlled workflow.

## Current uses

Tools such as Codex may assist with:

- investigating bugs and access-control edge cases;
- implementing narrowly scoped fixes;
- generating regression tests;
- reviewing pull-request diffs;
- summarizing issue/PR history and handoffs;
- dependency/runtime troubleshooting;
- maintenance automation and release-readiness checks.

## Human responsibility

The primary maintainer remains responsible for merge decisions, deployments, schema changes, security boundaries, production data access, and compliance-related behavior. AI output is reviewed and validated before becoming project state.

## Why API-backed maintenance helps

BauClock combines role-aware business logic, time-event history, correction workflows, database migrations, Telegram UX, reporting, and German compliance support. Small changes can cross multiple trust boundaries, so repeatable review and regression coverage matter more than raw code generation.

API credits can support automated issue triage, focused test/review loops, dependency/runtime diagnostics, release preparation, and maintenance summaries while preserving human merge authority.

## Data-protection rule

Do not put production employee records, credentials, encryption keys, tokens, or private deployment data into public prompts, public issues, or repository artifacts. Use synthetic fixtures for tests and public examples.
