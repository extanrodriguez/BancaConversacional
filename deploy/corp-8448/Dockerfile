# Genesis Cognitive API — container for port 8448
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GENESIS_HOST=0.0.0.0 \
    GENESIS_PORT=8448 \
    GENESIS_SERVE_UI=true \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd -r genesis && useradd -r -g genesis genesis \
    && apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.runtime.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.runtime.txt \
    && pip install --no-cache-dir .

COPY prompts ./prompts
COPY schemas ./schemas
COPY data ./data
COPY Knowledge_Base ./Knowledge_Base
COPY scripts/run_contract_inspector.py ./scripts/

RUN chown -R genesis:genesis /app \
    && apt-get purge -y gcc || true \
    && apt-get autoremove -y || true

USER genesis

EXPOSE 8448

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8448/health', timeout=3)"

CMD ["python", "scripts/run_contract_inspector.py"]
