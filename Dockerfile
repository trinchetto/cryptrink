# Cryptrink Docker Image
# Multi-stage build for smaller final image

# Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=2.0.1 \
    POETRY_HOME=/opt/poetry \
    POETRY_VENV=/opt/poetry-venv \
    POETRY_CACHE_DIR=/opt/.cache

RUN python -m venv $POETRY_VENV \
    && $POETRY_VENV/bin/pip install -U pip setuptools \
    && $POETRY_VENV/bin/pip install poetry==$POETRY_VERSION

ENV PATH="${POETRY_VENV}/bin:${PATH}"

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (without dev dependencies)
RUN poetry config virtualenvs.in-project true \
    && poetry install --only main --no-interaction --no-ansi

# Copy source code
COPY src/ ./src/

# Runtime stage
FROM python:3.12-slim as runtime

WORKDIR /app

# Create non-root user
RUN groupadd --gid 1000 cryptrink \
    && useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home cryptrink

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY --from=builder /app/src /app/src

# Set environment variables
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Switch to non-root user
USER cryptrink

# Default command
ENTRYPOINT ["python", "-m", "cryptrink.cli"]
CMD ["--help"]
