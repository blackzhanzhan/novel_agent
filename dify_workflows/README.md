# Dify Workflow DSL Snapshots

This directory contains sanitized DSL YAML exports from the local live Dify runtime.

Current exported agents:

- `世界模型agent.yml`
- `文风学习agent.yml`
- `灵感大纲agent.yml`
- `续写agent.yml`
- `审核agent.yml`
- `读书存档agent.yml`

These files are for reproducible demo import and review. They do not contain model provider credentials, Dify API keys, knowledge-base data, PostgreSQL state, or plugin storage.

## Import Boundary

Importing these YAML files into Dify can recreate the app/workflow structure, prompts, graph, and tool references. It is not a full runtime restore.

The complete demo still requires:

- a running Dify instance;
- configured model providers and app API keys;
- the LoreGit backend ToolProvider reachable from Dify;
- the Flask backend and Vite frontend;
- per-book Git storage created by the local backend.

If the LoreGit ToolProvider endpoint changes, resync it after import with the deployment helper documented in `docs/DEPLOYMENT.md`.

## Marketplace Boundary

Dify Marketplace can distribute app templates, so these workflows can be adapted into marketplace-style templates. For this project, Marketplace should be treated as an optional template distribution channel, not the primary deployment method, because the core product depends on local book storage, Git branch/rollback semantics, and backend tools outside Dify.

Recommended public delivery:

1. publish the repository with these sanitized DSL exports;
2. document one-click/local bootstrap in `docs/DEPLOYMENT.md`;
3. optionally publish selected Dify agents as templates that point users back to the repo for the full runtime.
