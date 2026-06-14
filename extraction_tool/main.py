#!/usr/bin/env python3
"""
Пакетная обработка STEP → SQLite.

  python -m extraction_tool.main
  python -m extraction_tool.main /path/to/step/folder
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Корень проекта в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction_tool import config
from extraction_tool.database import init_db, insert_edges, insert_faces, insert_part
from extraction_tool.extractor import extract_step_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("extraction_tool")

STEP_EXT = (".stp", ".step", ".STP", ".STEP")


def iter_step_files(root: str):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(STEP_EXT):
                yield os.path.join(dirpath, fn)


def process_file(path: str) -> bool:
    log.info("Обработка: %s", path)
    metrics = extract_step_path(path, save_faces_edges=True)
    part_id = insert_part(metrics)
    if metrics.get("status") == "ok" and config.ENABLE_FACE_EDGE_TABLES:
        insert_faces(part_id, metrics.get("_faces", []))
        insert_edges(part_id, metrics.get("_edges", []))
        log.info(
            "  OK vol=%.1f мм³ SA/V=%.3f price_prim=%.0f ₽ id=%s",
            metrics.get("volume_mm3", 0),
            metrics.get("surface_to_volume_ratio", 0),
            metrics.get("price_primitive", 0),
            part_id,
        )
        return True
    log.warning("  ОШИБКА: %s", metrics.get("error_message"))
    return False


def main():
    parser = argparse.ArgumentParser(description="Sinlex STEP extraction → SQLite")
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=config.STEP_INPUT_DIR,
        help="Папка с STEP (рекурсивно)",
    )
    parser.add_argument(
        "--db",
        default=config.DB_PATH,
        help="Путь к SQLite",
    )
    args = parser.parse_args()
    config.DB_PATH = args.db
    init_db()
    log.info("БД: %s", config.DB_PATH)
    log.info("Вход: %s", args.input_dir)

    if not os.path.isdir(args.input_dir):
        log.error("Папка не найдена: %s", args.input_dir)
        sys.exit(1)

    ok, fail = 0, 0
    for path in iter_step_files(args.input_dir):
        try:
            if process_file(path):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            log.exception("Сбой %s: %s", path, e)
            fail += 1

    log.info("Готово: успешно %d, ошибок %d", ok, fail)


if __name__ == "__main__":
    main()
