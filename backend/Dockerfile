# syntax=docker/dockerfile:1

# ---- builder: install pinned, hash-checked dependencies into a venv ----
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

# ---- test: builder + pytest + sources (used by `make test` when no local venv) ----
FROM builder AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
WORKDIR /src
COPY . .
CMD ["python", "-m", "pytest"]

# ---- runtime: slim image with only the venv and the app code ----
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    LITELLM_LOG=ERROR
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
USER app
EXPOSE 8000
# Shell form so hosting platforms can inject $PORT. `exec` hands PID 1 to uvicorn so
# it receives SIGTERM directly. One worker: the in-memory cache is per process.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
