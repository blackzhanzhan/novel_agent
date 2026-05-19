ARG BACKEND_BASE_IMAGE=mcr.microsoft.com/devcontainers/python:3.11-bookworm
FROM ${BACKEND_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app/novel_agent

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY novel_git_server/requirements.txt novel_git_server/requirements.txt
RUN pip install --no-cache-dir -r novel_git_server/requirements.txt

COPY . .

WORKDIR /app/novel_agent/novel_git_server

EXPOSE 8000

CMD ["python", "app.py"]
