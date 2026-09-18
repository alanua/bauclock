# Quickstart: verify BauClock safely

This quickstart uses only local development configuration and synthetic test fixtures. It does not connect to a production database, Telegram bot, worker account, or deployment.

## Requirements

- Python 3.11+
- Git

## 1. Clone and create an isolated environment

```bash
git clone https://github.com/alanua/bauclock.git
cd bauclock
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r api/requirements.txt -r bot/requirements.txt -r requirements-dev.txt
```

## 2. Set test-only configuration

Use values only for the local test process:

```bash
export ENCRYPTION_KEY=0000000000000000000000000000000000000000000000000000000000000000
export HASH_PEPPER=test-hash-pepper
export DATABASE_URL=sqlite+aiosqlite:///./bauclock-test.db
export REDIS_URL=redis://localhost:6379/0
```

These are synthetic development values, not production secrets.

## 3. Run a focused security-sensitive regression slice

```bash
python -m pytest -q tests/test_time_corrections.py
```

Then run the full suite before submitting a pull request:

```bash
python -m pytest
```

## What this verifies

The focused module exercises manual-time correction rules and access boundaries with generated test data. It does not authorize real corrections or touch external systems.

## Do not use production data

Do not copy real employee records, Telegram tokens, database credentials, encryption material, exports, or deployment environment files into a public checkout, fixture, issue, or pull request.
