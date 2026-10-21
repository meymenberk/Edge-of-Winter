"""Crash-safe offline save file: validated loading, atomic writes and backups.

``savegame.json`` holds one offline world's progress.  Saving never destroys an
earlier save: the previous file is kept as ``savegame.json.bak``, a save that
belongs to a different world seed is archived as ``savegame.seed-<seed>.json``
before it is replaced, and an unreadable file is renamed aside instead of being
overwritten.  Loading never raises; a missing or broken save starts a new game.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from .paths import PROJECT_ROOT

SAVE_VERSION = 1
SAVE_FILE = PROJECT_ROOT / "savegame.json"


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def seed_archive_path(path: Path, seed: int) -> Path:
    return path.with_name(f"{path.stem}.seed-{int(seed)}{path.suffix}")


def save_seed(data) -> int | None:
    try:
        return int(data.get("world_seed"))
    except (AttributeError, TypeError, ValueError):
        return None


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("save root is not an object")
    version = int(data.get("version", 0))
    if not 1 <= version <= SAVE_VERSION:
        raise ValueError(f"unsupported save version {version}")
    return data


def _quarantine(path: Path, reason) -> None:
    """Move an unreadable save aside so a later write cannot destroy it."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.stem}.corrupt-{stamp}{path.suffix}")
    counter = 1
    while target.exists():
        counter += 1
        target = path.with_name(f"{path.stem}.corrupt-{stamp}-{counter}{path.suffix}")
    try:
        os.replace(path, target)
        print(f"[SAVE] {path.name} is unreadable ({reason}); kept it as {target.name}.")
    except OSError as exc:
        print(f"[SAVE] {path.name} is unreadable ({reason}) and could not be moved aside: {exc}")


def _read_or_quarantine(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return _read(path)
    except (OSError, ValueError, TypeError, UnicodeDecodeError) as exc:
        _quarantine(path, exc)
        return None


def load_save(world_seed=None, path: Path = SAVE_FILE) -> dict:
    """Return the save for ``world_seed`` (any world when None), or ``{}``."""
    path = Path(path)
    candidates = [path, backup_path(path)]
    if world_seed is not None:
        candidates.append(seed_archive_path(path, world_seed))
    for candidate in candidates:
        data = _read_or_quarantine(candidate)
        if data is None:
            continue
        if world_seed is not None and save_seed(data) not in (None, int(world_seed)):
            continue
        if candidate != path:
            print(f"[SAVE] Loaded progress from {candidate.name}.")
        return data
    return {}


def write_save(data: dict, path: Path = SAVE_FILE) -> None:
    """Atomically replace the save, keeping the previous one recoverable."""
    path = Path(path)
    payload = dict(data)
    payload["version"] = SAVE_VERSION
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)

    previous = _read_or_quarantine(path)
    if previous is not None:
        previous_seed = save_seed(previous)
        if previous_seed is not None and previous_seed != save_seed(payload):
            shutil.copy2(path, seed_archive_path(path, previous_seed))
        else:
            shutil.copy2(path, backup_path(path))

    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
