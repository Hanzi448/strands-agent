# AgentCore Runtime requires an ARM64 container image.
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# No PyAudio/PortAudio layer here, unlike the vendored sample's Dockerfile:
# this container never opens a sound device (`agents/agentcore_app.py`
# takes audio as JSON events over the WebSocket), and `requirements.txt`
# installs `strands-agents[bidi]`, not `[bidi-pyaudio]`.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the two packages the deployed entrypoint reaches -- `infra/`,
# `tests/`, and the dev-only `requirements-dev.txt` never leave the build
# context at all (see `.dockerignore`).
COPY agents/ ./agents/
COPY tools/ ./tools/

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENV CONTAINER_ENV=true

# Required by AgentCore Runtime.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/ping').read()"]

CMD ["uvicorn", "agents.agentcore_app:app", "--host", "0.0.0.0", "--port", "8080"]
