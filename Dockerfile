# Pin the exact base-image digest used for the verified submission build.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HOST=0.0.0.0

# Set work directory
WORKDIR /app

# Runtime healthcheck plus compatibility build tools for environments where a
# binary dependency wheel is unavailable.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy dependencies list first for efficient Docker layer caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ app/
COPY tests/ tests/

# The API does not require root privileges.
RUN useradd --create-home --uid 10001 gridwise \
    && chown -R gridwise:gridwise /app
USER gridwise

# Expose default HTTP service port
EXPOSE 8000

# Healthcheck for Docker container
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run API server using Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
