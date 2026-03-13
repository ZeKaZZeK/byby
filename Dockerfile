FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e "." || true

# Copy source
COPY byby/ byby/

# Install the package properly
RUN pip install --no-cache-dir -e "."

# Create non-root user
RUN useradd -m -u 1000 byby && chown -R byby:byby /app
USER byby

# Expose Prometheus metrics port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import byby; print('ok')" || exit 1

CMD ["byby", "paper"]
