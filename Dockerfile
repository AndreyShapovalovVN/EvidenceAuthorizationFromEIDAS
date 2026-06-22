FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
        libffi-dev \
        gcc \
        git  && \
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
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

ENV PATH="/app/.venv/bin:$PATH"
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
