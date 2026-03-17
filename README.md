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

- Start local Postgres & Redis using `docker-compose up -d postgres redis`
- Navigate to `/api` or `/bot` with your virtual environment activated, install `requirements.txt`.
- Run alembic migrations (to be added) in `/db`.
