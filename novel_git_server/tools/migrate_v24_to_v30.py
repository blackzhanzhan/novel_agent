import argparse
import datetime
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.book_storage import ensure_book_layout, validate_book_id


def _move_file(src: Path, dst: Path, dry_run: bool) -> None:
    if not src.exists() or not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"DRY-RUN move file: {src} -> {dst}")
        return
    if dst.exists():
        dst.unlink()
    shutil.move(str(src), str(dst))


def _merge_move_dir(src: Path, dst: Path, dry_run: bool) -> None:
    if not src.exists() or not src.is_dir():
        return
    if dry_run:
        print(f"DRY-RUN merge dir: {src} -> {dst}")
    else:
        dst.mkdir(parents=True, exist_ok=True)

    for entry in src.iterdir():
        target = dst / entry.name
        if entry.is_dir():
            _merge_move_dir(entry, target, dry_run)
        else:
            if dry_run:
                print(f"DRY-RUN move file: {entry} -> {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target.unlink()
                shutil.move(str(entry), str(target))

    if not dry_run:
        try:
            src.rmdir()
        except OSError:
            pass


def migrate_storage(storage_root: Path, book_id: str, dry_run: bool = False) -> dict:
    safe_book_id = validate_book_id(book_id)
    storage_root = storage_root.resolve()

    paths = ensure_book_layout(safe_book_id, str(storage_root))
    book_dir = Path(paths["book_dir"])

    legacy_world_model = storage_root / "world_model.md"
    legacy_summary = storage_root / "summary.md"
    legacy_outlines = storage_root / "outlines"
    legacy_chapters = storage_root / "chapters"
    legacy_db = storage_root / "database.json"

    _move_file(legacy_world_model, Path(paths["world_model_path"]), dry_run)
    _move_file(legacy_summary, Path(paths["summary_path"]), dry_run)
    _merge_move_dir(legacy_chapters, Path(paths["chapters_dir"]), dry_run)

    archive_dir: Path | None = None

    def _ensure_archive_dir() -> Path:
        nonlocal archive_dir
        if archive_dir is None:
            archive_dir = storage_root / "_legacy_archive" / datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
            archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir

    outlines_archive = None
    if legacy_outlines.exists() and legacy_outlines.is_dir():
        outlines_archive = _ensure_archive_dir() / "outlines"
        _merge_move_dir(legacy_outlines, outlines_archive, dry_run)

    database_archive = None
    if legacy_db.exists() and legacy_db.is_file():
        database_archive = _ensure_archive_dir() / "database.json"
        _move_file(legacy_db, database_archive, dry_run)

    return {
        "storage_root": str(storage_root),
        "book_id": safe_book_id,
        "book_dir": str(book_dir),
        "database_archive": str(database_archive) if database_archive else None,
        "outlines_archive": str(outlines_archive) if outlines_archive else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate v2.4 storage layout into v3.0 book-scoped layout.")
    parser.add_argument("--book-id", required=True, help="target book id for migrated data")
    parser.add_argument("--storage-root", default=None, help="storage root path (defaults to ../storage)")
    parser.add_argument("--dry-run", action="store_true", help="show actions without moving files")
    args = parser.parse_args()

    storage_root = Path(args.storage_root) if args.storage_root else (PROJECT_ROOT / "storage")

    result = migrate_storage(storage_root, args.book_id, args.dry_run)
    print(result)


if __name__ == "__main__":
    main()
