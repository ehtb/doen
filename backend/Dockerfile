# Doen backend — FastAPI + the stdio MCP server share this image.
# Built from source (spec 0008). Migrations run on boot, then uvicorn serves :8000.
FROM python:3.13-slim

WORKDIR /app

COPY backend/ ./
RUN pip install --no-cache-dir .

EXPOSE 8000

# Auto-migrate on boot (constraint 1: no manual migration step), then serve.
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
