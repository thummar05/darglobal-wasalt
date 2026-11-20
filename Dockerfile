# Multi-stage / Production Dockerfile for Real Estate Chatbot (FastAPI + LangGraph + ChromaDB)
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    CHROMA_PERSIST_DIRECTORY=data/chroma

# Set working directory
WORKDIR /app

# Install minimal OS dependencies for ChromaDB and curl healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ ./app/
COPY data/ ./data/
COPY scrapers/ ./scrapers/
COPY ingest.py .

# Copy prebuilt frontend so the backend can optionally serve it directly
COPY frontend/dist/ ./frontend/dist/

# Expose standard port
EXPOSE 8000

# Health check to ensure service readiness
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Start FastAPI application via Uvicorn (Render sets $PORT dynamically)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
