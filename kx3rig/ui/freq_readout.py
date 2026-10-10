"""The hero frequency readout: big digits you can tune directly.

Layout: 14.074.000 MHz, with the Hz group smaller and dimmed. Each digit is
its own label so it can be hovered, scrolled, dragged, and clicked:

- scroll or drag vertically over a digit: tune that place value
- click a digit: it becomes the tuning step (accent underline)
- keyboard (when focused): Up/Down one step, Page Up/Down ten steps,
  Left/Right move the step, digits or Ctrl+L open "Enter Frequency"
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

# Place values of the eight digits shown: 10 MHz .. 1 Hz, grouped 2.3.3
PLACES = [10_000_000, 1_000_000, 100_000, 10_000, 1_000, 100, 10, 1]
MIN_HZ = 100_000
MAX_HZ = 54_000_000


def format_groups(hz: int) -> list[str]:
    """Eight digit characters for the readout; a leading zero becomes ' '."""
    text = f"{max(0, hz):08d}"[-8:]
    if text[0] == "0":
        text = " " + text[1:]
    return list(text)


def snap_step(hz: int, steps: int, place: int) -> int:
    """Move `steps` grid points of size `place`, snapping off-grid values first.

    14.0743 MHz plus one 1 kHz step lands on 14.075, not 14.0753.
    """
    if steps > 0:
        return (hz // place) * place + steps * place
    return -(-hz // place) * place + steps * place


def parse_entry(text: str) -> int | None:
    """Parse typed frequencies: '14.074' (MHz), '14074' or '14074.5' (kHz), '7.185.000'."""
    t = text.strip().lower().replace(",", ".").replace(" ", "")
    unit = None
    for suffix, mult in (("mhz", 1_000_000), ("khz", 1_000), ("hz", 1)):
        if t.endswith(suffix):
            unit, t = mult, t[: -len(suffix)]
            break
    if not t:
        return None
    if t.count(".") > 1:          # 7.185.000 style: groups of digits
        t = t.replace(".", "")
        unit = unit or 1
    try:
        value = float(t)
    except ValueError:
        return None
    if unit is None:
        unit = 1_000_000 if value < 100 else 1_000 if value < 100_000 else 1
    hz = int(round(value * unit))
    return hz if MIN_HZ <= hz <= MAX_HZ else None


class FrequencyReadout(Gtk.Box):
    __gtype_name__ = "KX3FrequencyReadout"

    __gsignals__ = {
        "tune": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "step-changed": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, halign=Gtk.Align.CENTER)
        self.add_css_class("freq-readout")
        self.add_css_class("numeric")
        self.set_focusable(True)
        self.set_accessible_role(Gtk.AccessibleRole.SPIN_BUTTON)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Frequency"])

        self.frequency = 0
        self.step = 100
        self._digits: list[Gtk.Label] = []
        self._scroll_accum = 0.0
        self._drag_digit = -1
        self._drag_steps = 0

        for i, place in enumerate(PLACES):
            if i in (2, 5):
                sep = Gtk.Label(label=".", valign=Gtk.Align.BASELINE_FILL)
                sep.add_css_class("freq-sep")
                if i == 5:
                    sep.add_css_class("freq-hz")
                self.append(sep)
            digit = Gtk.Label(label="0", valign=Gtk.Align.BASELINE_FILL)
            digit.add_css_class("freq-digit")
            if place < 1000:
                digit.add_css_class("freq-hz")
            digit.set_tooltip_text(self._place_name(place))
            self._attach_digit_controllers(digit, i)
            self._digits.append(digit)
            self.append(digit)
        unit = Gtk.Label(label="MHz", valign=Gtk.Align.BASELINE_FILL)
        unit.add_css_class("freq-unit")
        self.append(unit)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *a: self.grab_focus())
        self.add_controller(click)

        self._popover = self._build_entry_popover()
        self.set_frequency(0)
        self.set_step(100)

    @staticmethod
    def _place_name(place: int) -> str:
        if place >= 1_000_000:
            name = f"{place // 1_000_000} MHz"
        elif place >= 1_000:
            name = f"{place // 1_000} kHz"
        else:
            name = f"{place} Hz"
        return f"Scroll to tune in {name} steps. Click to use {name} steps."

    # --- public ----------------------------------------------------------------------

    def set_frequency(self, hz: int) -> None:
        self.frequency = int(hz)
        chars = format_groups(self.frequency) if hz > 0 else list(" -------")
        for label, ch in zip(self._digits, chars):
            label.set_label("0" if ch == " " else ch)
            if ch == " ":
                label.add_css_class("blank")
            else:
                label.remove_css_class("blank")
        if hz > 0:
            self.update_property([Gtk.AccessibleProperty.VALUE_TEXT], [f"{hz / 1e6:.6f} MHz"])

    def set_step(self, step: int) -> None:
        if step not in PLACES:
            return
        self.step = step
        for label, place in zip(self._digits, PLACES):
            if place == step:
                label.add_css_class("step")
            else:
                label.remove_css_class("step")
        self.emit("step-changed", step)

    def set_online(self, online: bool) -> None:
        if online:
            self.remove_css_class("offline")
        else:
            self.add_css_class("offline")
        self.set_sensitive(online)

    # --- interaction --------------------------------------------------------------------

    def _request(self, hz: int) -> None:
        hz = max(MIN_HZ, min(MAX_HZ, int(hz)))
        if hz != self.frequency and self.frequency > 0:
            self.set_frequency(hz)
            self.emit("tune", hz)

    def nudge(self, steps: int, place: int | None = None) -> None:
        place = place or self.step
        if self.frequency <= 0:
            return
        self._request(snap_step(self.frequency, steps, place))

    def _attach_digit_controllers(self, digit: Gtk.Label, index: int) -> None:
        place = PLACES[index]
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll, place)
        digit.add_controller(scroll)

        click = Gtk.GestureClick()
        click.connect("released", lambda g, n, x, y: self.set_step(place))
        digit.add_controller(click)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda g, x, y: self._drag_begin(index))
        drag.connect("drag-update", lambda g, dx, dy: self._drag_update(index, dy))
        digit.add_controller(drag)

    def _on_scroll(self, controller, dx, dy, place) -> bool:
        unit = controller.get_unit()
        if unit == Gdk.ScrollUnit.WHEEL:
            steps = -int(round(dy)) or (-1 if dy > 0 else 1)
        else:  # smooth (touchpad): accumulate surface pixels
            self._scroll_accum += -dy / 12.0
            steps = int(self._scroll_accum)
            self._scroll_accum -= steps
        if steps:
            self.nudge(steps, place)
        return True

    def _drag_begin(self, index: int) -> None:
        self._drag_digit = index
        self._drag_steps = 0

    def _drag_update(self, index: int, dy: float) -> None:
        steps = int(-dy / 12)
        if steps != self._drag_steps:
            self.nudge(steps - self._drag_steps, PLACES[index])
            self._drag_steps = steps

    def _on_key(self, controller, keyval, keycode, state) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            self.nudge(1)
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            self.nudge(-1)
        elif keyval == Gdk.KEY_Page_Up:
            self.nudge(10)
        elif keyval == Gdk.KEY_Page_Down:
            self.nudge(-10)
        elif keyval == Gdk.KEY_Left:
            i = PLACES.index(self.step)
            self.set_step(PLACES[max(0, i - 1)])
        elif keyval == Gdk.KEY_Right:
            i = PLACES.index(self.step)
            self.set_step(PLACES[min(len(PLACES) - 1, i + 1)])
        elif (ctrl and keyval == Gdk.KEY_l) or Gdk.KEY_0 <= keyval <= Gdk.KEY_9:
            self.open_entry("" if ctrl else chr(keyval))
        else:
            return False
        return True

    # --- Enter Frequency popover --------------------------------------------------------------

    def _build_entry_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        pop.set_parent(self)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6,
                      margin_bottom=6, margin_start=6, margin_end=6)
        title = Gtk.Label(label="Enter Frequency", xalign=0)
        title.add_css_class("heading")
        self._entry = Gtk.Entry(placeholder_text="14.074 or 14074", input_purpose=Gtk.InputPurpose.NUMBER)
        self._entry.set_width_chars(16)
        self._entry.connect("activate", self._on_entry_activate)
        self._entry.connect("changed", lambda e: e.remove_css_class("error"))
        hint = Gtk.Label(label="MHz or kHz, then press Enter", xalign=0)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        box.append(title)
        box.append(self._entry)
        box.append(hint)
        pop.set_child(box)
        return pop

    def open_entry(self, initial: str = "") -> None:
        if self.frequency <= 0:
            return
        self._entry.set_text(initial)
        self._popover.popup()
        self._entry.grab_focus()
        self._entry.set_position(-1)

    def _on_entry_activate(self, entry: Gtk.Entry) -> None:
        hz = parse_entry(entry.get_text())
        if hz is None:
            entry.add_css_class("error")
            return
        self._popover.popdown()
        self._request(hz)
        self.grab_focus()
