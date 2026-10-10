"""First thing the operator sees until the radio answers: what is connected so far.

A status page with a live checklist (Bottles' "creating bottle" steps pattern):
Digirig cable, radio answering, radio audio. Detection runs continuously, so a
correctly cabled, powered-on radio needs no clicks at all.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..radio import Link, RadioState  # noqa: E402

DIALOUT_FIX = 'sudo usermod -aG dialout "$USER"'

# Power-on keys and connector names below are from the Elecraft KX3 Control
# Panel Reference and Owner's Manual (see docs/references.md).
COPY = {
    Link.NO_INTERFACE: (
        "Connect Your Radio",
        "Plug the Digirig into a USB port on this computer. KX3-Rig finds it automatically.",
    ),
    Link.BUSY: (
        "Radio in Use",
        "{app} is using the Digirig right now. Quit {app} and KX3-Rig connects automatically.",
    ),
    Link.PERMISSION: (
        "Permission Needed",
        "Your account can't open the Digirig's serial port yet. Run this once in a terminal, "
        "then log out and back in:",
    ),
    Link.NO_REPLY: (
        "Turn On the KX3",
        "The Digirig is connected, but the radio isn't answering. To turn the KX3 on, hold "
        "BAND− and ATU TUNE together for about 2 seconds.",
    ),
    Link.NOT_KX3: (
        "This Isn't a KX3",
        "A radio answered, but it reports a different model. KX3-Rig only supports the Elecraft KX3.",
    ),
}


class Step(Adw.ActionRow):
    """One checklist row: spinner while waiting, check when done, warning on trouble."""

    def __init__(self, title: str):
        super().__init__(title=title)
        self.set_activatable(False)
        self._stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._spinner = Gtk.Spinner(spinning=True)
        self._wait = Gtk.Image.new_from_icon_name("content-loading-symbolic")
        self._wait.add_css_class("dim-label")
        self._ok = Gtk.Image.new_from_icon_name("object-select-symbolic")
        self._ok.add_css_class("success")
        self._warn = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        self._warn.add_css_class("warning")
        for name, w in (("spin", self._spinner), ("wait", self._wait), ("ok", self._ok), ("warn", self._warn)):
            self._stack.add_named(w, name)
        self._stack.set_size_request(24, 24)
        self.add_prefix(self._stack)

    def set(self, status: str, subtitle: str) -> None:
        self._stack.set_visible_child_name(status)
        self._spinner.set_spinning(status == "spin")
        self.set_subtitle(subtitle)


class ConnectPage(Gtk.Box):
    __gtype_name__ = "KX3ConnectPage"

    def __init__(self, station):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.station = station
        self.status = Adw.StatusPage(icon_name="com.zatloukal.KX3Rig", vexpand=True)
        self.status.add_css_class("compact")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        clamp = Adw.Clamp(maximum_size=480)
        clamp.set_child(box)

        # Permission fix: a copyable command.
        self.fix_box = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, visible=False)
        self.fix_label = Gtk.Label(label=DIALOUT_FIX, selectable=True)
        self.fix_label.add_css_class("monospace")
        self.fix_label.add_css_class("card")
        self.fix_label.set_margin_top(2)
        copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Copy Command", valign=Gtk.Align.CENTER)
        copy.add_css_class("flat")
        copy.connect("clicked", lambda b: Gdk.Display.get_default().get_clipboard().set(DIALOUT_FIX))
        self.fix_box.append(self.fix_label)
        self.fix_box.append(copy)
        box.append(self.fix_box)

        steps = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        steps.add_css_class("boxed-list")
        steps.add_css_class("checklist")
        self.cable = Step("Digirig Cable")
        self.radio = Step("Radio Answering")
        self.audio = Step("Radio Audio")
        for s in (self.cable, self.radio, self.audio):
            steps.append(s)
        box.append(steps)

        self.help = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=56)
        self.help.add_css_class("caption")
        self.help.add_css_class("dim-label")
        box.append(self.help)

        self.status.set_child(clamp)
        self.append(self.status)

        station.connect("radio-changed", lambda s, st: self.update())
        station.connect("audio-changed", lambda s, a: self.update())
        self.update()

    def update(self) -> None:
        st: RadioState = self.station.radio
        audio = self.station.audio
        title, desc = COPY.get(st.link, ("Connecting…", ""))
        self.status.set_title(title)
        self.status.set_description(desc.format(app=st.busy_with or "Another program"))
        self.fix_box.set_visible(st.link is Link.PERMISSION)

        port = st.port.rsplit("/", 1)[-1] if st.port else ""
        if st.link is Link.NO_INTERFACE:
            self.cable.set("spin", "Looking for the Digirig…")
            self.radio.set("wait", "Waiting for the Digirig")
        elif st.link is Link.BUSY:
            self.cable.set("warn", f"In use by {st.busy_with}")
            self.radio.set("wait", "Waiting for the serial port")
        elif st.link is Link.PERMISSION:
            self.cable.set("warn", "Found, but this account can't open it")
            self.radio.set("wait", "Waiting for permission")
        elif st.link is Link.NO_REPLY:
            self.cable.set("ok", "Found" + (f" ({_short(port)})" if port else ""))
            self.radio.set("spin", "Waiting for the KX3 to answer…")
        elif st.link is Link.NOT_KX3:
            self.cable.set("ok", "Found")
            self.radio.set("warn", "Not a KX3")
        else:
            self.cable.set("ok", "Found")
            self.radio.set("ok", "Connected")

        if audio.rx and audio.tx:
            self.audio.set("ok", "Receive and transmit audio ready")
        elif audio.error:
            self.audio.set("warn", audio.error)
        elif st.link is Link.NO_INTERFACE:
            self.audio.set("wait", "Waiting for the Digirig")
        else:
            self.audio.set("spin", "Looking for the Digirig sound card…")

        if st.link is Link.NO_REPLY:
            self.help.set_label("Already on? Check that the KX3's RS232 menu is set to 38400 and the "
                                "black cable is in the ACC1 jack, next to the power jack.")
        elif st.link is Link.NO_INTERFACE:
            self.help.set_label("The Digirig shows up as a USB serial port and a USB sound card. "
                                "Any USB port works.")
        else:
            self.help.set_label("")


def _short(name: str) -> str:
    if "CP2102" in name:
        return "CP2102N serial"
    return name
