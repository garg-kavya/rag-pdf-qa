# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools needed for faiss-cpu and numpy C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# System packages: tesseract-ocr + poppler (pdf2image) for OCR fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder (no build tools in final image)
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy only application source — no tests, docs, scripts, or secrets
COPY app/ ./app/
COPY pyproject.toml .

# Non-root user for security
RUN useradd -m -u 1000 appuser \
    && mkdir -p uploads data \
    && chown -R appuser:appuser /app

USER appuser

# Railway injects PORT; fall back to 8000 for local docker run
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/api/v1/health')" || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
