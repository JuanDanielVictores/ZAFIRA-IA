# syntax=docker/dockerfile:1
# Production image: FastAPI + Poetry, multi-stage (builder → slim runtime).
#   docker build -t zafira-ia:local .
#   docker run --rm -p 8000:8000 zafira-ia:local

ARG PYTHON_VERSION=3.12-slim

# ---------- Builder: resolve and install dependencies ----------
FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=2.0.1 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN pip install --upgrade pip setuptools wheel \
    && pip install "poetry==${POETRY_VERSION}"

WORKDIR /app

COPY pyproject.toml poetry.lock poetry.toml ./
COPY src ./src

RUN poetry install --only main --no-interaction --no-ansi

# ---------- Runtime: no compilers, pure-python deps only ----------
FROM python:${PYTHON_VERSION} AS runtime

ARG APP_USER=appuser
ARG APP_GROUP=appgroup
ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    TZ=America/Guayaquil \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tzdata \
    && ln -fs /usr/share/zoneinfo/America/Guayaquil /etc/localtime \
    && echo "America/Guayaquil" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g "${APP_GID}" -r "${APP_GROUP}" \
    && useradd -u "${APP_UID}" -r -g "${APP_GROUP}" -d /app -s /sbin/nologin "${APP_USER}"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY pyproject.toml poetry.toml /app/

RUN chown -R "${APP_USER}:${APP_GROUP}" /app

USER ${APP_USER}

EXPOSE 8000

# Render injects PORT at runtime. The fallback keeps local Docker usage simple.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
