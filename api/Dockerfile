FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies for WeasyPrint and asyncpg
RUN apt-get update && apt-get install -y \
    build-essential \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    libcairo2 \
    libffi-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements if we had them (using poetry or reqs)
# For now we create a requirements inline or you can mount it
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY ./api /app/api
COPY ./db /app/db

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
