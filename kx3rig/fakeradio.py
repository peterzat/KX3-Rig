"""A KX3 emulator that speaks the CAT protocol over a serial-port-like object.

Used by the tests (to exercise the real RadioLink code) and by demo mode
(`kx3-rig --demo`), so the whole app can run with no hardware attached.
It implements the subset of commands the app uses, with formats taken from the
Programmer's Reference, and records everything it receives so tests can assert
on exactly what the driver sent.
"""

from __future__ import annotations

import random
import threading
import time

from .cat import Mode


class FakeKX3:
    """Looks like an open pyserial port connected to a powered-on KX3."""

    def __init__(self, frequency: int = 14_074_000, mode: Mode = Mode.DATA, powered: bool = True,
                 garbled: bool = False, k2: int = 2, ai: int = 0, firmware: str = "02.93"):
        self.frequency = frequency
        self.mode = mode
        self.data_submode = 0
        self.bandwidth = 2800
        self.power = 5
        self.k2 = k2
        self.k3 = 0
        self.ai = ai
        self.firmware = firmware
        self.powered = powered
        self.garbled = garbled
        self.cat_tx = False
        self.split = False
        self.xit_on = False
        self._rts = False
        self.dtr = False
        self.received: list[str] = []
        self.rts_history: list[bool] = []
        self.closed = False
        self._inbuf = ""
        self._out = bytearray()
        self._lock = threading.Lock()
        self.smeter = 5
        self.timeout = 0.03
        # Per-band memory like the real radio's BAND keys: band -> (frequency, mode).
        self.band_memory = {
            0: (1_840_000, Mode.LSB), 1: (3_985_000, Mode.LSB), 2: (5_357_000, Mode.USB),
            3: (7_185_000, Mode.LSB), 4: (10_136_000, Mode.DATA), 5: (14_074_000, Mode.DATA),
            6: (18_100_000, Mode.USB), 7: (21_300_000, Mode.USB), 8: (24_950_000, Mode.USB),
            9: (28_400_000, Mode.USB), 10: (50_125_000, Mode.USB),
        }

    # --- pyserial surface -------------------------------------------------------

    @property
    def rts(self) -> bool:
        return self._rts

    @rts.setter
    def rts(self, value: bool) -> None:
        self._rts = bool(value)
        self.rts_history.append(self._rts)

    @property
    def transmitting(self) -> bool:
        return self.powered and (self._rts or self.cat_tx)

    def write(self, data: bytes) -> int:
        with self._lock:
            self._inbuf += data.decode("ascii")
            while ";" in self._inbuf:
                cmd, self._inbuf = self._inbuf.split(";", 1)
                self.received.append(cmd + ";")
                if self.powered:
                    reply = self._handle(cmd)
                    if reply:
                        if self.garbled:
                            reply = "\x13" + reply[::-1]
                        self._out.extend(reply.encode("latin-1"))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        deadline = time.monotonic() + self.timeout
        while True:
            with self._lock:
                if self._out:
                    chunk = bytes(self._out[:size])
                    del self._out[:size]
                    return chunk
            if time.monotonic() >= deadline:
                return b""
            time.sleep(0.002)

    def reset_input_buffer(self) -> None:
        with self._lock:
            self._out.clear()

    def close(self) -> None:
        self.closed = True

    # --- radio behaviour ------------------------------------------------------------

    def _if_frame(self) -> str:
        return (
            f"IF{self.frequency:011d}     +0000"
            f"0{1 if self.xit_on else 0} 00{1 if self.transmitting else 0}{self.mode.value}"
            f"00{1 if self.split else 0}0"
            f"{self.data_submode if self.k3 else 0}1 ;"
        )

    def _handle(self, cmd: str) -> str | None:
        if cmd == "ID":
            return "ID017;"
        if cmd == "OM":
            return "OM A-F-------02;"
        if cmd == "RVM":
            return f"RVM{self.firmware};"
        if cmd == "IF":
            return self._if_frame()
        if cmd == "FA":
            return f"FA{self.frequency:011d};"
        if cmd.startswith("FA") and len(cmd) == 13:
            self.frequency = int(cmd[2:])
            return None
        if cmd == "MD":
            return f"MD{self.mode.value};"
        if cmd.startswith("MD") and len(cmd) == 3:
            self.mode = Mode(int(cmd[2]))
            self.bandwidth = {Mode.CW: 400, Mode.AM: 4000, Mode.FM: 6000}.get(self.mode, 2800)
            return None
        if cmd.startswith("BN") and len(cmd) == 4:
            self.frequency, self.mode = self.band_memory[int(cmd[2:])]
            return None
        if cmd == "DT":
            return f"DT{self.data_submode};"
        if cmd.startswith("DT") and len(cmd) == 3:
            self.data_submode = int(cmd[2])
            return None
        if cmd == "BW":
            return f"BW{self.bandwidth // 10:04d};"
        if cmd.startswith("BW") and len(cmd) == 6:
            self.bandwidth = int(cmd[2:]) * 10
            return None
        if cmd == "PC":
            return f"PC{self.power:03d};"
        if cmd.startswith("PC") and len(cmd) == 5:
            self.power = min(int(cmd[2:]), 15)
            return None
        if cmd == "SM":
            if self.transmitting:
                return "SM0000;"
            self.smeter = max(2, min(8, self.smeter + random.choice((-1, 0, 0, 1))))
            return f"SM{self.smeter:04d};"
        if cmd == "TQ":
            return f"TQ{1 if self.transmitting else 0};"
        if cmd == "PO":
            return f"PO{int(self.power * 10) if self.transmitting else 0:03d};"
        if cmd == "SW":
            return "SW013;"
        if cmd in ("K2", "K3", "AI"):
            return f"{cmd}{getattr(self, cmd.lower())};"
        if cmd[:2] in ("K2", "K3", "AI") and len(cmd) == 3:
            setattr(self, cmd[:2].lower(), int(cmd[2]))
            return None
        if cmd == "TX":
            self.cat_tx = True
            return None
        if cmd == "RX":
            self.cat_tx = False
            return None
        return "?;"
