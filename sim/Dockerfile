# Minimal image for sage.sim docker_runner (pytest / tool isolation POC).
FROM python:3.11-slim-bookworm
RUN pip install --no-cache-dir pytest
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python", "--version"]
