# Build stage — pip, hatchling, and build artefacts stay here only.
# No build toolchains survive into the runtime layer.
FROM python:3.13-slim AS builder
WORKDIR /build
COPY backend/ ./
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir .

# Runtime stage — lean image with only the venv and app source.
# No pip, no build toolchains, no dev packages.
FROM python:3.13-slim AS runtime
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY backend/app ./app
COPY backend/migrations ./migrations
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level ${LOG_LEVEL:-info}"]
