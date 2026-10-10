#!/usr/bin/env bash
# Install KX3-Rig for the current user: a venv, the kx3-rig command, and a
# desktop launcher (Activities > KX3-Rig). No sudo; system packages it needs
# are checked and, if missing, the exact apt command is printed for you to run.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(pwd)"
APP_ID=com.zatloukal.KX3Rig
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

missing=()
python3 -c 'import gi; gi.require_version("Gtk","4.0"); gi.require_version("Adw","1"); from gi.repository import Gtk, Adw' 2>/dev/null \
  || missing+=(python3-gi gir1.2-gtk-4.0 gir1.2-adw-1)
python3 -c 'import gi; gi.require_version("Gst","1.0"); from gi.repository import Gst; Gst.init(None); assert Gst.ElementFactory.find("pipewiresrc")' 2>/dev/null \
  || missing+=(gir1.2-gstreamer-1.0 gstreamer1.0-pipewire)
command -v jt9 >/dev/null && command -v ft8code >/dev/null \
  || echo "Note: WSJT-X (jt9, ft8code) not found. FT8 needs it: https://wsjt.sourceforge.io/wsjtx.html"
if ((${#missing[@]})); then
  echo "Missing system packages. Install them with:"
  echo "  sudo apt install ${missing[*]}"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv --system-site-packages .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .

mkdir -p "$DATA/applications" "$DATA/icons/hicolor/scalable/apps" "$DATA/icons/hicolor/symbolic/apps" "$DATA/metainfo"
sed "s|@EXEC@|$REPO/.venv/bin/kx3-rig|" data/$APP_ID.desktop.in > "$DATA/applications/$APP_ID.desktop"
cp data/icons/hicolor/scalable/apps/$APP_ID.svg "$DATA/icons/hicolor/scalable/apps/"
cp data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg "$DATA/icons/hicolor/symbolic/apps/"
cp data/$APP_ID.metainfo.xml "$DATA/metainfo/"
command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" || true
command -v gtk4-update-icon-cache >/dev/null && gtk4-update-icon-cache -q -t -f "$DATA/icons/hicolor" || true

echo "KX3-Rig installed. Open it from Activities, or run: $REPO/.venv/bin/kx3-rig"
echo "Try it without a radio: $REPO/.venv/bin/kx3-rig --demo"
