"""Main window: the connect page until the radio answers, then Radio and FT8."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import bandplan  # noqa: E402
from ..looptune.state import RETUNE, TOUCH_UP  # noqa: E402
from ..radio import Link  # noqa: E402
from .connect_page import ConnectPage  # noqa: E402
from .ft8_page import Ft8Page  # noqa: E402
from .radio_page import STEPS, RadioPage  # noqa: E402

BANNERS = {
    Link.NO_INTERFACE: "The Digirig was disconnected. Plug it back in to continue.",
    Link.NO_REPLY: "The KX3 stopped answering. Check that it is on.",
    Link.BUSY: "Another program is using the Digirig.",
    Link.PERMISSION: "This account can't open the Digirig's serial port.",
    Link.NOT_KX3: "The connected radio isn't a KX3.",
}


class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "KX3MainWindow"

    def __init__(self, app, station, engine, smartscan=None, looptune=None):
        super().__init__(application=app, title="KX3-Rig")
        self.station = station
        self.engine = engine
        self.smartscan = smartscan
        self.looptune = looptune
        self.set_default_size(1100, 860)
        self.set_size_request(380, 520)
        self._ever_connected = False
        self._tx_confirmed_band: str | None = None

        self.toasts = Adw.ToastOverlay()
        self.root = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=250)
        self.toasts.set_child(self.root)
        self.set_content(self.toasts)

        self.root.add_named(self._build_connect(), "connect")
        self.root.add_named(self._build_main(), "main")
        self.root.set_visible_child_name("connect")

        station.connect("radio-changed", lambda s, st: self._on_radio(st))
        station.connect("audio-changed", lambda s, a: self._on_radio(self.station.radio))
        station.connect("event", lambda s, kind, msg: self._on_event(kind, msg))
        engine.connect("event", lambda e, kind, msg: self.toast(msg))
        engine.connect("transmitting", lambda e, on, text: self._on_radio(self.station.radio))

        self._add_breakpoints()
        self._on_radio(station.radio)

    # --- construction --------------------------------------------------------------------

    def _menu_button(self) -> Gtk.MenuButton:
        menu = Gio_menu()
        b = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                           tooltip_text="Main Menu")
        return b

    def _build_connect(self) -> Gtk.Widget:
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.pack_end(self._menu_button())
        view.add_top_bar(header)
        view.set_content(ConnectPage(self.station))
        return view

    def _build_main(self) -> Gtk.Widget:
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.stack = Adw.ViewStack()
        self.radio_page = RadioPage(self.station, self.toast, self.confirm_transmit, self.smartscan,
                                    self.looptune, self.open_loop_tune, self.toast_action)
        self.ft8_page = Ft8Page(self.station, self.engine, self.toast, self.confirm_transmit)
        self.stack.add_titled_with_icon(self.radio_page, "radio", "Radio", "kx3rig-transceiver-symbolic")
        self.stack.add_titled_with_icon(self.ft8_page, "ft8", "FT8", "network-transmit-receive-symbolic")
        self.switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self.switcher)
        header.pack_start(self._connection_button())
        header.pack_end(self._menu_button())
        self.tx_pill = Gtk.Label(label="ON AIR", visible=False, valign=Gtk.Align.CENTER)
        self.tx_pill.add_css_class("tag")
        self.tx_pill.add_css_class("tx")
        self.tx_pill.add_css_class("caption-heading")
        header.pack_end(self.tx_pill)
        view.add_top_bar(header)
        self.banner = Adw.Banner(revealed=False)
        view.add_top_bar(self.banner)
        view.set_content(self.stack)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        self.listen_button = Gtk.ToggleButton(active=self.station.settings.listen, valign=Gtk.Align.CENTER)
        self.listen_button.add_css_class("flat")
        self.listen_button.set_tooltip_text("Listen on This Computer")
        self.listen_button.connect("toggled", self._on_listen_toggled)
        bar.append(self.listen_button)
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.02)
        self.volume.set_value(self.station.settings.listen_volume)
        self.volume.set_size_request(160, -1)
        self.volume.set_tooltip_text("Volume")
        self.volume.connect("value-changed", lambda s: self.station.set_listen_volume(s.get_value()))
        bar.append(self.volume)
        bar.append(Gtk.Box(hexpand=True))
        level_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        level_box.set_tooltip_text("Audio level from the radio. Adjust the KX3's AF gain to keep it in the green.")
        level_box.append(_label("Radio audio", "caption", "dim-label"))
        self.rx_level = Gtk.LevelBar(min_value=0, max_value=1)
        self.rx_level.add_css_class("meter")
        self.rx_level.set_size_request(90, -1)
        level_box.append(self.rx_level)
        bar.append(level_box)
        self.step_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.step_box.append(_label("Step", "caption", "dim-label"))
        self.step_dd = Gtk.DropDown.new_from_strings([name for _, name in STEPS])
        self.step_dd.set_selected(1)
        self.step_dd.set_tooltip_text("Tuning Step")
        self.step_dd.connect("notify::selected", lambda dd, p: self.radio_page.set_step(STEPS[dd.get_selected()][0]))
        self.radio_page.readout.connect("step-changed", self._on_step_changed)
        self.step_box.append(self.step_dd)
        bar.append(self.step_box)
        bottom.append(bar)
        self.switcher_bar = Adw.ViewSwitcherBar(stack=self.stack)
        bottom.append(self.switcher_bar)
        view.add_bottom_bar(bottom)
        self._update_listen_icon()
        self.stack.connect("notify::visible-child-name", lambda *a: self._on_view_changed())
        GLib.timeout_add(100, self._update_rx_level)
        self._on_view_changed()
        return view

    def _connection_button(self) -> Gtk.MenuButton:
        self.conn_button = Gtk.MenuButton(icon_name="kx3rig-plug-symbolic", tooltip_text="Connection")
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        box.append(_label("Connection", "heading", xalign=0))
        self.conn_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.conn_list.add_css_class("boxed-list")
        self.conn_rows = {}
        for key, title in (("radio", "Radio"), ("port", "Serial Port"), ("audio", "Audio"), ("ptt", "Push-to-Talk")):
            row = Adw.ActionRow(title=title)
            row.add_css_class("property")
            self.conn_rows[key] = row
            self.conn_list.append(row)
        self.conn_list.set_size_request(320, -1)
        box.append(self.conn_list)
        pop.set_child(box)
        self.conn_button.set_popover(pop)
        return self.conn_button

    def _add_breakpoints(self) -> None:
        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        narrow.add_setter(self.switcher_bar, "reveal", True)
        narrow.add_setter(self.switcher, "visible", False)
        narrow.add_setter(self.step_box, "visible", False)
        narrow.connect("apply", lambda b: self.radio_page.readout.add_css_class("compact"))
        narrow.connect("unapply", lambda b: self.radio_page.readout.remove_css_class("compact"))
        self.add_breakpoint(narrow)
        medium = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 960sp"))
        medium.add_setter(self.ft8_page.split, "collapsed", True)
        medium.add_setter(self.ft8_page.panel_toggle, "visible", True)
        self.add_breakpoint(medium)

    # --- behaviour --------------------------------------------------------------------------

    def toast(self, message: str) -> None:
        if message:
            self.toasts.add_toast(Adw.Toast(title=message, timeout=4))

    def toast_action(self, message: str, label: str, callback) -> Adw.Toast:
        """A toast with one button (for example "Tune Loop")."""
        toast = Adw.Toast(title=message, timeout=8, button_label=label)
        toast.connect("button-clicked", lambda t: callback())
        self.toasts.add_toast(toast)
        return toast

    def open_loop_tune(self, then_scan: bool = False) -> None:
        """Open the Loop Tune guide; then_scan starts Smartscan when it finishes."""
        if self.looptune is None:
            return
        reason = self.looptune.open_refusal(self.engine)
        if reason:
            self.toast(reason)
            return
        from .looptune import LoopTuneDialog

        visible = self.get_visible_dialog() if hasattr(self, "get_visible_dialog") else None
        if isinstance(visible, LoopTuneDialog):
            return
        dialog = LoopTuneDialog(self.looptune, self.station.settings, self.smartscan, then_scan, self.toast)
        dialog.present(self)

    def _on_event(self, kind: str, message: str) -> None:
        if kind == "connected":
            self.toast("Connected to the KX3")
        elif kind in ("watchdog", "error", "garbled"):
            self.toast(message)

    def _on_radio(self, st) -> None:
        connected = st.link is Link.CONNECTED
        if connected:
            self._ever_connected = True
        self.root.set_visible_child_name("main" if self._ever_connected else "connect")
        if self._ever_connected and not connected:
            self.banner.set_title(BANNERS.get(st.link, "The radio isn't connected."))
            self.banner.set_revealed(True)
        elif connected and not self.station.audio.rx:
            self.banner.set_title("Radio audio isn't available. Check the Digirig's USB connection.")
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)
        transmitting = st.ptt or st.transmitting
        self.tx_pill.set_visible(transmitting)
        rows = self.conn_rows
        if st.options and st.firmware:
            rows["radio"].set_subtitle(f"Elecraft KX3, firmware {st.firmware:.2f}")
        else:
            rows["radio"].set_subtitle("Elecraft KX3" if connected else "Not answering")
        rows["port"].set_subtitle(_short_port(st.port) or "Not found")
        audio = self.station.audio
        rows["audio"].set_subtitle("Digirig sound card" if audio.rx and audio.tx else (audio.error or "Not found"))
        rows["ptt"].set_subtitle("Digirig RTS line")
        self.conn_button.set_icon_name("kx3rig-plug-symbolic" if connected else "dialog-warning-symbolic")

    def _on_listen_toggled(self, button) -> None:
        self.station.set_listen(button.get_active())
        self._update_listen_icon()

    def _update_listen_icon(self) -> None:
        on = self.listen_button.get_active()
        self.listen_button.set_icon_name("audio-volume-high-symbolic" if on else "audio-volume-muted-symbolic")
        self.volume.set_sensitive(on)

    def _on_step_changed(self, readout, step) -> None:
        idx = next((i for i, (s, _) in enumerate(STEPS) if s == step), None)
        if idx is not None and idx != self.step_dd.get_selected():
            self.step_dd.set_selected(idx)

    def _on_view_changed(self) -> None:
        self.step_box.set_visible(self.stack.get_visible_child_name() == "radio")

    def _update_rx_level(self) -> bool:
        db = self.station.rx_level_dbfs
        # -60 dBFS empty, -6 full; good receive level sits in the middle.
        frac = max(0.0, min(1.0, (db + 60) / 54))
        self.rx_level.set_value(frac)
        for cls in ("good", "warn"):
            self.rx_level.remove_css_class(cls)
        self.rx_level.add_css_class("warn" if db > -10 or db < -50 else "good")
        return GLib.SOURCE_CONTINUE

    def show_view(self, name: str) -> None:
        self.stack.set_visible_child_name(name)

    def halt(self) -> None:
        if self.smartscan is not None:
            self.smartscan.stop()
        self.engine.halt()
        self.station.halt_all()

    def confirm_transmit(self, action) -> None:
        """Ask once per band before the first transmission: antenna tuned, power right."""
        st = self.station.radio
        band = bandplan.band_for(st.frequency)
        name = band.name if band else ""
        # Ask again when the loop needs a retune here, even on a confirmed band.
        loop = self.looptune.need if self.looptune is not None else None
        retune = loop is not None and loop.level == RETUNE
        key = f"{name}|retune@{loop.tuned_hz}" if retune else name
        if name and key == self._tx_confirmed_band:
            action()
            return
        power = f"{st.power_set:g} W" if st.power_set is not None else "the radio's power setting"
        if retune:
            antenna = (f"{loop.explain()} Transmitting into a loop that is off resonance mostly heats it, "
                       "and the KX3 cuts power on high SWR.")
        elif loop is not None and loop.level == TOUCH_UP:
            antenna = loop.explain()
        else:
            antenna = ("Make sure your antenna is tuned for this frequency. A magnetic loop such as "
                       "the AlexLoop needs retuning after every change.")
        dialog = Adw.AlertDialog(
            heading=f"Transmit on {band.label if band else 'this band'}?",
            body=(f"KX3-Rig will transmit at {power} on {st.frequency / 1e6:.3f} MHz.\n\n{antenna} "
                  "You can stop at any time with Stop or the Esc key."),
        )
        dialog.add_response("cancel", "_Cancel")
        if loop is not None and loop.wants_action:
            dialog.add_response("tune", "Tune _Loop")
        dialog.add_response("transmit", "_Transmit")
        dialog.set_response_appearance("transmit", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("transmit")
        dialog.set_close_response("cancel")

        def on_response(d, response):
            if response == "transmit":
                self._tx_confirmed_band = key
                action()
            elif response == "tune":
                self.open_loop_tune()
        dialog.connect("response", on_response)
        dialog.present(self)


def _label(text: str, *classes: str, **kw) -> Gtk.Label:
    lbl = Gtk.Label(label=text, **kw)
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def _short_port(port: str) -> str:
    if not port:
        return ""
    import os

    real = os.path.realpath(port)
    return real if real != port else port


def Gio_menu():
    from gi.repository import Gio

    menu = Gio.Menu()
    section = Gio.Menu()
    section.append("Open Log Folder", "app.open-log")
    menu.append_section(None, section)
    section = Gio.Menu()
    section.append("_Preferences", "app.preferences")
    section.append("_Keyboard Shortcuts", "win.show-help-overlay")
    section.append("_About KX3-Rig", "app.about")
    menu.append_section(None, section)
    return menu

