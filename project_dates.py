"""Даты проектов: ISO в JSON, «Сегодня»/«Вчера»/дд.мм.гггг в UI."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

_LEGACY_DATE_LABELS = frozenset({"сегодня", "вчера", "today", "yesterday"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id(name: str) -> str:
    return name.replace(" ", "_").replace("/", "_")


def project_dir_mtime_iso(user_dir: str, project_name: str) -> str:
    """Оценка даты создания по mtime каталога или STEP."""
    pid = _project_id(project_name)
    candidates = [
        os.path.join(user_dir, pid, f"{pid}.stp"),
        os.path.join(user_dir, pid, f"{pid}.step"),
        os.path.join(user_dir, pid),
        os.path.join(user_dir, f"{pid}.stp"),
    ]
    best_ts = 0.0
    for path in candidates:
        if os.path.isfile(path):
            best_ts = max(best_ts, os.path.getmtime(path))
        elif os.path.isdir(path):
            best_ts = max(best_ts, os.path.getmtime(path))
    if best_ts <= 0:
        return utc_now_iso()
    return datetime.fromtimestamp(best_ts, tz=timezone.utc).isoformat()


def parse_project_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    low = s.lower()
    if low in _LEGACY_DATE_LABELS:
        return None
    if low == "сегодня":
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def to_local_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


def format_project_date_label(
    value: Any,
    *,
    view_date: Optional[date] = None,
) -> str:
    """Сегодня / Вчера / дд.мм.гггг относительно даты просмотра."""
    view = view_date or date.today()
    dt = parse_project_datetime(value)
    if dt is None:
        return "—"
    d = to_local_date(dt)
    if d == view:
        return "Сегодня"
    if d == view - timedelta(days=1):
        return "Вчера"
    return d.strftime("%d.%m.%Y")



_PROJECT_COMPARE_KEYS = (
    "name",
    "material",
    "volume",
    "workpiece_type",
    "diam",
    "length",
    "width",
    "height",
    "cost_per_hour",
    "cost_per_unit",
    "total_cost",
    "machining_hours",
)


def _project_field_norm(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in ("volume", "diam", "length", "width", "height", "cost_per_hour"):
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return value
    if key in ("cost_per_unit", "total_cost"):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if key == "machining_hours":
        return str(value).strip()
    return value


def project_fields_changed(
    existing: Optional[Dict[str, Any]],
    fields: Dict[str, Any],
    *,
    step_changed: bool = False,
) -> bool:
    if step_changed:
        return True
    if not existing:
        return True
    for key in _PROJECT_COMPARE_KEYS:
        if _project_field_norm(key, existing.get(key)) != _project_field_norm(
            key, fields.get(key)
        ):
            return True
    return False


def project_activity_datetime(project: Optional[Dict[str, Any]]) -> Optional[datetime]:
    """Момент последней активности: updated_at, иначе created_at."""
    p = project or {}
    return parse_project_datetime(p.get("updated_at")) or parse_project_datetime(
        p.get("created_at")
    )


def project_activity_iso(project: Optional[Dict[str, Any]]) -> Any:
    """ISO-метка для колонки «Дата» и сортировки."""
    p = project or {}
    return p.get("updated_at") or p.get("created_at") or p.get("date")


def sort_projects_by_created(projects: list) -> list:
    """Активные проекты сверху (updated_at, с точностью до минуты)."""

    def _sort_key(p: Dict[str, Any]) -> datetime:
        dt = project_activity_datetime(p)
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return dt

    return sorted(
        [p for p in (projects or []) if isinstance(p, dict)],
        key=_sort_key,
        reverse=True,
    )


def sync_project_registry(
    user_dir: str,
    project_name: str,
    updates: Dict[str, Any],
    *,
    step_changed: bool = False,
) -> bool:
    """Обновить projects.json при изменении параметров проекта (UI / data.txt)."""
    if not user_dir or not project_name:
        return False
    projects_file = os.path.join(user_dir, "projects.json")
    if not os.path.isfile(projects_file):
        return False
    with open(projects_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    projects = data.get("projects") or []
    idx = next(
        (i for i, p in enumerate(projects) if p.get("name") == project_name),
        None,
    )
    if idx is None:
        return False
    existing = projects[idx]
    fields = {"name": project_name}
    for key in _PROJECT_COMPARE_KEYS:
        if key == "name":
            continue
        if key in updates:
            fields[key] = updates[key]
        else:
            fields[key] = existing.get(key)
    record, changed = build_project_record(
        fields,
        existing=existing,
        user_dir=user_dir,
        is_new=False,
        step_changed=step_changed,
    )
    if not changed:
        return False
    projects[idx] = record
    data["projects"] = sort_projects_by_created(projects)
    with open(projects_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True

def build_project_record(
    fields: Dict[str, Any],
    *,
    existing: Optional[Dict[str, Any]] = None,
    user_dir: str = "",
    is_new: bool = False,
    step_changed: bool = False,
) -> Tuple[Dict[str, Any], bool]:
    prev = existing or {}
    if prev and not is_new and not project_fields_changed(
        prev, fields, step_changed=step_changed
    ):
        return dict(prev), False

    now = utc_now_iso()
    rec = dict(fields)
    created = prev.get("created_at")
    if not parse_project_datetime(created):
        if user_dir and not is_new:
            created = project_dir_mtime_iso(user_dir, rec.get("name", ""))
        else:
            created = now

    rec["created_at"] = created
    rec["updated_at"] = now
    rec.pop("date", None)
    return rec, True


def migrate_project_entry(
    project: Dict[str, Any],
    user_dir: str,
) -> Tuple[Dict[str, Any], bool]:
    changed = False
    p = dict(project)
    name = p.get("name") or ""

    created = p.get("created_at")
    legacy_date = (p.get("date") or "").strip()
    if legacy_date.lower() in _LEGACY_DATE_LABELS or legacy_date == "Сегодня":
        if user_dir and name:
            p["created_at"] = project_dir_mtime_iso(user_dir, name)
        else:
            p["created_at"] = utc_now_iso()
        changed = True
    elif not parse_project_datetime(created):
        if user_dir and name:
            p["created_at"] = project_dir_mtime_iso(user_dir, name)
        else:
            p["created_at"] = utc_now_iso()
        changed = True

    if not parse_project_datetime(p.get("updated_at")):
        p["updated_at"] = p.get("created_at") or utc_now_iso()
        changed = True

    if "date" in p:
        del p["date"]
        changed = True

    return p, changed


def migrate_projects_data(
    data: Dict[str, Any],
    user_dir: str,
) -> Tuple[Dict[str, Any], bool]:
    changed = False
    projects = []
    for raw in data.get("projects") or []:
        if not isinstance(raw, dict):
            continue
        p, ch = migrate_project_entry(raw, user_dir)
        projects.append(p)
        changed = changed or ch
    data = dict(data)
    data["projects"] = sort_projects_by_created(projects)
    return data, changed


def migrate_projects_file(projects_file: str, user_dir: str) -> bool:
    if not os.path.isfile(projects_file):
        return False
    with open(projects_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data, changed = migrate_projects_data(data, user_dir)
    if changed:
        with open(projects_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return changed
