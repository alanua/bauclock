FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Basic dependencies
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY ./bot /app/bot
COPY ./db /app/db

CMD ["python", "-m", "bot.main"]
