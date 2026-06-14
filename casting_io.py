"""Файлы meta.json / costing.json / analysis.json в каталоге литьевого проекта."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from project_store import _safe_dir_name, projects_base_dir


def _project_dir(project_name: str, user_folder: str) -> str:
    safe = _safe_dir_name(project_name)
    return os.path.join(projects_base_dir(user_folder, storage="casting"), safe)


def data_casting_path(project_name: str, user_folder: str) -> str:
    """Путь к data_casting.json: casting/<user>/<project>/data_casting.json."""
    return os.path.join(_project_dir(project_name, user_folder), "data_casting.json")


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_casting_artifacts(
    project_name: str,
    user_folder: str,
    *,
    meta: Dict[str, Any],
    analysis: Dict[str, Any] | None = None,
    costing: Dict[str, Any] | None = None,
) -> None:
    pdir = _project_dir(project_name, user_folder)
    os.makedirs(pdir, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    meta_out = {"name": project_name, "updated_at": now, **(meta or {})}
    _write_json(os.path.join(pdir, "meta.json"), meta_out)
    if analysis is not None:
        _write_json(
            os.path.join(pdir, "analysis.json"),
            {"saved_at": now, **analysis},
        )
    if costing is not None:
        _write_json(
            os.path.join(pdir, "costing.json"),
            {"saved_at": now, **costing},
        )
