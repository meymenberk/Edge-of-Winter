"""Persistent, validated launch settings and stable world-seed conversion."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from .localization import tr
from .paths import PROJECT_ROOT

SETTINGS_FILE = PROJECT_ROOT / "settings.json"
MAX_SEED = 2 ** 31 - 1
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def stable_seed(value) -> int:
    """Map integer or text input to a process-independent positive seed."""
    text = str(value).strip()
    if not text:
        raise ValueError(tr("error.seed_empty"))
    try:
        return int(text, 10) % MAX_SEED
    except ValueError:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % MAX_SEED


def random_seed_text() -> str:
    return str(secrets.randbelow(MAX_SEED))


def validate_endpoint(host: str, port) -> tuple[str, int]:
    host = str(host).strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or any(ch.isspace() for ch in host):
        raise ValueError(tr("error.address_invalid"))
    try:
        ipaddress.ip_address(host)
    except ValueError:
        labels = host[:-1].split(".") if host.endswith(".") else host.split(".")
        # All-numeric dotted text (e.g. 300.1.1.1) is a malformed IPv4 address.
        if (len(host) > 253 or all(label.isdigit() for label in labels)
                or not all(_HOST_LABEL.fullmatch(label) for label in labels)):
            raise ValueError(tr("error.address_invalid"))
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError(tr("error.port_number")) from exc
    if not 1 <= port <= 65535:
        raise ValueError(tr("error.port_range"))
    return host, port


DISPLAY_MODES = ("windowed", "fullscreen")


@dataclass
class GameSettings:
    world_seed: str = "42"
    server_address: str = "127.0.0.1"
    server_port: int = 5555
    display_mode: str = "windowed"
    window_width: int = 1200
    window_height: int = 780
    pixel_perfect: bool = False
    music_volume: int = 70

    def validated(self) -> "GameSettings":
        stable_seed(self.world_seed)
        host, port = validate_endpoint(self.server_address, self.server_port)
        mode = self.display_mode if self.display_mode in DISPLAY_MODES else "windowed"
        # Presentation values are clamped rather than rejected so an edited or
        # older settings file can never stop the game from opening a window.
        width = max(640, min(7680, int(self.window_width)))
        height = max(360, min(4320, int(self.window_height)))
        volume = max(0, min(100, int(self.music_volume)))
        return GameSettings(str(self.world_seed).strip(), host, port, mode, width, height,
                            bool(self.pixel_perfect), volume)


def load_settings(path: Path = SETTINGS_FILE) -> GameSettings:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return GameSettings()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return GameSettings()
    defaults = GameSettings()
    try:
        return GameSettings(*(data.get(name, getattr(defaults, name))
                              for name in GameSettings.__dataclass_fields__)).validated()
    except (ValueError, TypeError, AttributeError):
        pass
    # One invalid value (e.g. a hand-edited port) must not also reset the world
    # seed and the rest of the file: keep every field that validates on its own.
    settings = defaults
    for name in GameSettings.__dataclass_fields__:
        if name not in data:
            continue
        candidate = replace(settings, **{name: data[name]})
        try:
            candidate.validated()
        except (ValueError, TypeError, AttributeError):
            continue
        settings = candidate
    return settings.validated()


def save_settings(settings: GameSettings, path: Path = SETTINGS_FILE) -> None:
    settings = settings.validated()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(asdict(settings), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
