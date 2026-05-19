import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict

from utils.git_utils import (
    DEFAULT_BOOTSTRAP_LAYOUT_MESSAGE,
    ensure_initial_commit,
    ensure_repo,
    ensure_tracked_files,
    format_git_error,
    get_head_commit,
    has_valid_head,
    is_nothing_to_commit_error,
    repo_lock,
    run_git,
)

try:
    from pypinyin import lazy_pinyin
except ImportError:  # pragma: no cover - runtime fallback when dependency is missing
    lazy_pinyin = None


DEFAULT_WORLD_MODEL = """# World Model

> 本文件不是散设定档案，而是后续续写、审核、大纲与风格工作流共同读取的创作约束引擎。
> 每条重要设定都应说明它对剧情推进、冲突制造、读者承诺或一致性审查的作用。

## 读者承诺与主轴

- 核心看点：
- 题材/卖点契约：
- 长线情绪驱动：

## 冲突发动机

- 长期冲突：
- 中期压力源：
- 单章可复用矛盾：

## 硬约束

- 已确立事实：
- 力量/资源/代价规则：
- 不可轻易突破的禁区：

## 软假设

- 可调整设定：
- 待作者确认：

## 未回收承诺

- 伏笔/谜团：
- 情感债/关系债：
- 必须回收的读者期待：

## 矛盾与风险

- 已发现矛盾：
- 高风险写法：

## 下游工作流接口

- 给续写 agent：
- 给审核 agent：
- 给大纲 agent：
- 给文风 agent：

"""
DEFAULT_SUMMARY = "# Summary\n\n"
DEFAULT_STYLE_GUIDE = "# 文风指南\n\n"
DEFAULT_STYLE_FINGERPRINT = "# 叙事结构指纹\n\n"
DEFAULT_STYLE_REVIEW = "# 作者可读审查\n\n"
DEFAULT_STYLE_CONSTRAINTS_FOR_CONTINUATION = "# 续写硬约束\n\n"
DEFAULT_STATUS_CARD = """# 状态卡片

> 本文件记录当前创作运行态，服务下一章续写和即时一致性检查；不要把长期世界设定堆在这里。

## 当前时间线

- 最新章节/事件：
- 当前地点：
- 当前 POV：

## 角色状态

- 主角：
- 关键配角：
- 反派/压力源：

## 当前冲突与目标

- 本阶段目标：
- 当前阻力：
- 下一步必须推进：

## 开放承诺

- 待读者兑现：
- 待解释信息：
- 待回收伏笔：

## 下一章约束

- 必须写到：
- 不要误写：
- 需要核对：

"""
DEFAULT_ERROR_ARCHIVE = "# 错误档案\n\n"
DEFAULT_DOMAIN_RULES = (
    "# 领域规则\n\n"
    "> 本文件存放可复用、可审核、可由工具消费的领域规则；不要在代码中硬编码题材规则。\n"
    "> 只有稳定约束才沉淀为 `domain-rule` JSON 代码块；临时状态写入 status_card.md，长期设定写入 world_model.md。\n\n"
    "## 规则沉淀原则\n\n"
    "- 每条规则必须说明适用范围、触发条件和违反后果。\n"
    "- 规则应服务续写和审核，而不是复制背景资料。\n\n"
    "## domain-rule 示例\n\n"
    "```domain-rule\n"
    "{\n"
    "  \"id\": \"example_rule_id\",\n"
    "  \"type\": \"context_forbidden_terms\",\n"
    "  \"scope\": \"chapter_draft.md\",\n"
    "  \"description\": \"说明这条规则保护的创作约束。\",\n"
    "  \"context_terms\": [\"示例上下文\"],\n"
    "  \"forbidden_terms\": [\"示例禁用词\"]\n"
    "}\n"
    "```\n\n"
)
DEFAULT_BRAINSTORM = "# 头脑风暴\n\n"
DEFAULT_MASTER_OUTLINE = "# 总纲\n\n"
DEFAULT_ARC_OUTLINE = "# 篇章大纲\n\n"
DEFAULT_CHAPTER_OUTLINE = "# 逐章大纲\n\n"
DEFAULT_CHAPTER_DRAFT = "# 续写草稿\n\n"
BOOK_GITIGNORE = "*.tmp\n*.log\n__pycache__/\n.locks/\nconflicts/\n"
BOOK_ID_PATTERN = re.compile(r"^[\w\-]{1,64}$", re.UNICODE)
CHAPTER_FILE_INDEX_PATTERN = re.compile(r"^(\d+)(?:_|\.|$)")
SAFE_SLUG_PATTERN = re.compile(r"[^a-z0-9_-]+")
TRACKED_LAYOUT_FILES = (
    "world_model.md",
    "summary.md",
    "status_card.md",
    "style_guide.md",
    "style_fingerprint.md",
    "style_review.md",
    "style_constraints_for_continuation.md",
    "error_archive.md",
    "domain_rules.md",
    "brainstorm.md",
    "master_outline.md",
    "arc_outline.md",
    "chapter_outline.md",
    "metadata.json",
    ".gitignore",
)
CORE_LAYOUT_DEFAULTS = {
    "world_model.md": DEFAULT_WORLD_MODEL,
    "summary.md": DEFAULT_SUMMARY,
    "status_card.md": DEFAULT_STATUS_CARD,
    "style_guide.md": DEFAULT_STYLE_GUIDE,
    "style_fingerprint.md": DEFAULT_STYLE_FINGERPRINT,
    "style_review.md": DEFAULT_STYLE_REVIEW,
    "style_constraints_for_continuation.md": DEFAULT_STYLE_CONSTRAINTS_FOR_CONTINUATION,
    "error_archive.md": DEFAULT_ERROR_ARCHIVE,
    "domain_rules.md": DEFAULT_DOMAIN_RULES,
}
PLANNING_LAYOUT_DEFAULTS = {
    "brainstorm.md": DEFAULT_BRAINSTORM,
    "master_outline.md": DEFAULT_MASTER_OUTLINE,
    "arc_outline.md": DEFAULT_ARC_OUTLINE,
    "chapter_outline.md": DEFAULT_CHAPTER_OUTLINE,
}
VIRTUAL_LAYOUT_FILE_CONTENT = {
    name: ""
    for name in {
        **CORE_LAYOUT_DEFAULTS,
        **PLANNING_LAYOUT_DEFAULTS,
    }
}
VIRTUAL_LAYOUT_FILE_CONTENT["chapter_draft.md"] = DEFAULT_CHAPTER_DRAFT


def get_storage_root(base_dir: str | None = None) -> str:
    if base_dir:
        root_base = base_dir
    else:
        root_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.abspath(os.path.join(root_base, "storage"))


def validate_book_id(book_id: str) -> str:
    if not isinstance(book_id, str):
        raise ValueError("book_id must be a string")
    trimmed = book_id.strip()
    if not trimmed:
        raise ValueError("book_id is required")
    if trimmed in {".", ".."}:
        raise ValueError("book_id is invalid")
    if "/" in trimmed or "\\" in trimmed:
        raise ValueError("book_id cannot include path separators")
    if any(ch.isspace() for ch in trimmed):
        raise ValueError("book_id cannot include whitespace")
    if not BOOK_ID_PATTERN.fullmatch(trimmed):
        raise ValueError("book_id contains unsupported characters")
    return trimmed


def _normalize_book_name(book_name: str) -> str:
    return " ".join(str(book_name).strip().split()).lower()


def _safe_slug(value: str) -> str:
    slug = SAFE_SLUG_PATTERN.sub("_", value)
    slug = slug.strip("._-")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug[:55] if slug else ""


def generate_deterministic_id(book_name: str) -> str:
    normalized_name = _normalize_book_name(book_name)
    if not normalized_name:
        raise ValueError("book_name is required for deterministic id generation")

    slug_source = ""
    if lazy_pinyin is not None:
        try:
            slug_source = "".join(lazy_pinyin(normalized_name, errors="ignore")).strip()
        except Exception:
            slug_source = ""

    if not slug_source:
        slug_source = normalized_name

    slug = _safe_slug(slug_source)
    if not slug:
        slug = "book"

    short_hash = hashlib.md5(normalized_name.encode("utf-8")).hexdigest()[:8]
    deterministic_id = f"{slug}_{short_hash}"
    return validate_book_id(deterministic_id)


def smart_resolve_id(user_input: str, storage_root: str | None = None) -> str:
    """
    Resolve user-provided identifier with anti-"ID of ID" protection.

    Why:
    - Frontend may accidentally send an existing book_id through `book_name`.
    - If we always hash `book_name`, an existing id string would become a new id
      (nested hash), splitting data into a wrong directory.

    Strategy:
    1) direct-id hit: if input itself is a valid id and folder exists, use it.
    2) name-derived hit: derive deterministic id from input and reuse if exists.
    3) new-book fallback: return derived deterministic id for creation.
    """
    if not isinstance(user_input, str) or not user_input.strip():
        raise ValueError("book_name is required for deterministic id generation")

    normalized_input = user_input.strip()
    root = os.path.abspath(storage_root or get_storage_root())

    candidate_id = None
    try:
        candidate_id = validate_book_id(normalized_input)
    except ValueError:
        candidate_id = None

    if candidate_id:
        direct_dir = get_book_dir(candidate_id, root)
        if os.path.isdir(direct_dir):
            return candidate_id

    normalized_name = _normalize_book_name(normalized_input)
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        entries = []
    for entry in entries:
        if entry.endswith("_deleted") or entry.startswith("_trash_") or entry == "_pending_delete":
            continue
        try:
            existing_id = validate_book_id(entry)
        except ValueError:
            continue
        existing_dir = get_book_dir(existing_id, root)
        if not os.path.isdir(existing_dir):
            continue
        metadata_path = os.path.join(existing_dir, "metadata.json")
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        existing_name = metadata.get("book_name") if isinstance(metadata, dict) else None
        if isinstance(existing_name, str) and _normalize_book_name(existing_name) == normalized_name:
            return existing_id

    derived_id = generate_deterministic_id(normalized_input)
    derived_dir = get_book_dir(derived_id, root)
    if os.path.isdir(derived_dir):
        return derived_id

    return derived_id


def resolve_book_id(
    raw_book_id: str | None = None,
    raw_book_name: str | None = None,
    storage_root: str | None = None,
) -> str:
    if isinstance(raw_book_id, str) and raw_book_id.strip():
        return validate_book_id(raw_book_id)
    if isinstance(raw_book_name, str) and raw_book_name.strip():
        return smart_resolve_id(raw_book_name, storage_root)
    raise ValueError("book_id or book_name is required")


def resolve_book_locators(
    raw_book_id: str | None = None,
    raw_book_name: str | None = None,
    storage_root: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Resolve both locators independently for conflict detection.

    Returns:
    - validated_book_id: normalized id from `raw_book_id`, if provided.
    - resolved_book_name_id: resolved id from `raw_book_name`, if provided.
    """
    validated_book_id: str | None = None
    resolved_book_name_id: str | None = None
    if isinstance(raw_book_id, str) and raw_book_id.strip():
        validated_book_id = validate_book_id(raw_book_id)
    if isinstance(raw_book_name, str) and raw_book_name.strip():
        resolved_book_name_id = smart_resolve_id(raw_book_name, storage_root)
    return validated_book_id, resolved_book_name_id


def get_book_dir(book_id: str, storage_root: str | None = None) -> str:
    safe_book_id = validate_book_id(book_id)
    root = os.path.abspath(storage_root or get_storage_root())
    return os.path.abspath(os.path.join(root, safe_book_id))


def _ensure_path_inside_root(path: str, root: str) -> None:
    abs_path = os.path.abspath(path)
    abs_root = os.path.abspath(root)
    if os.path.commonpath([abs_path, abs_root]) != abs_root:
        raise ValueError("resolved book path escapes storage root")


def _ensure_file(path: str, default_content: str) -> None:
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(default_content)


def _metadata_path(book_dir: str) -> str:
    return os.path.join(book_dir, "metadata.json")


def get_book_paths(book_id: str, storage_root: str | None = None) -> Dict[str, str]:
    safe_book_id = validate_book_id(book_id)
    root = os.path.abspath(storage_root or get_storage_root())
    book_dir = get_book_dir(safe_book_id, root)
    _ensure_path_inside_root(book_dir, root)

    chapters_dir = os.path.join(book_dir, "chapters")
    return {
        "storage_root": root,
        "book_dir": book_dir,
        "chapters_dir": chapters_dir,
        "world_model_path": os.path.join(book_dir, "world_model.md"),
        "summary_path": os.path.join(book_dir, "summary.md"),
        "style_guide_path": os.path.join(book_dir, "style_guide.md"),
        "style_fingerprint_path": os.path.join(book_dir, "style_fingerprint.md"),
        "style_review_path": os.path.join(book_dir, "style_review.md"),
        "style_constraints_for_continuation_path": os.path.join(
            book_dir,
            "style_constraints_for_continuation.md",
        ),
        "status_card_path": os.path.join(book_dir, "status_card.md"),
        "error_archive_path": os.path.join(book_dir, "error_archive.md"),
        "domain_rules_path": os.path.join(book_dir, "domain_rules.md"),
        "brainstorm_path": os.path.join(book_dir, "brainstorm.md"),
        "master_outline_path": os.path.join(book_dir, "master_outline.md"),
        "arc_outline_path": os.path.join(book_dir, "arc_outline.md"),
        "chapter_outline_path": os.path.join(book_dir, "chapter_outline.md"),
        "metadata_path": _metadata_path(book_dir),
    }


def get_virtual_core_file_content(file_name: str) -> str | None:
    normalized = str(file_name).strip().replace("\\", "/")
    return VIRTUAL_LAYOUT_FILE_CONTENT.get(normalized)


def inspect_book_layout_integrity(book_id: str, storage_root: str | None = None) -> dict[str, Any]:
    paths = get_book_paths(book_id, storage_root)
    book_dir = paths["book_dir"]
    exists = os.path.isdir(book_dir)
    repo_exists = os.path.isdir(os.path.join(book_dir, ".git"))
    head_exists = False
    head_commit = None
    untracked_layout_files: list[str] = []
    if repo_exists:
        head_exists = has_valid_head(book_dir)
        head_commit = get_head_commit(book_dir)
        existing_layout_files = [name for name in TRACKED_LAYOUT_FILES if os.path.exists(os.path.join(book_dir, name))]
        if existing_layout_files:
            try:
                tracked_text = run_git(book_dir, ["ls-files", "--", *existing_layout_files]).stdout
                tracked = {line.strip() for line in tracked_text.splitlines() if line.strip()}
                untracked_layout_files = [name for name in existing_layout_files if name not in tracked]
            except subprocess.CalledProcessError:
                untracked_layout_files = list(existing_layout_files)

    missing_core_files = [name for name in CORE_LAYOUT_DEFAULTS if not os.path.exists(os.path.join(book_dir, name))]
    missing_directories: list[str] = []
    if exists and not os.path.isdir(paths["chapters_dir"]):
        missing_directories.append("chapters/")

    problem_codes: list[str] = []
    if not exists:
        problem_codes.append("BOOK_MISSING")
    if exists and not repo_exists:
        problem_codes.append("REPO_MISSING")
    if repo_exists and not head_exists:
        problem_codes.append("HEAD_MISSING")
    if missing_core_files:
        problem_codes.append("CORE_FILES_MISSING")
    if missing_directories:
        problem_codes.append("DIRECTORIES_MISSING")
    if untracked_layout_files:
        problem_codes.append("LAYOUT_UNTRACKED")

    return {
        "book_id": validate_book_id(book_id),
        "exists": exists,
        "repo_exists": repo_exists,
        "head_exists": head_exists,
        "head_commit": head_commit,
        "missing_core_files": missing_core_files,
        "missing_directories": missing_directories,
        "untracked_layout_files": untracked_layout_files,
        "problem_codes": problem_codes,
        "needs_repair": bool(problem_codes),
    }


def repair_book_layout(book_id: str, storage_root: str | None = None, book_name: str | None = None) -> dict[str, Any]:
    paths = get_book_paths(book_id, storage_root)
    os.makedirs(paths["book_dir"], exist_ok=True)

    with repo_lock(paths["book_dir"], "layout_repair.lock"):
        paths = ensure_book_layout(book_id, storage_root, book_name=book_name)
        repo_dir = paths["book_dir"]

        repair_commits: list[str] = []
        bootstrap_commit = ensure_initial_commit(repo_dir)
        if bootstrap_commit:
            repair_commits.append(bootstrap_commit)

        layout_commit = ensure_tracked_files(repo_dir, TRACKED_LAYOUT_FILES, DEFAULT_BOOTSTRAP_LAYOUT_MESSAGE)
        if layout_commit and layout_commit not in repair_commits:
            repair_commits.append(layout_commit)

        return {
            **paths,
            "head_commit": get_head_commit(repo_dir),
            "repair_commits": repair_commits,
            "integrity": inspect_book_layout_integrity(book_id, storage_root),
        }


def _read_raw_metadata(metadata_path: str) -> dict[str, Any] | None:
    if not os.path.exists(metadata_path):
        return None
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def get_book_metadata(book_id: str, storage_root: str | None = None) -> Dict[str, str]:
    safe_book_id = validate_book_id(book_id)
    root = os.path.abspath(storage_root or get_storage_root())
    book_dir = get_book_dir(safe_book_id, root)
    _ensure_path_inside_root(book_dir, root)

    metadata_path = _metadata_path(book_dir)
    default = {
        "book_id": safe_book_id,
        "book_name": safe_book_id,
        "updated_at": "",
    }

    data = _read_raw_metadata(metadata_path)
    if data is None:
        return {**default, "metadata_path": metadata_path}

    book_name = data.get("book_name", safe_book_id)
    if not isinstance(book_name, str) or not book_name.strip():
        book_name = safe_book_id

    updated_at = data.get("updated_at", "")
    if not isinstance(updated_at, str):
        updated_at = ""

    return {
        "book_id": safe_book_id,
        "book_name": book_name.strip(),
        "updated_at": updated_at,
        "metadata_path": metadata_path,
    }


def update_book_metadata(book_id: str, book_name: str, storage_root: str | None = None) -> Dict[str, str]:
    safe_book_id = validate_book_id(book_id)
    root = os.path.abspath(storage_root or get_storage_root())
    book_dir = get_book_dir(safe_book_id, root)
    _ensure_path_inside_root(book_dir, root)
    os.makedirs(book_dir, exist_ok=True)

    normalized_name = safe_book_id
    if isinstance(book_name, str) and book_name.strip():
        normalized_name = book_name.strip()

    metadata_path = _metadata_path(book_dir)
    existing = _read_raw_metadata(metadata_path)
    existing_book_id = existing.get("book_id") if isinstance(existing, dict) else None
    existing_book_name = existing.get("book_name") if isinstance(existing, dict) else None
    existing_updated_at = existing.get("updated_at") if isinstance(existing, dict) else ""
    if not isinstance(existing_book_id, str):
        existing_book_id = None
    if not isinstance(existing_book_name, str):
        existing_book_name = None
    if not isinstance(existing_updated_at, str):
        existing_updated_at = ""

    has_structural_change = (
        existing is None
        or existing_book_id != safe_book_id
        or (existing_book_name or "").strip() != normalized_name
    )
    if not has_structural_change:
        return {
            "book_id": safe_book_id,
            "book_name": normalized_name,
            "updated_at": existing_updated_at,
            "metadata_path": metadata_path,
        }

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    metadata = {
        "book_id": safe_book_id,
        "book_name": normalized_name,
        "updated_at": now,
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if os.path.isdir(os.path.join(book_dir, ".git")):
        try:
            run_git(book_dir, ["add", "--", "metadata.json"])
            status_output = run_git(book_dir, ["status", "--porcelain", "--", "metadata.json"]).stdout
            if not status_output.strip():
                return {**metadata, "metadata_path": metadata_path}
            try:
                run_git(book_dir, ["commit", "-m", "chore: update book metadata", "--", "metadata.json"])
            except subprocess.CalledProcessError as exc:
                if not is_nothing_to_commit_error(exc):
                    raise
        except Exception as exc:
            raise RuntimeError(
                f"failed to archive metadata in git for {book_dir}. {format_git_error(exc)}"
            ) from exc

    return {**metadata, "metadata_path": metadata_path}


def ensure_book_git_repo(book_dir: str) -> None:
    os.makedirs(book_dir, exist_ok=True)

    try:
        ensure_repo(book_dir)
    except Exception as exc:
        raise RuntimeError(
            f"book git repository is unavailable or corrupted at {book_dir}. {format_git_error(exc)}"
        ) from exc

    gitignore_path = os.path.join(book_dir, ".gitignore")
    required_entries = [line.strip() for line in BOOK_GITIGNORE.splitlines() if line.strip()]
    existing_entries: list[str] = []
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            existing_entries = [line.strip() for line in f.read().splitlines() if line.strip()]

    merged_entries = list(existing_entries)
    for entry in required_entries:
        if entry not in merged_entries:
            merged_entries.append(entry)

    with open(gitignore_path, "w", encoding="utf-8") as f:
        f.write("\n".join(merged_entries).strip() + "\n")


def ensure_book_layout(book_id: str, storage_root: str | None = None, book_name: str | None = None) -> Dict[str, str]:
    paths = get_book_paths(book_id, storage_root)
    root = paths["storage_root"]
    os.makedirs(root, exist_ok=True)
    os.makedirs(paths["book_dir"], exist_ok=True)
    os.makedirs(paths["chapters_dir"], exist_ok=True)

    for file_name, default_content in {**CORE_LAYOUT_DEFAULTS, **PLANNING_LAYOUT_DEFAULTS}.items():
        _ensure_file(os.path.join(paths["book_dir"], file_name), default_content)
    ensure_book_git_repo(paths["book_dir"])

    if isinstance(book_name, str) and book_name.strip():
        update_book_metadata(book_id, book_name, root)

    return paths


def get_next_chapter_index(book_id: str, storage_root: str | None = None) -> int:
    paths = ensure_book_layout(book_id, storage_root)
    chapters_dir = paths["chapters_dir"]

    max_index = 0
    for name in os.listdir(chapters_dir):
        if not name.lower().endswith(".md"):
            continue
        match = CHAPTER_FILE_INDEX_PATTERN.match(name)
        if not match:
            continue
        try:
            current = int(match.group(1))
        except ValueError:
            continue
        if current > max_index:
            max_index = current

    return max_index + 1 if max_index > 0 else 1
