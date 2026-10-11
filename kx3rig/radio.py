"""The KX3 link: one worker thread owns the serial port.

Responsibilities, in order of importance:

1. Never transmit by accident. The port is opened with RTS and DTR deasserted
   (pyserial asserts both on open by default, and RTS keys the Digirig PTT).
   Every command passes the cat.ALLOWED allow-list. PTT has a watchdog. On
   close, RTS drops and RX; is sent if we were transmitting.
2. Be honest about connection state so the UI can guide the operator:
   no interface, port busy (another app), permission, radio not answering,
   connected.
3. Keep a live RadioState by polling, and apply operator changes (frequency,
   mode, power) as verified SETs: each SET is followed by its GET.

The port object is injected (`port_factory`) so tests and demo mode can use
kx3rig.fakeradio.FakeKX3 in place of a real serial.Serial.
"""

from __future__ import annotations

import enum
import errno
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from . import cat, devices
from .cat import DataSubmode, Mode

log = logging.getLogger(__name__)

BAUD = 38_400          # must match the KX3 RS232 menu; never scanned (see docs)
POLL_INTERVAL = 0.2    # seconds between poll cycles in receive
TX_POLL_INTERVAL = 0.4
GET_TIMEOUT = 0.35
BAND_CHANGE_TIMEOUT = 1.2
RETRY_INTERVAL = 1.5


class Link(enum.Enum):
    NO_INTERFACE = "no-interface"    # Digirig serial port not present
    BUSY = "busy"                    # another program has the port open
    PERMISSION = "permission"        # not allowed to open the port
    NO_REPLY = "no-reply"            # port open, radio silent (off, or RS232 baud mismatch)
    NOT_KX3 = "not-kx3"              # something answered, but not a KX3
    CONNECTED = "connected"


@dataclass(frozen=True)
class RadioState:
    link: Link = Link.NO_INTERFACE
    port: str = ""
    busy_with: str = ""              # friendly name of the program holding the port
    frequency: int = 0
    mode: Mode | None = None
    data_submode: DataSubmode | None = None
    bandwidth: int | None = None
    transmitting: bool = False
    ptt: bool = False                # what we asked for
    split: bool = False
    rit_on: bool = False
    xit_on: bool = False
    smeter_raw: int = 0
    smeter_db: float = -54.0
    power_set: float | None = None   # PC (requested power, W)
    power_out: float | None = None   # PO (estimated output while transmitting, W)
    swr: float | None = None         # SW (while transmitting, firmware 2.93+)
    firmware: float | None = None
    options: cat.Options | None = None


class PortError(Exception):
    def __init__(self, link: Link, message: str = ""):
        super().__init__(message)
        self.link = link


def open_serial(path: str):
    """Open the real serial port without asserting RTS/DTR.

    Build the port unopened and clear the line states first; pyserial applies
    them during open(), so RTS (the Digirig PTT line) never goes high.
    """
    import serial

    ser = serial.Serial()
    ser.port = path
    ser.baudrate = BAUD
    ser.bytesize = serial.EIGHTBITS
    ser.parity = serial.PARITY_NONE
    ser.stopbits = serial.STOPBITS_TWO
    ser.xonxoff = False
    ser.rtscts = False
    ser.dsrdtr = False
    ser.timeout = 0.03
    ser.write_timeout = 1.0
    ser.rts = False
    ser.dtr = False
    try:
        ser.exclusive = True   # flock: keeps a second KX3-Rig off the port
    except (AttributeError, ValueError):
        pass
    try:
        ser.open()
    except serial.SerialException as exc:
        code = getattr(exc, "errno", None)
        if code in (errno.EACCES, errno.EPERM) or "Permission denied" in str(exc):
            raise PortError(Link.PERMISSION, str(exc)) from exc
        if code == errno.EBUSY or "busy" in str(exc).lower() or "lock" in str(exc).lower():
            raise PortError(Link.BUSY, str(exc)) from exc
        if code == errno.ENOENT:
            raise PortError(Link.NO_INTERFACE, str(exc)) from exc
        raise PortError(Link.NO_INTERFACE, str(exc)) from exc
    return ser


@dataclass
class _Pending:
    """Operator changes waiting to be applied; newer values replace older ones."""

    band: int | None = None
    frequency: int | None = None
    mode: Mode | None = None
    data_submode: DataSubmode | None = None
    bandwidth: int | None = None
    power: float | None = None

    def empty(self) -> bool:
        return (
            self.band is None and self.frequency is None and self.mode is None and self.data_submode is None
            and self.bandwidth is None and self.power is None
        )


class RadioLink:
    """Owns the KX3 serial link on a worker thread.

    on_state(RadioState) and on_event(kind, message) are called from the worker
    thread; the UI wraps them to hop onto the main loop.
    """

    def __init__(
        self,
        on_state: Callable[[RadioState], None],
        on_event: Callable[[str, str], None] | None = None,
        port_factory: Callable[[str], object] = open_serial,
        find_port: Callable[[], str | None] = devices.find_serial_port,
        port_holders: Callable[[str], list[tuple[int, str]]] = devices.processes_holding,
        max_power_w: float = 10.0,
    ):
        self._on_state = on_state
        self._on_event = on_event or (lambda kind, msg: None)
        self._port_factory = port_factory
        self._find_port = find_port
        self._port_holders = port_holders
        self.max_power_w = max_power_w

        self._state = RadioState()
        self._ser = None
        self._splitter = cat.FrameSplitter()
        self._pending = _Pending()
        self._pending_lock = threading.Lock()
        self._tuning = False   # a band/frequency/mode change is being applied
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._rts_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._saved_meta: dict[str, int] = {}
        self._k31 = False
        self._ptt_since: float | None = None
        self._ptt_limit = 0.0
        self._cycle = 0
        self._got_bytes = False

    # --- public API (any thread) ------------------------------------------------

    @property
    def state(self) -> RadioState:
        return self._state

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kx3-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def set_band(self, number: int) -> None:
        """Change band using the KX3's own per-band memory (frequency and mode)."""
        with self._pending_lock:
            self._pending.band = int(number)
            self._pending.frequency = None
        self._wake.set()

    def set_frequency(self, hz: int) -> None:
        with self._pending_lock:
            self._pending.frequency = int(hz)
        self._update(frequency=int(hz))  # optimistic, corrected by readback
        self._wake.set()

    def set_mode(self, mode: Mode, data_submode: DataSubmode | None = None) -> None:
        with self._pending_lock:
            self._pending.mode = mode
            self._pending.data_submode = data_submode
        self._wake.set()

    def set_bandwidth(self, hz: int) -> None:
        with self._pending_lock:
            self._pending.bandwidth = int(hz)
        self._wake.set()

    def set_power(self, watts: float) -> None:
        watts = max(0.0, min(float(watts), self.max_power_w))
        with self._pending_lock:
            self._pending.power = watts
        self._wake.set()

    @property
    def tuning_pending(self) -> bool:
        """True while a band, frequency, or mode change has not reached the radio."""
        with self._pending_lock:
            return self._tuning_pending_locked()

    def _tuning_pending_locked(self) -> bool:
        p = self._pending
        return self._tuning or any(v is not None for v in (p.band, p.frequency, p.mode, p.data_submode))

    def ptt(self, on: bool, limit_s: float = 120.0, expect_frequency: int | None = None,
            expect_mode: Mode | None = None) -> bool:
        """Key or unkey the transmitter via the Digirig RTS line.

        Returns False if not connected. limit_s is the watchdog: transmit is
        dropped automatically after that many seconds. expect_frequency and
        expect_mode are what the caller's license check saw; keying is refused
        if the radio's live state no longer matches them.
        """
        ser = self._ser
        if on and (ser is None or self._state.link is not Link.CONNECTED):
            return False
        if on:
            # The license check ran against the optimistic frequency and mode, so
            # never key while a tuning change is still queued or being applied
            # (the radio would transmit on its previous frequency), and then only
            # if the live state matches what the check saw.
            with self._pending_lock:
                if self._tuning_pending_locked():
                    return False
                if expect_frequency is not None and self._state.frequency != expect_frequency:
                    return False
                if expect_mode is not None and self._state.mode is not expect_mode:
                    return False
                self._pending = _Pending(power=self._pending.power)
        with self._rts_lock:
            if ser is not None:
                try:
                    ser.rts = bool(on)
                except Exception as exc:  # port vanished mid-transmit
                    log.warning("RTS change failed: %s", exc)
                    if on:
                        return False
            self._ptt_since = time.monotonic() if on else None
            self._ptt_limit = limit_s
        self._update(ptt=bool(on))
        self._wake.set()
        return True

    # --- worker thread ----------------------------------------------------------

    def _update(self, **changes) -> None:
        with self._state_lock:
            new = replace(self._state, **changes)
            if new == self._state:
                return
            self._state = new
        try:
            self._on_state(new)
        except Exception:  # never let a UI bug kill the link thread
            log.exception("state callback failed")

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self._ptt_since is not None and self._state.link is not Link.CONNECTED:
                    self.ptt(False)   # never stay keyed without a working CAT link
                    self._on_event("watchdog", "Transmit stopped: lost contact with the radio.")
                if self._ser is None:
                    self._try_connect()
                    if self._ser is None:
                        self._sleep(RETRY_INTERVAL)
                        continue
                try:
                    if self._state.link is Link.CONNECTED:
                        self._service()
                    else:
                        self._handshake()
                        if self._state.link is not Link.CONNECTED:
                            self._sleep(RETRY_INTERVAL)
                except (OSError, PortError) as exc:
                    log.info("serial link lost: %s", exc)
                    self._drop_port()
                    self._on_event("lost", "Lost contact with the Digirig.")
                    self._sleep(RETRY_INTERVAL)
                except Exception:
                    log.exception("link error")
                    self._drop_port()
                    # Tell the station so any transmission in flight ends cleanly.
                    self._on_event("lost", "The radio link hit an error and was reset.")
                    self._sleep(RETRY_INTERVAL)
        finally:
            self._shutdown()

    def _sleep(self, seconds: float) -> None:
        self._wake.wait(seconds)
        self._wake.clear()

    def _try_connect(self) -> None:
        path = self._find_port()
        if path is None:
            self._update(link=Link.NO_INTERFACE, port="", busy_with="")
            return
        holders = [h for h in self._port_holders(path)]
        if holders:
            name = devices.friendly_app_name(holders[0][1])
            self._update(link=Link.BUSY, port=path, busy_with=name)
            return
        try:
            self._ser = self._port_factory(path)
        except PortError as exc:
            self._update(link=exc.link, port=path, busy_with="")
            return
        self._splitter = cat.FrameSplitter()
        self._update(link=Link.NO_REPLY, port=path, busy_with="")

    def _drop_port(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.rts = False
            except Exception:
                pass
            try:
                ser.close()
            except Exception:
                pass
        self._ptt_since = None
        self._update(link=Link.NO_INTERFACE, transmitting=False, ptt=False)

    def _shutdown(self) -> None:
        ser = self._ser
        if ser is None:
            return
        try:
            with self._rts_lock:
                ser.rts = False
            if self._state.transmitting or self._state.ptt:
                self._send("RX;")
            if self._state.link is Link.CONNECTED:
                # Put back what we changed (WSJT-X's Hamlib leaves K22 set).
                for key in ("K2", "AI"):
                    if key in self._saved_meta and self._saved_meta[key] != 0:
                        self._send(f"{key}{self._saved_meta[key]};")
        except Exception:
            pass
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self._ser = None

    # --- wire protocol ----------------------------------------------------------

    def _send(self, command: str) -> None:
        if not cat.is_allowed(command):
            raise ValueError(f"refusing to send non-allow-listed command {command!r}")
        self._ser.write(command.encode("ascii"))

    def _read_frames(self, timeout: float) -> list[str]:
        deadline = time.monotonic() + timeout
        frames: list[str] = []
        while time.monotonic() < deadline:
            data = self._ser.read(64)
            if data:
                self._got_bytes = True
                frames.extend(self._splitter.feed(data))
                if frames:
                    return frames
        return frames

    def _get(self, command: str, timeout: float = GET_TIMEOUT) -> str | None:
        """Send a GET and return the matching reply frame (others are dispatched)."""
        want = command[:-1] if command.endswith(";") else command
        want = want[:2]
        self._send(command)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            for frame in self._read_frames(remaining):
                kind = cat.frame_kind(frame)
                if kind == want or (want == "RV" and frame.startswith("RV")):
                    return frame
                if kind == "?":
                    return frame
                self._dispatch(frame)

    def _dispatch(self, frame: str) -> None:
        """Apply any reply (solicited or not) to the state."""
        kind = cat.frame_kind(frame)
        if kind == "IF":
            info = cat.parse_if(frame)
            if info:
                changes = dict(
                    transmitting=info.transmitting,
                    split=info.split, rit_on=info.rit_on, xit_on=info.xit_on,
                )
                # A reply that raced an operator tune would snap the display back.
                if self._pending.frequency is None and self._pending.band is None:
                    changes["frequency"] = info.frequency
                if info.mode is not None:
                    changes["mode"] = info.mode
                self._update(**changes)
        elif kind == "FA":
            f = cat.parse_fa(frame)
            if f and self._pending.frequency is None:
                self._update(frequency=f)
        elif kind == "MD":
            m = cat.parse_md(frame)
            if m:
                self._update(mode=m)
        elif kind == "DT":
            d = cat.parse_dt(frame)
            if d is not None:
                self._update(data_submode=d)
        elif kind == "BW":
            self._update(bandwidth=cat.parse_bw(frame))
        elif kind == "PC":
            p = cat.parse_pc(frame)
            if p is not None:
                self._update(power_set=p)
        elif kind == "SM":
            raw = cat.parse_sm(frame)
            if raw is not None:
                self._update(smeter_raw=raw, smeter_db=cat.smeter_db(raw, self._k31))
        elif kind == "TQ":
            tq = cat.parse_tq(frame)
            if tq is not None:
                self._update(transmitting=tq)
        elif kind == "PO":
            self._update(power_out=cat.parse_po(frame))
        elif kind == "SW":
            self._update(swr=cat.parse_sw(frame))

    # --- connection handshake -----------------------------------------------------

    def _handshake(self) -> None:
        try:
            self._ser.reset_input_buffer()
        except Exception:
            pass
        self._splitter = cat.FrameSplitter()
        self._got_bytes = False
        reply = self._get("ID;", timeout=0.6)
        if reply is None:
            self._update(link=Link.NO_REPLY)
            if self._got_bytes:
                self._on_event("garbled", "The radio sent unreadable data; check the KX3 RS232 menu is 38400.")
            return
        if cat.parse_id(reply) != 17:
            # Something answered, but not with ID017. Likely a baud mismatch; do
            # not send anything else (garbage at the wrong baud can be executed).
            self._update(link=Link.NO_REPLY)
            self._on_event("garbled", f"Unexpected reply {reply!r}; check the KX3 RS232 menu is 38400.")
            return
        om = cat.parse_om(self._get("OM;") or "")
        if om is not None and not om.is_kx3:
            self._update(link=Link.NOT_KX3, options=om)
            return
        firmware = cat.parse_rv(self._get("RVM;") or "")
        # Keep the first values read this session: a re-handshake reads our own
        # K20/AI0 back, and saving those would lose what to restore on exit.
        k2 = cat.parse_k2(self._get("K2;") or "")
        if k2 is not None:
            self._saved_meta.setdefault("K2", k2)
            if k2 != 0:
                self._send("K20;")
                self._get("K2;")
        k3 = cat.parse_k3(self._get("K3;") or "")
        self._k31 = k3 == 1
        ai = cat.parse_ai(self._get("AI;") or "")
        if ai is not None:
            self._saved_meta.setdefault("AI", ai)
            if ai != 0:
                self._send("AI0;")
                self._get("AI;")
        self._update(link=Link.CONNECTED, firmware=firmware, options=om)
        for command in ("IF;", "DT;", "BW;", "PC;", "SM;"):
            reply = self._get(command)
            if reply:
                self._dispatch(reply)
        self._on_event("connected", "Connected to your KX3.")

    # --- steady state ----------------------------------------------------------------

    def _service(self) -> None:
        self._enforce_watchdog()
        self._apply_pending()
        transmitting = self._state.ptt or self._state.transmitting
        if transmitting:
            reply = self._get("TQ;")
            if reply is None:
                # No answer while keyed: treat as lost contact (the run loop unkeys).
                self._update(link=Link.NO_REPLY, transmitting=False)
                self._on_event("no-reply", "The KX3 stopped answering.")
                return
            self._dispatch(reply)
            for command in ("PO;",) + (("SW;",) if (self._state.firmware or 0) >= 2.93 else ()):
                reply = self._get(command)
                if reply:
                    self._dispatch(reply)
            self._sleep(TX_POLL_INTERVAL)
            return
        reply = self._get("IF;")
        if reply is None:
            # The radio stopped answering (turned off, or cable pulled at the KX3 end).
            self._update(link=Link.NO_REPLY, transmitting=False)
            self._on_event("no-reply", "The KX3 stopped answering.")
            return
        self._dispatch(reply)
        reply = self._get("SM;")
        if reply:
            self._dispatch(reply)
        self._cycle += 1
        if self._cycle % 5 == 0:
            for command in ("PC;", "BW;") + (("DT;",) if self._state.mode and self._state.mode.is_data else ()):
                reply = self._get(command)
                if reply:
                    self._dispatch(reply)
            if self._state.power_out is not None or self._state.swr is not None:
                self._update(power_out=None)
        self._sleep(POLL_INTERVAL)

    def _enforce_watchdog(self) -> None:
        since = self._ptt_since
        if since is not None and time.monotonic() - since > self._ptt_limit:
            self.ptt(False)
            self._on_event("watchdog", "Transmit stopped automatically (time limit reached).")

    def _apply_pending(self) -> None:
        with self._pending_lock:
            pending, self._pending = self._pending, _Pending()
            self._tuning = any(v is not None for v in (pending.band, pending.frequency, pending.mode))
        try:
            self._apply_changes(pending)
        finally:
            with self._pending_lock:
                self._tuning = False

    def _apply_changes(self, pending: _Pending) -> None:
        if pending.empty():
            return
        if pending.band is not None:
            self._send(cat.set_band(pending.band))
            time.sleep(0.4)  # band changes take up to 500 ms (Programmer's Reference p.3)
            for command in ("IF;", "BW;", "DT;"):
                reply = self._get(command, timeout=BAND_CHANGE_TIMEOUT)
                if reply:
                    self._dispatch(reply)
        if pending.frequency is not None:
            self._send(cat.set_frequency(pending.frequency))
            reply = self._get("FA;", timeout=BAND_CHANGE_TIMEOUT)
            if reply:
                self._dispatch(reply)
        if pending.mode is not None:
            self._send(cat.set_mode(pending.mode))
            reply = self._get("MD;")
            if reply:
                self._dispatch(reply)
            if pending.data_submode is not None and pending.mode.is_data:
                self._send(cat.set_data_submode(pending.data_submode))
                reply = self._get("DT;")
                if reply:
                    self._dispatch(reply)
            reply = self._get("BW;")
            if reply:
                self._dispatch(reply)
        if pending.bandwidth is not None:
            self._send(cat.set_bandwidth(pending.bandwidth))
            reply = self._get("BW;")
            if reply:
                self._dispatch(reply)
        if pending.power is not None:
            self._send(cat.set_power(pending.power))
            reply = self._get("PC;")
            if reply:
                self._dispatch(reply)
