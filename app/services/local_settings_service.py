from pathlib import Path
import json

SETTINGS_PATH = Path(".webcrawler_local_settings.json")


def load_local_settings(path: Path = SETTINGS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_local_settings(settings: dict, path: Path = SETTINGS_PATH) -> None:
    try:
        path.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def clear_local_settings(path: Path = SETTINGS_PATH) -> None:
    try:
        path.unlink(missing_ok=True)
    except TypeError:
        if path.exists():
            path.unlink()


def merge_with_defaults(settings: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update({k: v for k, v in settings.items() if k in defaults})
    return merged
