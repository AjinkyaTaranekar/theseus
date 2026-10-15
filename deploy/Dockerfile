# The Theseus API. Built from the repo root: docker build -f deploy/Dockerfile .
# Secrets never enter the image: .dockerignore excludes .env, and compose passes it at run time.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml README.md ./
COPY theseus ./theseus
RUN pip install .

# Read at run time, relative to /app: fixtures for {fixture} requests, the stub sample, the world root.
COPY fixtures ./fixtures
COPY tests/data ./tests/data
COPY demo-infra ./demo-infra

RUN useradd --system --uid 10001 theseus && chown -R theseus /app
USER theseus

EXPOSE 8000
CMD ["uvicorn", "theseus.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
