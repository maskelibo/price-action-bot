FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_SYSTEM_PYTHON=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        ca-certificates \
        libpq-dev \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv pip install --system -e ".[dev]" || uv pip install --system -e .

COPY . .

RUN useradd -m -u 1000 pa && chown -R pa:pa /app
USER pa

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "price_action.api.server"]
