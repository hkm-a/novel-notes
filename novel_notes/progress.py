"""进度记录，支持中断后续跑。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def progress_path(output_dir: Path) -> Path:
    return output_dir / ".progress.json"


def load_progress(output_dir: Path) -> Dict[str, Any]:
    path = progress_path(output_dir)
    if not path.exists():
        return {"version": 1, "chapters": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "chapters": {}}
        data.setdefault("version", 1)
        data.setdefault("chapters", {})
        return data
    except Exception:
        # 进度文件损坏时不应阻断运行，但保留备份避免误删。
        try:
            backup = path.with_suffix(".json.bak")
            path.replace(backup)
        except Exception:
            pass
        return {"version": 1, "chapters": {}}


def save_progress(output_dir: Path, progress: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp = progress_path(output_dir).with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(progress_path(output_dir))


def is_done(progress: Dict[str, Any], index: int) -> bool:
    record = progress.get("chapters", {}).get(str(index))
    return bool(record and record.get("status") == "done")


def mark_done(
    progress: Dict[str, Any],
    index: int,
    file: str,
    title: str,
) -> None:
    progress.setdefault("chapters", {})[str(index)] = {
        "index": index,
        "title": title,
        "file": file,
        "status": "done",
        "error": None,
        "updated_at": _now_iso(),
    }


def mark_error(
    progress: Dict[str, Any],
    index: int,
    file: str,
    title: str,
    error: str,
) -> None:
    progress.setdefault("chapters", {})[str(index)] = {
        "index": index,
        "title": title,
        "file": file,
        "status": "error",
        "error": error,
        "updated_at": _now_iso(),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
