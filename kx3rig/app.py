"""KX3-Rig application: startup, actions, and the command line."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, config  # noqa: E402

APP_ID = "com.zatloukal.KX3Rig"
HERE = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(os.path.dirname(HERE), "data", "icons")

SHORTCUTS_UI = """<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <object class="GtkShortcutsWindow" id="help_overlay">
    <property name="modal">True</property>
    <child>
      <object class="GtkShortcutsSection">
        <property name="section-name">shortcuts</property>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">Tuning</property>
            <child><object class="GtkShortcutsShortcut"><property name="title">Tune up or down one step</property><property name="accelerator">Up Down</property></object></child>
            <child><object class="GtkShortcutsShortcut"><property name="title">Tune ten steps</property><property name="accelerator">Page_Up Page_Down</property></object></child>
            <child><object class="GtkShortcutsShortcut"><property name="title">Choose the tuning step</property><property name="accelerator">Left Right</property></object></child>
            <child><object class="GtkShortcutsShortcut"><property name="title">Type a frequency</property><property name="accelerator">&lt;Ctrl&gt;L</property></object></child>
          </object>
        </child>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">Transmit</property>
            <child><object class="GtkShortcutsShortcut"><property name="title">Stop transmitting</property><property name="accelerator">Escape</property></object></child>
          </object>
        </child>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">General</property>
            <child><object class="GtkShortcutsShortcut"><property name="title">Radio view</property><property name="accelerator">&lt;Ctrl&gt;1</property></object></child>
            <child><object class="GtkShortcutsShortcut"><property name="title">FT8 view</property><property name="accelerator">&lt;Ctrl&gt;2</property></object></child>
            <child><object class="GtkShortcutsShortcut"><property name="title">Preferences</property><property name="accelerator">&lt;Ctrl&gt;comma</property></object></child>
            <child><object class="GtkShortcutsShortcut"><property name="title">Keyboard shortcuts</property><property name="accelerator">&lt;Ctrl&gt;question</property></object></child>
            <child><object class="GtkShortcutsShortcut"><property name="title">Quit</property><property name="accelerator">&lt;Ctrl&gt;Q</property></object></child>
          </object>
        </child>
      </object>
    </child>
  </object>
</interface>
"""


class Application(Adw.Application):
    def __init__(self, demo: str | None, screenshot_dir: str | None):
        app_id = APP_ID + (".Demo" if demo else "")
        super().__init__(application_id=app_id, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.demo = demo
        self.screenshot_dir = screenshot_dir
        self.window = None
        self.station = None
        self.engine = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        provider = Gtk.CssProvider()
        provider.load_from_path(os.path.join(HERE, "ui", "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _fix_monospace(display)
        Gtk.IconTheme.get_for_display(display).add_search_path(ICON_DIR)
        Gtk.Window.set_default_icon_name(APP_ID)

        for name, callback, accels in (
            ("quit", lambda *a: self.quit(), ["<Ctrl>q"]),
            ("preferences", lambda *a: self._preferences(), ["<Ctrl>comma"]),
            ("about", lambda *a: self._about(), []),
            ("open-log", lambda *a: self._open_log(), []),
            ("halt", lambda *a: self.window and self.window.halt(), ["Escape"]),
            ("view-radio", lambda *a: self.window and self.window.show_view("radio"), ["<Ctrl>1"]),
            ("view-ft8", lambda *a: self.window and self.window.show_view("ft8"), ["<Ctrl>2"]),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)
        self.set_accels_for_action("win.show-help-overlay", ["<Ctrl>question"])

    def do_activate(self) -> None:
        if self.window:
            self.window.present()
            return
        from .controller import Station
        from .ft8.engine import Ft8Engine
        from .ui.window import MainWindow

        settings = config.load()
        self.station = Station(settings, demo=bool(self.demo))
        if self.demo == "off":
            self.station._fake.powered = False
        elif self.demo == "unplugged":
            self.station.link._find_port = lambda: None
        self.engine = Ft8Engine(self.station, demo=bool(self.demo))
        self.window = MainWindow(self, self.station, self.engine)
        builder = Gtk.Builder.new_from_string(SHORTCUTS_UI, -1)
        self.window.set_help_overlay(builder.get_object("help_overlay"))
        if self.demo:
            self.window.add_css_class("devel")
        self.station.start()
        for sig in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, self._on_signal)
        if self.demo == "unplugged":
            from .controller import AudioStatus
            self.station._set_audio(AudioStatus())   # no Digirig: no sound card either
        self.engine.start()
        self.window.present()
        if self.screenshot_dir:
            from .screenshots import run as screenshots
            screenshots(self, self.screenshot_dir)

    def _on_signal(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE

    def do_shutdown(self) -> None:
        # Always runs on quit (window closed, Ctrl+Q, SIGINT/SIGTERM): stop
        # transmitting, drop RTS, restore the radio's CAT state.
        if self.engine:
            self.engine.stop()
        if self.station:
            if self.demo:
                self.station.halt_all()
                self.station.link.stop()
                if self.station._demo_source:
                    self.station._demo_source.stop()
            else:
                self.station.shutdown()
        Adw.Application.do_shutdown(self)

    def _preferences(self) -> None:
        from .ui import preferences

        def saved():
            self.engine.sequencer.my_call = self.station.settings.callsign
            self.engine.sequencer.my_grid4 = self.station.settings.grid4
            self.window.radio_page.update(self.station.radio)
        dialog = preferences.build(self.station, saved)
        dialog.present(self.window)

    def _about(self) -> None:
        about = Adw.AboutDialog(
            application_name="KX3-Rig",
            application_icon=APP_ID,
            developer_name="Peter Zatloukal",
            version=__version__,
            website="https://github.com/peterzat/KX3-Rig",
            issue_url="https://github.com/peterzat/KX3-Rig/issues",
            license_type=Gtk.License.GPL_3_0,
            comments="A friendly controller for the Elecraft KX3: tune, listen, talk, and work FT8.",
            copyright="© 2026 Peter Zatloukal",
        )
        about.add_credit_section("Built On", [
            "WSJT-X by Joe Taylor, K1JT, and the WSJT Development Group (FT8 encode and decode) https://wsjt.sourceforge.io",
            "GTK and libadwaita https://gnome.org",
        ])
        st = self.station.radio
        about.set_debug_info(
            f"KX3-Rig {__version__}\nPort: {st.port}\nLink: {st.link.value}\n"
            f"Firmware: {st.firmware}\nAudio: rx={self.station.audio.rx} tx={self.station.audio.tx}\n"
        )
        about.present(self.window)

    def _open_log(self) -> None:
        folder = config.data_dir()
        os.makedirs(folder, exist_ok=True)
        Gtk.FileLauncher.new(Gio.File.new_for_path(folder)).launch(self.window, None, None)


def _fix_monospace(display) -> None:
    """libadwaita 1.5's .monospace uses the 'monospace' alias (DejaVu here); use the desktop's font."""
    try:
        font = Gio.Settings.new("org.gnome.desktop.interface").get_string("monospace-font-name")
    except Exception:
        return
    family = " ".join(w for w in font.split() if not w.replace(".", "").isdigit())
    if not family:
        return
    provider = Gtk.CssProvider()
    provider.load_from_string(f'.monospace {{ font-family: "{family}"; }}')
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kx3-rig", description="Control an Elecraft KX3.")
    parser.add_argument("--demo", nargs="?", const="on", choices=["on", "off", "unplugged"],
                        help="run with a simulated KX3 and band (no hardware)")
    parser.add_argument("--screenshot", metavar="DIR", help=argparse.SUPPRESS)
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    parser.add_argument("--version", action="version", version=f"KX3-Rig {__version__}")
    args = parser.parse_args(argv)
    if args.screenshot and not args.demo:
        parser.error("--screenshot requires --demo (it drives the radio and can transmit)")
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    GLib.set_application_name("KX3-Rig")
    app = Application(args.demo, args.screenshot)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "subprocess"]
