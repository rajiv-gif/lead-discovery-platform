FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Install the package
RUN pip install --no-cache-dir -e .

# Create data directories
RUN mkdir -p data/pages data/llm_runs data/exports data/website_checks

# Railway injects PORT; DASHBOARD_PORT reads it.
# DASHBOARD_HOST must be 0.0.0.0 for Railway to route traffic in.
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8000

EXPOSE 8000

CMD ["leads-ui"]
