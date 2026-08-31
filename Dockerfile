# Cloud Run image for csf-gateway.
# Build target: linux/amd64 (Cloud Build default). Multi-stage to keep the
# runtime image small — poetry + build tools stay in the builder layer.

FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

RUN pip install "poetry==${POETRY_VERSION}"

WORKDIR /build

# Copy dep manifests first so this layer caches across code-only changes
COPY pyproject.toml poetry.lock ./

# Install to system site-packages inside the builder image so we can copy them out
RUN poetry install --no-root --only main


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Pull installed packages + console scripts from the builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source. One image, three run targets via command override:
# csf-gateway (Cloud Run service, uvicorn), csf-worker (Cloud Run Job, runs
# csf_specialists/worker.py), and csf-ui (Cloud Run service, streamlit run
# csf_ui/app.py) — rather than maintaining separate builds.
COPY csf_gateway/ ./csf_gateway/
COPY csf_specialists/ ./csf_specialists/
COPY csf_coordinator/ ./csf_coordinator/
COPY csf_ui/ ./csf_ui/

# Streamlit reads its theme from $CWD/.streamlit/config.toml, and csf-ui runs
# `streamlit run csf_ui/app.py` from this WORKDIR. Without this the deployed UI
# falls back to the stock theme while local dev looks correct.
COPY .streamlit/ ./.streamlit/

# Run as non-root (Cloud Run best practice)
RUN useradd --create-home --shell /bin/bash appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# `exec` so uvicorn receives SIGTERM directly; ${PORT} is expanded by the shell
CMD exec uvicorn csf_gateway.app.main:app --host 0.0.0.0 --port ${PORT}
