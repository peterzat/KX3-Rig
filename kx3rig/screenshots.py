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
                      (t + 67000, lambda: capture(win, os.path.join(out_dir, "qso-3-dark.png")))]
            t += 67500
    steps.append((t + 300, lambda: win.close()))
    for delay, fn in steps:
        GLib.timeout_add(delay, lambda f=fn: (f(), False)[1])


def _close_dialogs(win) -> None:
    dialog = win.get_visible_dialog() if hasattr(win, "get_visible_dialog") else None
    if dialog is not None:
        dialog.force_close()
