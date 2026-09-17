# Contributing to BauClock

BauClock welcomes focused contributions that improve correctness, security, maintainability, and construction-site usability.

## Before making a large change

Open or reference an issue first. Describe the problem, affected roles/sites/data paths, expected behavior, and how the change will be verified. Keep unrelated refactors out of the same pull request.

## Pull-request expectations

A good PR should:

- stay narrowly scoped;
- preserve tenant/company/site isolation;
- include regression tests for access-control or time-correction behavior;
- document schema or migration changes;
- explain any ArbZG/compliance behavior it touches;
- avoid production personal data and secrets;
- keep payroll/HR scope expansion out unless explicitly agreed;
- state validation performed and any known limitations.

## Local validation

Install development requirements and run the relevant targeted tests first, then the full suite where practical:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
pytest
```

For model/schema changes, review Alembic migrations before applying them.

## AI-assisted contributions

AI tools may be used for research, implementation, tests, or review. Contributors remain responsible for the final diff, licensing, security, data protection, and correctness. Generated code must be reviewed and tested like handwritten code.

Do not send production employee data, secrets, credentials, or private deployment configuration to public AI prompts or public repository artifacts.

## Security-sensitive changes

Changes involving authentication, authorization, tenant isolation, personal/time data, exports, retention, or audit history need focused review. Vulnerabilities should be reported privately according to [SECURITY.md](SECURITY.md).

## Scope discipline

BauClock is a time-tracking and compliance-support project. Avoid silently turning it into a general payroll, HR, or legal-adjudication platform.

## Maintainers

See [MAINTAINERS.md](MAINTAINERS.md).
