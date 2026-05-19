# Deployment And Reproducible Demo

This document defines the reproducible demo target for `novel_agent`. It is intentionally conservative: the demo must make the existing project chain easier to start, not replace the chain with local fake generation.

## Goal

A new evaluator should be able to run the workbench, connect it to a valid Dify runtime, import or open a demo book, and verify that outline, continuation, review, Git branch, and rollback flows still use the project-owned agents and LoreGit tools.

## Supported Modes

### Mode A: Local Windows Demo Pack

This mode is for the main development machine or a Windows laptop with Docker Desktop, Python, Node.js, and an existing Dify compose stack.

Target command:

```powershell
.\deploy\demo\bootstrap.ps1
```

First-time local setup:

```powershell
Copy-Item .\deploy\demo\.env.example .\deploy\demo\.env
# Fill Dify app keys and optional DeepSeek key in deploy/demo/.env.
.\deploy\demo\bootstrap.ps1
```

The bootstrap flow must:

- check Docker, Python, Node.js, npm, Git, and the Dify compose path;
- prepare local environment files from examples without committing secrets;
- optionally restore a sanitized Dify runtime seed;
- start Dify, Flask, and Vite through the existing startup scripts;
- synchronize the live LoreGit ToolProvider endpoint to the selected backend port;
- run smoke checks and print the frontend URL.

Useful switches:

- `-InitEnv`: create `deploy/demo/.env` from the safe example if it does not exist.
- `-SkipDify`: start only backend/frontend for local UI work.
- `-Status` / `-Stop`: forward to the underlying startup scripts.
- `-DryRun`: print what would be checked or started.

Dify runtime helper:

```powershell
.\deploy\demo\dify_runtime.ps1 -VerifyOnly
```

This helper defaults to verification and endpoint dry-run. Live Dify writes such as SQL restore, plugin-storage repair, or ToolProvider endpoint sync require `-IUnderstandThisWritesDify`.

### Mode B: Compose Demo Pack

This mode is for repeatable evaluation. It should make backend, frontend, demo storage, and smoke checks reproducible from repository-owned config.

Target command:

```powershell
docker compose --env-file deploy\demo\.env.example -f docker-compose.demo.yml up -d --build
```

The compose pack may connect to an external or separately restored Dify stack, but that dependency must be explicit. A compose process being alive is not enough; the smoke check must prove that Dify can reach the backend LoreGit tools.

Smoke command:

```powershell
docker compose --env-file deploy\demo\.env.example -f docker-compose.demo.yml run --rm smoke
```

The compose pack builds two local images:

- `deploy/demo/backend.Dockerfile`
- `deploy/demo/frontend.Dockerfile`

The default base images are MCR devcontainer images because they are usually reachable from Docker Desktop environments even when direct Docker Hub pulls are blocked. Override these in `deploy/demo/.env` when your environment prefers Docker Hub or a private mirror:

```text
BACKEND_BASE_IMAGE=python:3.11-slim
FRONTEND_BASE_IMAGE=node:22-bookworm-slim
```

The backend image mounts an isolated `demo-storage` volume and a `demo-runtime` volume. The pack must not mount or reuse `novel_git_server/storage/` from the host.
Use `COMPOSE_DIFY_BASE_URL` when the compose stack should talk to an external Dify runtime; keep `DIFY_BASE_URL` for the Windows bootstrap path.
The compose frontend sets `VITE_ALLOWED_HOSTS=frontend` so the smoke container can reach Vite through the Docker service name without weakening the normal local dev default.

## Dify Runtime Rule

Dify live PostgreSQL plus plugin storage are the runtime source of truth. The exported `dify_workflows/*.yml` files are sanitized DSL snapshots: they can be imported into Dify to recreate app/workflow structure, prompts, graphs, and tool references, but they are not a full runtime backup.

Current exported DSL files:

- `dify_workflows/世界模型agent.yml`
- `dify_workflows/文风学习agent.yml`
- `dify_workflows/灵感大纲agent.yml`
- `dify_workflows/续写agent.yml`
- `dify_workflows/审核agent.yml`
- `dify_workflows/读书存档agent.yml`

After importing DSL files into a fresh Dify runtime, configure model providers, app API keys, and the LoreGit ToolProvider endpoint before running the workbench.

Sanitized restore material may seed a demo runtime, but it must not contain:

- API keys or model credentials;
- private Dify backups;
- real user books from `novel_git_server/storage/`;
- local absolute paths that are required for every machine.

To restore an out-of-band sanitized SQL seed:

```powershell
.\deploy\demo\dify_runtime.ps1 `
  -RestoreSqlBackup `
  -BackupDir C:\path\to\sanitized_dify_seed `
  -RestartAfterRestore `
  -IUnderstandThisWritesDify
```

The seed directory must contain `dify.sql` and `dify_plugin.sql`. Private `.dify_backups` stay ignored and must not be committed.

## Authorship Boundary

Deployment scripts may orchestrate, restore, start, healthcheck, and validate. They must not generate outline cards or novel prose directly.

For demo content:

- outline files must be produced by the outline Agent;
- `chapter_draft.md` must be produced by the continuation Agent;
- review findings must be produced by the review Agent;
- Git operations must preserve the per-book branch and rollback model.

## Healthcheck Contract

A reproducible demo is accepted only when these checks pass:

- backend `/health` is reachable;
- frontend is reachable;
- Dify API is reachable;
- Dify sandbox or API can reach Flask LoreGit `/health` through the configured endpoint;
- the LoreGit ToolProvider endpoint matches the selected backend port;
- no secret or real storage file becomes tracked by Git.

## Current Slice Status

This file defines the deployment contract. The concrete bootstrap, Dify restore, compose, and smoke scripts are implemented by the subsequent `DEPLOY-LOCAL-1`, `DEPLOY-DIFY-1`, `DEPLOY-COMPOSE-1`, and `DEPLOY-E2E-1` slices.
