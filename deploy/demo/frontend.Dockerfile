ARG FRONTEND_BASE_IMAGE=mcr.microsoft.com/devcontainers/javascript-node:22-bookworm
FROM ${FRONTEND_BASE_IMAGE}

ENV NODE_ENV=development \
    HOST=0.0.0.0 \
    PORT=5173

WORKDIR /app/novel_agent/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
