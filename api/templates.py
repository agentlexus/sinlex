"""Load HTML templates from api/templates/."""
from pathlib import Path

_DIR = Path(__file__).parent / "templates"


def render_template(name: str, **replacements: str) -> str:
    text = (_DIR / name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(f"%%{key}%%", value)
    return text
