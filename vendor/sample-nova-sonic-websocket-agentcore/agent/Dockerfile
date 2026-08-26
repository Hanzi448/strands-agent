# Use ARM64 Python base image for AgentCore Runtime
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.13-slim

# Install system dependencies for PyAudio
# PyAudio is required by BidiAgent even though we don't directly use mic/speakers
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libasound-dev \
    libportaudio2 \
    libportaudiocpp0 \
    portaudio19-dev \
    gcc \
    python3-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY strands_agent.py .

# Create non-root user for running the application
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set environment variable to indicate container environment
ENV CONTAINER_ENV=true

# Expose port 8080 (required by AgentCore Runtime)
EXPOSE 8080

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping').read()"]

# Start the FastAPI application with uvicorn
CMD ["uvicorn", "strands_agent:app", "--host", "0.0.0.0", "--port", "8080"]
