"""Station settings, preconfigured for this station and stored as JSON.

Location: $XDG_CONFIG_HOME/kx3-rig/settings.json (usually ~/.config/kx3-rig/).
Unknown keys in the file are ignored and missing keys take the defaults, so the
file can be edited by hand and survives upgrades.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields

LICENSE_CLASSES = ("Technician", "General", "Extra")


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "kx3-rig")


def data_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "kx3-rig")


@dataclass
class Settings:
    callsign: str = "K1ABC"
    grid: str = "FN42hn"
    license_class: str = "General"
    # Transmit power the app sets when you start transmitting, in watts.
    power_w: float = 5.0
    # Hard ceiling for any power the app will request (AlexLoop digital limit).
    max_power_w: float = 10.0
    # Speaker volume for listening to the radio, 0..1.
    listen_volume: float = 0.6
    # Microphone gain applied before the Digirig for voice transmit, 0..2.
    voice_gain: float = 1.0
    # Digital transmit audio level into the Digirig, 0..1.
    data_tx_level: float = 0.5
    # FT8 audio offset for our transmissions, Hz.
    ft8_tx_offset_hz: int = 1500
    # Serial port override; empty means auto-detect the Digirig.
    serial_port: str = ""
    # Show the radio's audio on this computer's speakers.
    listen: bool = True

    @property
    def grid4(self) -> str:
        """The 4-character grid used in FT8 messages."""
        return self.grid[:4].upper()

    def clamp(self) -> None:
        if self.license_class not in LICENSE_CLASSES:
            self.license_class = "General"
        self.callsign = self.callsign.strip().upper()
        self.grid = self.grid.strip()
        self.max_power_w = min(max(self.max_power_w, 0.1), 15.0)
        self.power_w = min(max(self.power_w, 0.1), self.max_power_w)
        self.listen_volume = min(max(self.listen_volume, 0.0), 1.0)
        self.voice_gain = min(max(self.voice_gain, 0.0), 2.0)
        self.data_tx_level = min(max(self.data_tx_level, 0.0), 1.0)
        self.ft8_tx_offset_hz = int(min(max(self.ft8_tx_offset_hz, 200), 3000))


def from_dict(raw: dict) -> Settings:
    known = {f.name for f in fields(Settings)}
    s = Settings(**{k: v for k, v in raw.items() if k in known})
    s.clamp()
    return s


def load(path: str | None = None) -> Settings:
    path = path or os.path.join(config_dir(), "settings.json")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("settings file is not a JSON object")
        return from_dict(raw)
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError, TypeError):
        # A corrupt file should never stop the app from starting.
        return Settings()


def save(settings: Settings, path: str | None = None) -> None:
    path = path or os.path.join(config_dir(), "settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
