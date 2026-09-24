# Referencia — copiar/adaptar a Dockerfile en raíz del repo
# Build: docker build -t genesis-api:local .

FROM python:3.12-slim-bookworm AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.runtime.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.runtime.txt \
    && pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GENESIS_HOST=0.0.0.0 \
    GENESIS_PORT=8445 \
    GENESIS_FAQ_PATH=/app/data/kb_faq_vf01.json \
    GENESIS_FAQ_OVERLAY_PATH=/app/data/kb_faq_overlay_fase1.json \
    GENESIS_RAG_NO_HUMAN_ESCALATION_INSTITUTIONAL=1

RUN groupadd -r genesis && useradd -r -g genesis genesis
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY pyproject.toml ./
COPY src ./src
COPY prompts ./prompts
COPY schemas ./schemas
COPY data ./data
COPY docs ./docs
COPY scripts/run_contract_inspector.py ./scripts/

RUN chown -R genesis:genesis /app
USER genesis

EXPOSE 8445

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8445/health', timeout=3)"

CMD ["python", "scripts/run_contract_inspector.py"]
