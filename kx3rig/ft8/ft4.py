"""FT4: encode and synthesize transmit audio, and read jt9's FT4 decodes.

WSJT-X builds an `ft4code` program but does not install it (CMakeLists.txt
install list, WSJT-X master b4f9a43), so KX3-Rig encodes FT4 itself. FT4 packs
messages into the same 77 bits as FT8, so the installed `ft8code` supplies
the packing and the "would arrive as" check. The rest is a port of WSJT-X:

- lib/ft4/genft4.f90: scramble the 77 bits with rvec, add the CRC and LDPC
  parity (lib/ft8/encode174_91.f90, generator lib/ft8/ldpc_174_91_c_generator.f90,
  CRC lib/crc14.cpp), Gray-map bit pairs to 4 tones, and frame
  s4 d29 s4 d29 s4 d29 s4 with four Costas arrays: 103 tones. genft4's tones
  do not include the two ramp symbols; gen_ft4wave adds them.
- lib/ft4/gen_ft4wave.f90: continuous-phase GFSK, BT = 1.0, h = 1,
  576 samples per symbol at 12 kHz (20.833 baud and tone spacing), 105 symbol
  times with raised-cosine ramp-up and ramp-down symbols: 5.04 s.

Timing (Modulator/Modulator.cpp, mainwindow.cpp): 7.5 s periods, audio starts
0.3 s into the period, and jt9 -5 reads 72576 samples (6.048 s). Dial
frequencies are WSJT-X's defaults (models/FrequencyList.cpp; none for 160 m
or 60 m). jt9 prints FT4 decodes like FT8's, with " + " in place of " ~ "
(lib/decoder.f90:724-725).
"""

from __future__ import annotations

import functools
import math
import subprocess

import numpy as np

from . import encode as _ft8
from .decode import RawDecode

PERIOD = 7.5
TX_START_S = 0.3
DECODE_SAMPLES = 72_576
NSYM = 103
NSPS_12K = 576
BT = 1.0
SIGNAL_WIDTH_HZ = 90
TONE_SPACING_HZ = 12_000 / NSPS_12K
DIALS = {"80m": 3_575_000, "40m": 7_047_500, "30m": 10_140_000, "20m": 14_080_000, "17m": 18_104_000,
         "15m": 21_140_000, "12m": 24_919_000, "10m": 28_180_000, "6m": 50_318_000}

COSTAS = ((0, 1, 3, 2), (1, 0, 2, 3), (2, 3, 1, 0), (3, 2, 0, 1))
RVEC = (0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0,
        1, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 0, 1,
        0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1)
CRC14_POLY = 0x2757

# 83 rows of 91 bits (23 hex digits, the last holding 3 bits).
GENERATOR = (
    "8329ce11bf31eaf509f27fc", "761c264e25c259335493132", "dc265902fb277c6410a1bdc",
    "1b3f417858cd2dd33ec7f62", "09fda4fee04195fd034783a", "077cccc11b8873ed5c3d48a",
    "29b62afe3ca036f4fe1a9da", "6054faf5f35d96d3b0c8c3e", "e20798e4310eed27884ae90",
    "775c9c08e80e26ddae56318", "b0b811028c2bf997213487c", "18a0c9231fc60adf5c5ea32",
    "76471e8302a0721e01b12b8", "ffbccb80ca8341fafb47b2e", "66a72a158f9325a2bf67170",
    "c4243689fe85b1c51363a18", "0dff739414d1a1b34b1c270", "15b48830636c8b99894972e",
    "29a89c0d3de81d665489b0e", "4f126f37fa51cbe61bd6b94", "99c47239d0d97d3c84e0940",
    "1919b75119765621bb4f1e8", "09db12d731faee0b86df6b8", "488fc33df43fbdeea4eafb4",
    "827423ee40b675f756eb5fe", "abe197c484cb74757144a9a", "2b500e4bc0ec5a6d2bdbdd0",
    "c474aa53d70218761669360", "8eba1a13db3390bd6718cec", "753844673a27782cc42012e",
    "06ff83a145c37035a5c1268", "3b37417858cc2dd33ec3f62", "9a4a5a28ee17ca9c324842c",
    "bc29f465309c977e89610a4", "2663ae6ddf8b5ce2bb29488", "46f231efe457034c1814418",
    "3fb2ce85abe9b0c72e06fbe", "de87481f282c153971a0a2e", "fcd7ccf23c69fa99bba1412",
    "f0261447e9490ca8e474cec", "4410115818196f95cdd7012", "088fc31df4bfbde2a4eafb4",
    "b8fef1b6307729fb0a078c0", "5afea7acccb77bbc9d99a90", "49a7016ac653f65ecdc9076",
    "1944d085be4e7da8d6cc7d0", "251f62adc4032f0ee714002", "56471f8702a0721e00b12b8",
    "2b8e4923f2dd51e2d537fa0", "6b550a40a66f4755de95c26", "a18ad28d4e27fe92a4f6c84",
    "10c2e586388cb82a3d80758", "ef34a41817ee02133db2eb0", "7e9c0c54325a9c15836e000",
    "3693e572d1fde4cdf079e86", "bfb2cec5abe1b0c72e07fbe", "7ee18230c583cccc57d4b08",
    "a066cb2fedafc9f52664126", "bb23725abc47cc5f4cc4cd2", "ded9dba3bee40c59b5609b4",
    "d9a7016ac653e6decdc9036", "9ad46aed5f707f280ab5fc4", "e5921c77822587316d7d3c2",
    "4f14da8242a8b86dca73352", "8b8b507ad467d4441df770e", "22831c9cf1169467ad04b68",
    "213b838fe2ae54c38ee7180", "5d926b6dd71f085181a4e12", "66ab79d4b29ee6e69509e56",
    "958148682d748a38dd68baa", "b8ce020cf069c32a723ab14", "f4331d6d461607e95752746",
    "6da23ba424b9596133cf9c8", "a636bcbc7b30c5fbeae67fe", "5cb0d86a07df654a9089a20",
    "f11f106848780fc9ecdd80a", "1fbb5364fb8d2c9d730d5ba", "fcb86bc70a50c9d02a5d034",
    "a534433029eac15f322e34c", "c989d9c7c3d3b8c55d75130", "7bb38b2f0186d46643ae962",
    "2644ebadeb44b9467d1f42c", "608cc857594bfbb55d69600", 
)


def parse_bits77(output: str) -> list[int]:
    """The 77 source bits from ft8code's printout."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("Source-encoded message") and i + 1 < len(lines):
            bits = [int(c) for c in lines[i + 1].strip() if c in "01"]
            if len(bits) == 77:
                return bits
    raise _ft8.EncodeError("ft8code printed no 77-bit message.")


def crc14(bits: list[int]) -> int:
    """boost::augmented_crc<14, 0x2757> over the bits as encode174_91 lays them
    out: 77 message bits, 3 zeros, and 16 zero bits (12 bytes)."""
    reg = 0
    for bit in list(bits) + [0] * (96 - len(bits)):
        top = (reg >> 13) & 1
        reg = ((reg << 1) | bit) & 0x3FFF
        if top:
            reg ^= CRC14_POLY
    return reg


@functools.lru_cache(maxsize=1)
def _generator() -> np.ndarray:
    gen = np.zeros((83, 91), np.uint8)
    for i, row in enumerate(GENERATOR):
        for j, digit in enumerate(row):
            value = int(digit, 16)
            for jj in range(3 if j == 22 else 4):
                if value & (1 << (3 - jj)):
                    gen[i, j * 4 + jj] = 1
    return gen


def encode174_91(bits77: list[int]) -> list[int]:
    """77 message bits, their CRC-14, and 83 LDPC parity bits."""
    crc = crc14(list(bits77) + [0, 0, 0])
    message = list(bits77) + [(crc >> (13 - k)) & 1 for k in range(14)]
    parity = (_generator().astype(np.int32) @ np.array(message, np.int32)) % 2
    return message + [int(p) for p in parity]


def tones(bits77: list[int]) -> tuple[int, ...]:
    scrambled = [(b + r) % 2 for b, r in zip(bits77, RVEC)]
    cw = encode174_91(scrambled)
    gray = {0: 0, 1: 1, 2: 3, 3: 2}
    data = [gray[2 * cw[2 * i] + cw[2 * i + 1]] for i in range(87)]
    return (COSTAS[0] + tuple(data[0:29]) + COSTAS[1] + tuple(data[29:58])
            + COSTAS[2] + tuple(data[58:87]) + COSTAS[3])


@functools.lru_cache(maxsize=4)
def _pulse(nsps: int) -> np.ndarray:
    """gfsk_pulse(1.0, t) over 3 symbols (lib/ft2/gfsk_pulse.f90)."""
    c = math.pi * math.sqrt(2.0 / math.log(2.0))
    t = (np.arange(1, 3 * nsps + 1) - 1.5 * nsps) / nsps
    erf = np.vectorize(math.erf)
    return 0.5 * (erf(c * BT * (t + 0.5)) - erf(c * BT * (t - 0.5)))


def waveform(tones, rate: int = 48_000, f0: float = 1500.0) -> np.ndarray:
    """Unit-amplitude FT4 waveform: 105 symbol times (5.04 s), tone 0 at f0 Hz."""
    tones = list(tones)
    nsym = len(tones)
    nsps = int(round(NSPS_12K * rate / 12_000))
    twopi = 2 * math.pi
    pulse = _pulse(nsps)
    dphi_peak = twopi / nsps                      # hmod = 1
    nwave = (nsym + 2) * nsps
    dphi = np.zeros(nwave)
    for j, tone in enumerate(tones):
        dphi[j * nsps: j * nsps + 3 * nsps] += dphi_peak * pulse * tone
    dphi += twopi * f0 / rate
    phi = np.concatenate([[0.0], np.cumsum(dphi[:-1])])
    wave = np.sin(phi)
    i = np.arange(nsps)
    wave[:nsps] *= (1.0 - np.cos(twopi * i / (2.0 * nsps))) / 2.0
    k1 = (nsym + 1) * nsps
    wave[k1:k1 + nsps] *= (1.0 + np.cos(twopi * i / (2.0 * nsps))) / 2.0
    return wave.astype(np.float32)


def encode(message: str) -> _ft8.Encoded:
    """Pack with ft8code (refusing anything WSJT-X would mangle), then FT4 tones."""
    text = " ".join(message.upper().split())
    if not text:
        raise _ft8.EncodeError("The message is empty.")
    try:
        out = subprocess.run([_ft8.FT8CODE, text], capture_output=True, text=True, timeout=5, check=True).stdout
    except FileNotFoundError as exc:
        raise _ft8.EncodeError("WSJT-X's ft8code is not installed.") from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise _ft8.EncodeError(f"ft8code failed: {exc}") from exc
    requested, sent, lossy, _ = _ft8.parse_ft8code(out)
    if sent.startswith("*** bad message"):
        raise _ft8.EncodeError(f"“{text}” can't be sent as an FT4 message.")
    if lossy:
        raise _ft8.EncodeError(f"“{text}” would arrive as “{sent}”.")
    return _ft8.Encoded(requested=requested, sent=sent, tones=tones(parse_bits77(out)))


def parse_jt9_ft4_line(line: str) -> RawDecode | None:
    """One FT4 stdout line: format(i6.6,i4,f5.1,i5,' + ',1x,a37,1x,a2)."""
    line = line.rstrip("\n")
    if len(line) < 25 or line[20:23] != " + ":
        return None
    try:
        snr = int(line[6:10])
        dt = float(line[10:15])
        freq = int(line[15:20])
    except ValueError:
        return None
    msg37 = line[24:61].ljust(37)
    low = msg37[36] == "?"
    text = (msg37[:36] if low else msg37).strip()
    if not text:
        return None
    return RawDecode(line[0:6], snr, dt, freq, text, low, line[62:64].strip())
