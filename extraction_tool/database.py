"""SQLite-хранилище метрик деталей."""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import config

PARTS_COLUMNS = [
    ("file_path", "TEXT NOT NULL"),
    ("file_name", "TEXT"),
    ("part_name", "TEXT"),
    ("timestamp", "TEXT NOT NULL"),
    ("status", "TEXT"),
    ("error_message", "TEXT"),
    # Геометрия
    ("volume_mm3", "REAL"),
    ("surface_area_mm2", "REAL"),
    ("bbox_x_mm", "REAL"),
    ("bbox_y_mm", "REAL"),
    ("bbox_z_mm", "REAL"),
    ("center_x", "REAL"),
    ("center_y", "REAL"),
    ("center_z", "REAL"),
    ("inertia_ij", "TEXT"),
    ("principal_axes", "TEXT"),
    ("face_count", "INTEGER"),
    ("edge_count", "INTEGER"),
    ("vertex_count", "INTEGER"),
    ("solid_count", "INTEGER"),
    ("min_wall_thickness_mm", "REAL"),
    ("min_wall_thickness_note", "TEXT"),
    ("has_internal_void", "INTEGER"),
    ("void_volume_mm3", "REAL"),
    ("proj_area_xy_mm2", "REAL"),
    ("proj_area_xz_mm2", "REAL"),
    ("proj_area_yz_mm2", "REAL"),
    ("max_height_x_mm", "REAL"),
    ("max_height_y_mm", "REAL"),
    ("max_height_z_mm", "REAL"),
    ("curvature_note", "TEXT"),
    # CAD-метаданные
    ("cad_color", "TEXT"),
    ("cad_layer", "TEXT"),
    ("cad_material", "TEXT"),
    # Сложность
    ("surface_to_volume_ratio", "REAL"),
    ("detail_index", "REAL"),
    ("elongation_index", "REAL"),
    ("small_face_count", "INTEGER"),
    ("sharp_edge_count", "INTEGER"),
    ("cyl_face_count", "INTEGER"),
    ("plane_face_count", "INTEGER"),
    ("operation_type_hint", "TEXT"),
    ("part_type_hint", "TEXT"),
    ("complexity_hint", "TEXT"),
    # Цена и заметки
    ("price_primitive", "REAL"),
    ("notes", "TEXT"),
    ("raw_json", "TEXT"),
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создать таблицы, если их нет."""
    cols_sql = ",\n  ".join(f"{name} {typ}" for name, typ in PARTS_COLUMNS)
    with _connect() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS parts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              {cols_sql}
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faces (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              part_id INTEGER NOT NULL,
              face_index INTEGER,
              area_mm2 REAL,
              surface_type TEXT,
              FOREIGN KEY(part_id) REFERENCES parts(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS edges (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              part_id INTEGER NOT NULL,
              edge_index INTEGER,
              length_mm REAL,
              is_sharp INTEGER,
              FOREIGN KEY(part_id) REFERENCES parts(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_parts_path ON parts(file_path)")
        conn.commit()


def insert_part(metrics: Dict[str, Any]) -> int:
    """Вставить строку в parts, вернуть id."""
    init_db()
    row = {name: metrics.get(name) for name, _ in PARTS_COLUMNS}
    row["timestamp"] = row.get("timestamp") or datetime.now(timezone.utc).isoformat()
    if isinstance(row.get("raw_json"), dict):
        row["raw_json"] = json.dumps(row["raw_json"], ensure_ascii=False)
    for key in ("inertia_ij", "principal_axes", "cad_color"):
        if isinstance(row.get(key), (dict, list)):
            row[key] = json.dumps(row[key], ensure_ascii=False)

    cols = [name for name, _ in PARTS_COLUMNS if name in row]
    placeholders = ", ".join("?" for _ in cols)
    values = [row[c] for c in cols]

    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO parts ({', '.join(cols)}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
        return int(cur.lastrowid)


def insert_faces(part_id: int, faces: List[Dict[str, Any]]) -> None:
    if not faces:
        return
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO faces (part_id, face_index, area_mm2, surface_type) VALUES (?, ?, ?, ?)",
            [(part_id, f["face_index"], f.get("area_mm2"), f.get("surface_type")) for f in faces],
        )
        conn.commit()


def insert_edges(part_id: int, edges: List[Dict[str, Any]]) -> None:
    if not edges:
        return
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO edges (part_id, edge_index, length_mm, is_sharp) VALUES (?, ?, ?, ?)",
            [(part_id, e["edge_index"], e.get("length_mm"), e.get("is_sharp", 0)) for e in edges],
        )
        conn.commit()
