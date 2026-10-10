"""FT8 transmit audio.

Message packing comes from WSJT-X's own `ft8code` (installed with WSJT-X), so
what we send is encoded exactly as WSJT-X would. The audio synthesis is a port
of WSJT-X lib/ft8/gen_ft8wave.f90 (continuous-phase GFSK, BT = 2.0, 6.25 baud,
6.25 Hz tone spacing, 20 ms raised-cosine ramps, 12.64 s), validated by
round-tripping through `jt9` and sample-for-sample against `ft8sim`.
"""

from __future__ import annotations

import functools
import math
import re
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np

FT8CODE = "ft8code"
NSYM = 79
NSPS_12K = 1920          # samples per symbol at 12 kHz: 0.16 s
BT = 2.0
TX_START_S = 0.5         # FT8 audio starts 0.5 s after the 15 s boundary


class EncodeError(Exception):
    pass


@dataclass(frozen=True)
class Encoded:
    requested: str
    sent: str            # what the other station's decoder will display
    tones: tuple[int, ...]


def available() -> bool:
    return shutil.which(FT8CODE) is not None


def parse_ft8code(output: str) -> tuple[str, str, bool, list[int]]:
    """(requested, sent, lossy, tones) from ft8code's printout.

    Line 3 is fixed-column (Fortran format i2,'.',1x,a37,1x,a37,1x,a1,...):
    the message as typed, the message as it will be decoded, and '*' when
    they differ. The tones are on the line after the 'Sync Data' header.
    """
    lines = output.splitlines()
    if len(lines) < 3:
        raise EncodeError("ft8code produced no output")
    body = lines[2][4:]
    requested = body[0:37].rstrip()
    sent = body[38:75].rstrip()
    lossy = body[76:77] == "*"
    tones: list[int] = []
    for i, line in enumerate(lines):
        if line.startswith("Channel symbols"):
            if i + 2 < len(lines):
                tones = [int(c) for c in re.sub(r"\s+", "", lines[i + 2]) if c.isdigit()]
            break
    return requested, sent, lossy, tones


def encode(message: str) -> Encoded:
    """Pack a message with ft8code; refuse anything WSJT-X would mangle."""
    text = " ".join(message.upper().split())
    if not text:
        # ft8code packs blank input as telemetry without complaint.
        raise EncodeError("The message is empty.")
    try:
        out = subprocess.run([FT8CODE, text], capture_output=True, text=True, timeout=5, check=True).stdout
    except FileNotFoundError as exc:
        raise EncodeError("WSJT-X's ft8code is not installed.") from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise EncodeError(f"ft8code failed: {exc}") from exc
    requested, sent, lossy, tones = parse_ft8code(out)
    if sent.startswith("*** bad message"):
        raise EncodeError(f"“{text}” can't be sent as an FT8 message.")
    if lossy:
        raise EncodeError(f"“{text}” would arrive as “{sent}”.")
    if len(tones) != NSYM or any(t < 0 or t > 7 for t in tones):
        raise EncodeError("ft8code returned an unexpected tone sequence.")
    return Encoded(requested=requested, sent=sent, tones=tuple(tones))


@functools.lru_cache(maxsize=4)
def _pulse(nsps: int) -> np.ndarray:
    """Gaussian frequency pulse spanning 3 symbols (lib/ft2/gfsk_pulse.f90)."""
    c = math.pi * math.sqrt(2.0 / math.log(2.0))
    t = (np.arange(1, 3 * nsps + 1) - 1.5 * nsps) / nsps
    erf = np.frompyfunc(math.erf, 1, 1)
    p = 0.5 * (erf(c * BT * (t + 0.5)).astype(float) - erf(c * BT * (t - 0.5)).astype(float))
    return p


def waveform(tones, rate: int = 48_000, f0: float = 1500.0) -> np.ndarray:
    """Unit-amplitude FT8 waveform: 79 symbols, 12.64 s, tone 0 at f0 Hz."""
    tones = list(tones)
    nsym = len(tones)
    nsps = int(round(NSPS_12K * rate / 12_000))
    twopi = 2 * math.pi
    pulse = _pulse(nsps)
    dphi_peak = twopi / nsps                      # modulation index h = 1
    dphi = np.zeros((nsym + 2) * nsps)
    for j, tone in enumerate(tones):
        dphi[j * nsps: j * nsps + 3 * nsps] += dphi_peak * pulse * tone
    # Dummy symbols at both ends so the edges are not pulled toward tone 0.
    dphi[0: 2 * nsps] += dphi_peak * tones[0] * pulse[nsps: 3 * nsps]
    dphi[nsym * nsps: (nsym + 2) * nsps] += dphi_peak * tones[-1] * pulse[0: 2 * nsps]
    dphi += twopi * f0 / rate
    nwave = nsym * nsps
    seg = dphi[nsps: nsps + nwave]
    phi = np.concatenate([[0.0], np.cumsum(seg[:-1])])
    wave = np.sin(phi)
    nramp = int(round(nsps / 8.0))
    i = np.arange(nramp)
    wave[:nramp] *= (1.0 - np.cos(twopi * i / (2.0 * nramp))) / 2.0
    k1 = nwave - nramp
    wave[k1: k1 + nramp] *= (1.0 + np.cos(twopi * i / (2.0 * nramp))) / 2.0
    return wave.astype(np.float32)


def tune_tone(seconds: float, rate: int = 48_000, f0: float = 1500.0) -> np.ndarray:
    """A steady tone with soft edges, for setting levels and checking SWR."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    wave = np.sin(2 * math.pi * f0 * t)
    ramp = int(0.02 * rate)
    env = np.ones(n)
    env[:ramp] = np.linspace(0, 1, ramp)
    env[-ramp:] = np.linspace(1, 0, ramp)
    return (wave * env).astype(np.float32)
