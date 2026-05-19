# Dify 数据持久化与备份恢复

## 持久化现状

PostgreSQL 数据通过 bind mount 挂载到宿主机：

```
/home/zzy/dify/docker/volumes/db/data  →  /var/lib/postgresql/data (容器内)
实际 PGDATA：/var/lib/postgresql/data/pgdata
```

Dify API storage 和 plugin daemon storage 同样已 bind mount，容器重建不丢数据。

验证命令：

```bash
docker inspect docker-db_postgres-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

## 备份

```powershell
.\scripts\dify_pg_backup.ps1
```

默认输出到 `.dify_backups/<stamp>/`，包含：

- `dify.sql` — 主库完整 dump
- `dify_plugin.sql` — 插件库完整 dump
- `globals.sql` — 全局角色/权限
- `manifest.json` — 时间戳 + SHA256

`.dify_backups/` 已加入 `.gitignore`，不进版本库。

## 恢复

```powershell
.\scripts\dify_pg_restore.ps1 -BackupDir .dify_backups\<stamp>
```

恢复后重启容器：

```powershell
wsl -d Ubuntu -- bash -lc "cd /home/zzy/dify/docker && docker compose restart api worker plugin_daemon"
```

## 优先级说明

恢复顺序（高到低）：

1. **SQL 备份**（`.dify_backups/`）— bind mount 在，直接恢复，最可靠
2. **bind mount 原地**（`/home/zzy/dify/docker/volumes/db/data`）— 容器重建后数据仍在，`docker compose up -d` 即可
3. **`.runtime/` 证据**（旧 SQL patch 序列）— 仅在以上两种都不可用时使用，需要 `scripts/recover_dify_runtime.py`

**不要把 `dify_workflows/*.yml` 当作恢复源**——YAML 是历史导出快照，不含运行时 workflow 版本和 plugin 状态。

## 危险操作边界

- `docker compose down -v` 会删除匿名卷，**不要执行**
- 不要手动删除 `/home/zzy/dify/docker/volumes/db/`
- 恢复前先跑一次备份脚本留存当前状态

## 状态检测

```powershell
.\scripts\start_dify.ps1 -Status
```

输出包含：

- `db_persistence=bind_mount=<path>` — 确认 bind mount 路径
- `backup=latest=<stamp>` — 最近一次备份时间戳
- 若检测到匿名卷会打印 WARNING
