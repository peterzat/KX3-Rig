"""Signal meter: S-units in receive, output power and SWR in transmit."""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..cat import smeter_label  # noqa: E402

# Bar position: S0 (-54 dB re S9) at 0, S9 at 0.6, S9+60 at 1.0.
S9_POS = 0.6


def smeter_fraction(db_over_s9: float) -> float:
    if db_over_s9 <= 0:
        return max(0.0, S9_POS * (1 + db_over_s9 / 54.0))
    return min(1.0, S9_POS + (1 - S9_POS) * db_over_s9 / 60.0)


class SignalMeter(Gtk.Box):
    """LevelBar with a scale row and a value label, smoothed to read like a needle."""

    __gtype_name__ = "KX3SignalMeter"

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        top = Gtk.Box(spacing=12)
        self.caption = Gtk.Label(label="Signal", xalign=0)
        self.caption.add_css_class("caption-heading")
        self.caption.add_css_class("dim-label")
        self.value = Gtk.Label(label="S0", xalign=1, hexpand=True)
        self.value.add_css_class("heading")
        self.value.add_css_class("numeric")
        top.append(self.caption)
        top.append(self.value)

        self.bar = Gtk.LevelBar(min_value=0.0, max_value=1.0, hexpand=True)
        self.bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
        for name in ("low", "high", "full"):
            self.bar.remove_offset_value(name)
        self.bar.add_css_class("meter")
        self.bar.update_property([Gtk.AccessibleProperty.LABEL], ["Signal strength"])

        self.scale = Gtk.Box()
        self.scale.add_css_class("meter-scale")
        self.scale.add_css_class("dim-label")
        self.scale.add_css_class("numeric")
        self._set_scale(["1", "3", "5", "7", "9", "+20", "+40", "+60"])

        self.append(top)
        self.append(self.bar)
        self.append(self.scale)

        self._target = 0.0
        self._shown = 0.0
        self._last = time.monotonic()
        self._tx = False
        GLib.timeout_add(33, self._animate)

    def _set_scale(self, marks: list[str]) -> None:
        child = self.scale.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.scale.remove(child)
            child = nxt
        for i, mark in enumerate(marks):
            label = Gtk.Label(label=mark, hexpand=True,
                              xalign=0 if i == 0 else 1 if i == len(marks) - 1 else 0.5)
            self.scale.append(label)

    def show_receive(self, db_over_s9: float) -> None:
        if self._tx:
            self._tx = False
            self.bar.remove_css_class("tx")
            self.value.remove_css_class("warning")
            self.value.remove_css_class("error")
            self.caption.set_label("Signal")
            self._set_scale(["1", "3", "5", "7", "9", "+20", "+40", "+60"])
        self._target = smeter_fraction(db_over_s9)
        self.value.set_label(smeter_label(db_over_s9))

    def show_transmit(self, watts: float | None, swr: float | None, max_watts: float) -> None:
        if not self._tx:
            self._tx = True
            self.bar.add_css_class("tx")
            self.caption.set_label("Output")
            top = max(1, int(round(max_watts)))
            self._set_scale(["0"] + [f"{top * k // 4}" for k in (1, 2, 3)] + [f"{top} W"])
        self._target = 0.0 if watts is None else min(1.0, watts / max(0.1, max_watts))
        parts = []
        if watts is not None:
            parts.append(f"{watts:.1f} W")
        if swr is not None:
            parts.append(f"SWR {swr:.1f}")
        self.value.set_label("  ·  ".join(parts) or "Transmitting")
        # Yellow above 1.5:1, red above 2:1 (the loop needs a touch-up, then a retune).
        for cls in ("warning", "error"):
            self.value.remove_css_class(cls)
        if swr is not None and swr > 2.0:
            self.value.add_css_class("error")
        elif swr is not None and swr > 1.5:
            self.value.add_css_class("warning")

    def _animate(self) -> bool:
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        if self._target > self._shown:
            self._shown = self._target  # fast attack
        else:
            self._shown += (self._target - self._shown) * min(1.0, dt / 0.3)  # ~300 ms decay
        self.bar.set_value(self._shown)
        return GLib.SOURCE_CONTINUE
