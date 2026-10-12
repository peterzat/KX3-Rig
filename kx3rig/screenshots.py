"""Development aid: render the window to PNG files on a schedule.

    python -m kx3rig --demo --screenshot DIR

Captures the Radio and FT8 views in light and dark styles, then quits. Used to
review the design without a radio attached.
"""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402


def capture(widget: Gtk.Widget, path: str) -> bool:
    paintable = Gtk.WidgetPaintable.new(widget)
    image = paintable.get_current_image()
    snap = Gtk.Snapshot()
    image.snapshot(snap, float(widget.get_width()), float(widget.get_height()))
    node = snap.to_node()
    if node is None:
        print("screenshot: nothing rendered yet for", path)
        return False
    texture = widget.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(path)
    print("screenshot:", path)
    return True


def run(app, out_dir: str) -> None:
    if not app.demo:
        # The plans retune and key the radio; never run them against real hardware.
        print("screenshot: refused without --demo")
        app.quit()
        return
    os.makedirs(out_dir, exist_ok=True)
    win = app.window
    style = Adw.StyleManager.get_default()
    plan = os.environ.get("KX3RIG_SHOTS", "radio,ft8").split(",")
    steps: list[tuple[int, callable]] = []
    t = 4000
    if app.demo in ("off", "unplugged"):
        steps += [(t, lambda: capture(win, os.path.join(out_dir, f"connect-{app.demo}-light.png")))]
        t += 800
        steps += [(t, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                  (t + 800, lambda: capture(win, os.path.join(out_dir, f"connect-{app.demo}-dark.png")))]
        t += 1600
    else:
        if "voice" in plan:
            from .cat import Mode
            steps += [(t - 2500, lambda: app.station.link.set_frequency(14_285_000)),
                      (t - 2000, lambda: app.station.link.set_mode(Mode.USB)),
                      (t, lambda: win.show_view("radio")),
                      (t + 5000, lambda: capture(win, os.path.join(out_dir, "voice-light.png"))),
                      (t + 5200, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                      (t + 9000, lambda: capture(win, os.path.join(out_dir, "voice-dark.png"))),
                      (t + 9200, lambda: style.set_color_scheme(Adw.ColorScheme.DEFAULT)),
                      (t + 9400, lambda: app.station.link.set_frequency(14_074_000)),
                      (t + 9600, lambda: app.station.link.set_mode(Mode.DATA))]
            t += 10000
        if "scan" in plan:
            from .cat import Mode
            wait = int(os.environ.get("KX3RIG_SCAN_WAIT", "60000"))
            steps += [(t - 2500, lambda: app.station.link.set_frequency(14_300_000)),
                      (t - 2000, lambda: app.station.link.set_mode(Mode.USB)),
                      (t, lambda: win.show_view("radio")),
                      # The demo loop is "peaked" where the dial rests for 8 s; tell Loop Tune so.
                      (t + 8800, lambda: app.looptune.mark_tuned()),
                      (t + 9000, lambda: win.radio_page.scan_panel.toggle.set_active(True)),
                      (t + 9000 + wait, lambda: capture(win, os.path.join(out_dir, "scan-light.png"))),
                      (t + 9200 + wait, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                      (t + 10500 + wait, lambda: capture(win, os.path.join(out_dir, "scan-dark.png"))),
                      (t + 10700 + wait, lambda: style.set_color_scheme(Adw.ColorScheme.DEFAULT)),
                      (t + 10800 + wait, lambda: app.smartscan.stop())]
            t += 12000 + wait
        if "loop" in plan:
            from .cat import Mode

            def dialog():
                d = win.get_visible_dialog()
                return d if d is not None and hasattr(d, "knob") else None

            def knob(fraction):
                d = dialog()
                if d is not None and d.knob is not None:
                    d.knob.set_value(d.knob.get_upper() * fraction)

            def page(name):
                d = dialog()
                if d is not None:
                    d._show(name)

            def hold(on):
                d = dialog()
                if d is not None and getattr(d, "demo_hold", None) is not None:
                    d.demo_hold.set_active(on)

            shot = lambda name: (lambda: capture(win, os.path.join(out_dir, name)))  # noqa: E731
            steps += [(t - 2500, lambda: app.station.link.set_frequency(7_185_000)),
                      (t - 2000, lambda: app.station.link.set_mode(Mode.LSB)),
                      (t, lambda: win.show_view("radio")),
                      (t + 2500, shot("loop-retune-light.png")),
                      (t + 2700, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                      (t + 3000, lambda: win.open_loop_tune()),
                      (t + 4500, shot("loop-setup-dark.png")),
                      (t + 4700, lambda: page("peak"))]
            # Turn the pretend knob through resonance, like an operator would.
            for i, f in enumerate((0.6, 0.45, 0.3, 0.2, 0.12, 0.06, 0.02, 0.0)):
                steps.append((t + 5000 + i * 900, lambda f=f: knob(f)))
            t += 5000 + 8 * 900
            steps += [(t + 1500, shot("loop-peak-dark.png")),
                      (t + 1700, lambda: page("swr")),
                      (t + 2000, lambda: knob(0.08)),
                      (t + 2200, lambda: hold(True)),
                      (t + 3500, lambda: knob(0.0)),
                      (t + 5000, shot("loop-swr-dark.png")),
                      (t + 5200, lambda: hold(False)),
                      (t + 6500, lambda: (dialog() or win).grab_focus()),
                      (t + 7000, lambda: dialog() and dialog().primary.emit("clicked")),
                      (t + 8000, shot("loop-done-dark.png")),
                      (t + 8200, lambda: dialog() and dialog().close()),
                      (t + 8400, lambda: style.set_color_scheme(Adw.ColorScheme.DEFAULT)),
                      (t + 9500, shot("loop-tuned-light.png"))]
            t += 10000
        if "radio" in plan:
            steps += [(t, lambda: win.show_view("radio")),
                      (t + 3000, lambda: capture(win, os.path.join(out_dir, "radio-light.png"))),
                      (t + 3200, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                      (t + 4500, lambda: capture(win, os.path.join(out_dir, "radio-dark.png"))),
                      (t + 4700, lambda: style.set_color_scheme(Adw.ColorScheme.DEFAULT))]
            t += 5000
        if "ft8" in plan:
            wait = int(os.environ.get("KX3RIG_FT8_WAIT", "34000"))
            steps += [(t, lambda: win.show_view("ft8")),
                      (t + wait, lambda: capture(win, os.path.join(out_dir, "ft8-light.png"))),
                      (t + wait + 300, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                      (t + wait + 1600, lambda: capture(win, os.path.join(out_dir, "ft8-dark.png")))]
            t += wait + 1800
        if "qso" in plan:
            def answer_first_cq():
                for slot in sorted(app.engine.decodes, reverse=True):
                    for d in app.engine.decodes[slot]:
                        if d.message.is_cq and not d.message.cq_modifier:
                            win._tx_confirmed_band = "20m"
                            check = app.engine.answer(d)
                            print("screenshot: answering", d.text, check)
                            return
                print("screenshot: no CQ to answer")
            steps += [(t, lambda: style.set_color_scheme(Adw.ColorScheme.DEFAULT)),
                      (t + 200, lambda: win.show_view("ft8")),
                      (t + 500, lambda: win.confirm_transmit(lambda: None)),
                      (t + 2000, lambda: capture(win, os.path.join(out_dir, "confirm-light.png"))),
                      (t + 2200, lambda: _close_dialogs(win)),
                      (t + 2500, answer_first_cq),
                      (t + 22000, lambda: capture(win, os.path.join(out_dir, "qso-1.png"))),
                      (t + 52000, lambda: capture(win, os.path.join(out_dir, "qso-2.png"))),
                      (t + 52300, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                      (t + 67000, lambda: capture(win, os.path.join(out_dir, "qso-3-dark.png"))),
                      (t + 84000, lambda: capture(win, os.path.join(out_dir, "qso-4-logged-dark.png"))),
                      (t + 84300, lambda: style.set_color_scheme(Adw.ColorScheme.DEFAULT)),
                      (t + 86000, lambda: capture(win, os.path.join(out_dir, "qso-4-logged-light.png")))]
            t += 86500
    if app.demo not in ("off", "unplugged"):
        t = _keyboard_and_wspr_plans(app, win, style, plan, out_dir, steps, t)
    steps.append((t + 300, lambda: win.close()))
    for delay, fn in steps:
        GLib.timeout_add(delay, lambda f=fn: (f(), False)[1])


def _keyboard_and_wspr_plans(app, win, style, plan, out_dir, steps, t):
    from . import bandplan

    band = bandplan.BY_NAME["20m"]
    if "ft4" in plan:
        steps += [(t, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                  (t + 100, lambda: win.show_view("ft8")),
                  (t + 300, lambda: win.ft8_page.mode_buttons["FT4"].set_active(True)),
                  (t + 24000, lambda: capture(win, os.path.join(out_dir, "ft4-dark.png")))]
        t += 24500
    if "keyboard" in plan:
        steps += [(t, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                  (t + 100, lambda: win.show_view("keyboard")),
                  (t + 300, lambda: app.keyboard.tune_radio(band)),
                  (t + 25000, lambda: app.keyboard.set_their_call("W7PSK")),
                  (t + 25200, lambda: win.keyboard_page.entry.set_text(
                      app.keyboard.macro("{call} de {me} {me} k"))),
                  (t + 26000, lambda: capture(win, os.path.join(out_dir, "psk31-dark.png"))),
                  (t + 26300, lambda: win.keyboard_page.mode_buttons["cw"].set_active(True)),
                  (t + 26600, lambda: app.keyboard.tune_radio(band)),
                  (t + 50000, lambda: capture(win, os.path.join(out_dir, "cw-dark.png")))]
        t += 50500
    if "wspr" in plan:
        from .wspr import protocol as wspr

        def spots():
            import time as _time

            slot = wspr.slot_of(_time.time())
            for i in range(6, 0, -1):
                app.wspr._on_spots(slot - i, "20m", app.wspr._demo_spots(slot - i, app.station.radio.frequency))
        steps += [(t, lambda: style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)),
                  (t + 100, lambda: win.show_view("wspr")),
                  (t + 300, lambda: app.station.go_dial(wspr.DIALS["20m"])),
                  (t + 3000, spots),
                  (t + 6000, lambda: capture(win, os.path.join(out_dir, "wspr-dark.png")))]
        t += 6500
    return t


def _close_dialogs(win) -> None:
    dialog = win.get_visible_dialog() if hasattr(win, "get_visible_dialog") else None
    if dialog is not None:
        dialog.force_close()
