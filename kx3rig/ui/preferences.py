"""Preferences: station identity, transmit limits, audio, and connection."""

from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import config  # noqa: E402

CALL_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$")
GRID_RE = re.compile(r"^[A-R]{2}[0-9]{2}([a-x]{2})?$", re.IGNORECASE)


def build(station, on_saved) -> Adw.PreferencesDialog:
    s: config.Settings = station.settings
    dialog = Adw.PreferencesDialog()

    def save():
        config.save(s)
        on_saved()

    # --- Station --------------------------------------------------------------
    page = Adw.PreferencesPage(title="Station", icon_name="avatar-default-symbolic")
    group = Adw.PreferencesGroup(title="Station", description="Sent in FT8 messages and saved in your log")
    call = Adw.EntryRow(title="Callsign", text=s.callsign)
    grid = Adw.EntryRow(title="Grid Square", text=s.grid)

    def on_call(row):
        text = row.get_text().strip().upper()
        ok = bool(CALL_RE.match(text))
        (row.remove_css_class if ok else row.add_css_class)("error")
        if ok and text != s.callsign:
            s.callsign = text
            save()

    def on_grid(row):
        text = row.get_text().strip()
        ok = bool(GRID_RE.match(text))
        (row.remove_css_class if ok else row.add_css_class)("error")
        if ok and text != s.grid:
            s.grid = text[:2].upper() + text[2:4] + text[4:].lower()
            save()

    name = Adw.EntryRow(title="Your Name (for PSK31 and CW macros)", text=s.operator_name)

    def on_name(row):
        text = " ".join(row.get_text().split())[:20]
        if text != s.operator_name:
            s.operator_name = text
            save()

    call.connect("changed", on_call)
    grid.connect("changed", on_grid)
    name.connect("changed", on_name)
    group.add(call)
    group.add(grid)
    group.add(name)
    license_row = Adw.ComboRow(title="License Class", subtitle="Transmit is limited to your privileges")
    license_row.set_model(Gtk.StringList.new(list(config.LICENSE_CLASSES)))
    license_row.set_selected(config.LICENSE_CLASSES.index(s.license_class))

    def on_license(row, _p):
        s.license_class = config.LICENSE_CLASSES[row.get_selected()]
        save()

    license_row.connect("notify::selected", on_license)
    group.add(license_row)
    page.add(group)

    limits = Adw.PreferencesGroup(title="Transmit Limits")
    max_power = Adw.SpinRow.new_with_range(1, 15, 1)
    max_power.set_title("Maximum Power")
    max_power.set_subtitle("KX3-Rig never asks the radio for more (AlexLoop: 10 W digital)")
    max_power.set_value(s.max_power_w)

    def on_max(row, _p):
        s.max_power_w = row.get_value()
        station.link.max_power_w = s.max_power_w
        save()

    max_power.connect("notify::value", on_max)
    limits.add(max_power)
    page.add(limits)
    dialog.add(page)

    # --- Audio -------------------------------------------------------------------
    page = Adw.PreferencesPage(title="Audio", icon_name="audio-speakers-symbolic")
    group = Adw.PreferencesGroup(title="Voice", description="Your voice goes from this computer's microphone "
                                 "through the Digirig to the KX3. Set the KX3 mic gain for about 5 ALC bars.")
    gain_row = Adw.ActionRow(title="Microphone Level")
    gain = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 2.0, 0.05)
    gain.set_value(s.voice_gain)
    gain.set_size_request(180, -1)
    gain.set_valign(Gtk.Align.CENTER)
    gain.connect("value-changed", lambda w: (station.set_voice_gain(w.get_value()), save()))
    gain_row.add_suffix(gain)
    group.add(gain_row)
    page.add(group)
    group = Adw.PreferencesGroup(title="FT8")
    level_row = Adw.ActionRow(title="Transmit Audio Level", subtitle="Aim for 4–5 ALC bars on the KX3 while tuning")
    level = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.05, 1.0, 0.05)
    level.set_value(s.data_tx_level)
    level.set_size_request(180, -1)
    level.set_valign(Gtk.Align.CENTER)
    level.connect("value-changed", lambda w: (setattr(s, "data_tx_level", w.get_value()), save()))
    level_row.add_suffix(level)
    group.add(level_row)
    page.add(group)
    dialog.add(page)

    # --- Connection ---------------------------------------------------------------
    page = Adw.PreferencesPage(title="Connection", icon_name="kx3rig-plug-symbolic")
    group = Adw.PreferencesGroup(title="Digirig", description="Serial at 38400 baud, 8 data bits, 2 stop bits. "
                                 "The KX3's RS232 menu must match.")
    port = Adw.EntryRow(title="Serial Port (blank for automatic)", text=s.serial_port)

    def on_port(row):
        s.serial_port = row.get_text().strip()
        save()

    port.connect("apply", on_port)
    port.set_show_apply_button(True)
    group.add(port)
    note = Adw.ActionRow(title="Changes take effect the next time KX3-Rig starts")
    note.add_css_class("dim-label")
    group.add(note)
    page.add(group)
    dialog.add(page)
    return dialog
