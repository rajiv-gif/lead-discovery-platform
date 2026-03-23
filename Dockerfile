FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

ARG CACHEBUST=3
RUN pip install --no-cache-dir -e .

RUN mkdir -p data/pages data/llm_runs data/exports data/website_checks

ENV DASHBOARD_HOST=0.0.0.0

CMD ["leads-ui"]
