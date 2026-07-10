"""Тесты пропуска лишнего save при открытии проекта."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "page_modules"))
from upload_step import project_registry_unchanged


def test_registry_unchanged_when_inputs_match():
    baseline = {
        "material": "Сталь 45",
        "workpiece_type": "Пруток",
        "diam": 85,
        "length": 320,
        "width": 0,
        "height": 0,
        "cost_per_hour": 3500,
        "batch_size": 10,
        "cam_rate": 0,
    }
    save_params = {
        "material": "Сталь 45",
        "workpiece_type": "Пруток",
        "diam": 85,
        "length": 320,
        "width": 0,
        "height": 0,
        "cost_per_hour": 3500,
        "batch_size": 10,
        "cam_rate": 0,
        "cost_per_unit": 9999,
        "total_cost": 99999,
    }
    assert project_registry_unchanged(baseline, save_params) is True


def test_registry_changed_when_batch_differs():
    baseline = {
        "material": "Сталь 45",
        "workpiece_type": "Пруток",
        "diam": 85,
        "length": 320,
        "width": 0,
        "height": 0,
        "cost_per_hour": 3500,
        "batch_size": 10,
        "cam_rate": 0,
    }
    save_params = {
        "material": "Сталь 45",
        "workpiece_type": "Пруток",
        "diam": 85,
        "length": 320,
        "width": 0,
        "height": 0,
        "cost_per_hour": 3500,
        "batch_size": 20,
        "cam_rate": 0,
    }
    assert project_registry_unchanged(baseline, save_params) is False


def test_registry_no_baseline_always_saves():
    assert project_registry_unchanged(None, {"batch_size": 1}) is False


def test_registry_implied_batch_single_unit():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "page_modules"))
    from upload_step import registry_implied_batch, resolve_open_batch_size

    proj = {"cost_per_unit": 23243, "total_cost": 23243}
    assert registry_implied_batch(proj) == 1
    assert resolve_open_batch_size(proj, {"batch_size": 12}) == 1


def test_registry_implied_batch_party_of_twelve():
    from upload_step import registry_implied_batch
    proj = {"cost_per_unit": 5891, "total_cost": 70692}
    assert registry_implied_batch(proj) == 12
