#!/usr/bin/env bash
# Install the DTD Customizer Bridge extension and check dependencies.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UUID="dtd-customizer-bridge@brunos3d.github.com"
DEST="$HOME/.local/share/gnome-shell/extensions/$UUID"

echo "==> Installing bridge extension to $DEST (symlink for easy iteration)"
mkdir -p "$(dirname "$DEST")"
ln -sfnT "$REPO_DIR/extension" "$DEST"

echo "==> Checking Python GTK dependencies (system python)"
/usr/bin/python3 - <<'EOF'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
print("    GTK4 + libadwaita: OK")
try:
    gi.require_version("GtkSource", "5")
    print("    GtkSourceView 5:   OK (syntax highlighting)")
except ValueError:
    print("    GtkSourceView 5:   missing (plain editor fallback)")
EOF

echo "==> Trying to enable the extension"
if gnome-extensions enable "$UUID" 2>/dev/null; then
    echo "    Enabled."
else
    echo "    GNOME Shell hasn't scanned the new extension yet."
    echo "    Log out and back in ONCE (Wayland), then run:"
    echo "        gnome-extensions enable $UUID"
    echo "    All subsequent styling iteration is fully live — no more logouts."
fi

echo
echo "Run the app with:  ./run.sh"
