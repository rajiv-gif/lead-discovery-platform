FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Force fresh install — bypasses any stale layer cache
RUN pip install --no-cache-dir \
    sqlalchemy>=2.0 \
    alembic>=1.13 \
    psycopg2-binary>=2.9 \
    typer>=0.12 \
    python-dotenv>=1.0 \
    rich>=13.0 \
    httpx>=0.27 \
    beautifulsoup4>=4.12 \
    trafilatura>=1.12 \
    lxml>=5.0 \
    phonenumbers>=8.13 \
    dnspython>=2.6 \
    anthropic>=0.25 \
    fastapi>=0.111 \
    "uvicorn[standard]>=0.29" \
    jinja2>=3.1 \
    python-multipart>=0.0.9 \
    itsdangerous>=2.1 \
    && pip install --no-cache-dir -e .

RUN mkdir -p data/pages data/llm_runs data/exports data/website_checks

ENV DASHBOARD_HOST=0.0.0.0

CMD ["leads-ui"]
