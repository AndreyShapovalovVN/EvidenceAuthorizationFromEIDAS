FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        git \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system --gid 10001 app && \
    useradd --system --uid 10001 --gid app --home-dir /nonexistent --shell /usr/sbin/nologin app

COPY pyproject.toml uv.lock README.md ./
COPY main.py redis_keys.py ./
COPY lib ./lib
COPY Models ./Models
COPY static ./static
COPY templates ./templates

ENV PYTHONPATH=/app

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

RUN uv sync \
    --frozen \
    --no-dev \
    --no-build \
    --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
