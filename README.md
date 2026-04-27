# SEK Zeiterfassung (BauClock)

Telegram bot (@SEKbaubot) and backend for construction site time tracking, pause compliance (ArbZG §4), and reporting.

## Project Structure
```text
/bauclock
├── /api           # FastAPI backend 
├── /bot           # aiogram 3.x Telegram bot
├── /db            # shared db logic & SQLAlchemy models
├── docker-compose.yml
├── .env.example
└── README.md
```

## Quick Start

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in your variables (Token, DB password, Encryption Key).
    ```bash
    cp .env.example .env
    ```
3. Run the complete stack via Docker
    ```bash
    docker-compose up --build
    ```

## Development

Create a local virtual environment from the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Copy the example environment file and fill in local secrets:

```bash
cp .env.example .env
python -c "import os; print(os.urandom(32).hex())"  # ENCRYPTION_KEY
python -c "import os; print(os.urandom(16).hex())"  # HASH_PEPPER
```

Start local Postgres and Redis:

```bash
docker-compose up -d postgres redis
```

Run the test suite:

```bash
pytest
```

### Alembic Migrations

Alembic is configured in `db/alembic.ini` and reads the application database URL from the same environment as the app.

Apply migrations from the repository root:

```bash
alembic -c db/alembic.ini upgrade head
```

Create a new migration from model changes:

```bash
alembic -c db/alembic.ini revision --autogenerate -m "describe_change"
```
