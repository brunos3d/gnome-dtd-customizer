#!/usr/bin/python3
"""GNOME DTD Customizer — live styling editor for Dash to Dock.

Two live-update channels, both instant (no shell restart, no logout):

1. GSettings (left sidebar): Dash to Dock watches its own settings and
   restyles the dock the moment a key changes.
2. CSS (right editor): saved to ~/.config/gnome-dtd-customizer/dock.css,
   which the "DTD Customizer Bridge" shell extension hot-loads into the
   running GNOME Shell theme.
"""

import json
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

try:
    gi.require_version("GtkSource", "5")
    from gi.repository import GtkSource
    HAVE_SOURCEVIEW = True
except (ValueError, ImportError):
    HAVE_SOURCEVIEW = False

APP_ID = "dev.brunos3d.DtdCustomizer"
DTD_SCHEMA = "org.gnome.shell.extensions.dash-to-dock"
DTD_UUID = "dash-to-dock@micxgx.gmail.com"
BRIDGE_UUID = "dtd-customizer-bridge@brunos3d.github.com"
BRIDGE_PATH = "/dev/brunos3d/DtdCustomizerBridge"
BRIDGE_IFACE = "dev.brunos3d.DtdCustomizerBridge"

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "gnome-dtd-customizer")
CSS_PATH = os.path.join(CONFIG_DIR, "dock.css")
PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "presets")

TRANSPARENCY_NICKS = ["DEFAULT", "FIXED", "DYNAMIC"]
INDICATOR_NICKS = ["DEFAULT", "DOTS", "SQUARES", "DASHES",
                   "SEGMENTED", "SOLID", "CILIORA", "METRO", "BINARY"]

# GSettings keys snapshotted at startup so "Revert" can restore them.
SNAPSHOT_KEYS = [
    "dash-max-icon-size", "custom-theme-shrink", "apply-custom-theme",
    "custom-background-color", "background-color", "background-opacity",
    "transparency-mode", "running-indicator-style",
]

DEFAULT_TEMPLATE = """\
/* gnome-dtd-customizer — dock.css
 * Saved automatically; every save restyles the dock instantly.
 *
 * Useful Dash to Dock selectors:
 *   #dashtodockContainer            whole dock container
 *   #dashtodockContainer #dash      the dash itself
 *   .dash-background                the dock's background panel
 *   .dash-item-container            icon slots
 *   .app-well-app .overview-icon    app icons
 *   .show-apps .overview-icon       the "show applications" button
 *   .dash-label                     hover labels (tooltips)
 *
 * Tip: for background color/opacity prefer the sidebar controls —
 * Dash to Dock sets those as inline styles that beat any stylesheet.
 */

#dashtodockContainer .dash-background {
    /* border-radius: 24px; */
    /* border: 2px solid rgba(255, 255, 255, 0.2); */
    /* box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4); */
}
"""


def read_css() -> str:
    try:
        with open(CSS_PATH, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return DEFAULT_TEMPLATE


def write_css(text: str) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    GLib.file_set_contents(CSS_PATH, text.encode("utf-8"))


class Bridge:
    """Talks to the shell extension over D-Bus (destination org.gnome.Shell)."""

    def __init__(self):
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def status(self):
        """Return the bridge status dict, or None if the bridge isn't running."""
        try:
            reply = self._bus.call_sync(
                "org.gnome.Shell", BRIDGE_PATH, BRIDGE_IFACE, "GetStatus",
                None, GLib.VariantType("(s)"),
                Gio.DBusCallFlags.NONE, 500, None)
            return json.loads(reply.unpack()[0])
        except (GLib.Error, json.JSONDecodeError):
            return None


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="DTD Customizer",
                         default_width=1100, default_height=720)
        self.bridge = Bridge()
        self.settings = self._load_dtd_settings()
        self.snapshot = self._take_snapshot()
        self._apply_source = 0
        self._loading_buffer = False

        self.toaster = Adw.ToastOverlay()
        self.set_content(self.toaster)

        toolbar = Adw.ToolbarView()
        self.toaster.set_child(toolbar)

        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        self.status_label = Gtk.Label(label="checking bridge…")
        self.status_label.add_css_class("dim-label")
        header.pack_start(self.status_label)

        apply_btn = Gtk.Button(label="Apply", tooltip_text="Save CSS (Ctrl+S)")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", lambda *_: self.apply_css())
        header.pack_end(apply_btn)

        self.auto_apply = Gtk.ToggleButton(
            label="Auto", active=True,
            tooltip_text="Apply automatically while typing")
        header.pack_end(self.auto_apply)

        header.pack_end(self._build_menu_button())

        split = Adw.OverlaySplitView(sidebar_width_fraction=0.34,
                                     min_sidebar_width=320)
        split.set_sidebar(self._build_sidebar())
        split.set_content(self._build_editor())
        toolbar.set_content(split)

        self._install_shortcuts()
        self._refresh_status()
        GLib.timeout_add_seconds(3, self._refresh_status)

    # ----- setup helpers -------------------------------------------------

    def _load_dtd_settings(self):
        source = Gio.SettingsSchemaSource.get_default()
        if source and source.lookup(DTD_SCHEMA, True):
            return Gio.Settings.new(DTD_SCHEMA)
        return None

    def _take_snapshot(self):
        snap = {"css": read_css(), "gsettings": {}}
        if self.settings:
            for key in SNAPSHOT_KEYS:
                snap["gsettings"][key] = self.settings.get_value(key)
        return snap

    def _build_menu_button(self):
        menu = Gio.Menu()
        presets = Gio.Menu()
        if os.path.isdir(PRESETS_DIR):
            for name in sorted(os.listdir(PRESETS_DIR)):
                if name.endswith(".css"):
                    label = name[:-4].replace("-", " ").title()
                    presets.append(label, f"win.load-preset('{name}')")
        menu.append_submenu("Load Preset", presets)
        menu.append("Open dock.css folder", "win.open-folder")
        menu.append("Dash to Dock preferences", "win.dtd-prefs")
        menu.append("Revert session changes", "win.revert")

        for name, cb in [
            ("open-folder", self._on_open_folder),
            ("dtd-prefs", self._on_dtd_prefs),
            ("revert", self._on_revert),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)

        preset_action = Gio.SimpleAction.new(
            "load-preset", GLib.VariantType("s"))
        preset_action.connect("activate", self._on_load_preset)
        self.add_action(preset_action)

        return Gtk.MenuButton(icon_name="open-menu-symbolic",
                              menu_model=menu)

    # ----- sidebar (GSettings controls) ----------------------------------

    def _build_sidebar(self):
        page = Adw.PreferencesPage()

        if not self.settings:
            group = Adw.PreferencesGroup(
                title="Dash to Dock not found",
                description="Schema org.gnome.shell.extensions.dash-to-dock "
                            "is not installed; only the CSS editor is available.")
            page.add(group)
            return page

        s = self.settings

        group = Adw.PreferencesGroup(
            title="Dock settings",
            description="Applied instantly via GSettings")
        page.add(group)

        icon_row = Adw.SpinRow.new_with_range(16, 128, 1)
        icon_row.set_title("Max icon size")
        s.bind("dash-max-icon-size", icon_row, "value",
               Gio.SettingsBindFlags.DEFAULT)
        group.add(icon_row)

        shrink_row = Adw.SwitchRow(title="Shrink dock",
                                   subtitle="Compact padding around icons")
        s.bind("custom-theme-shrink", shrink_row, "active",
               Gio.SettingsBindFlags.DEFAULT)
        group.add(shrink_row)

        builtin_row = Adw.SwitchRow(
            title="Built-in theme",
            subtitle="Dash to Dock's own theme; disables color/opacity below")
        s.bind("apply-custom-theme", builtin_row, "active",
               Gio.SettingsBindFlags.DEFAULT)
        group.add(builtin_row)

        bg_group = Adw.PreferencesGroup(title="Background")
        page.add(bg_group)

        custom_bg_row = Adw.SwitchRow(title="Custom background color")
        s.bind("custom-background-color", custom_bg_row, "active",
               Gio.SettingsBindFlags.DEFAULT)
        bg_group.add(custom_bg_row)

        color_row = Adw.ActionRow(title="Background color")
        color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(),
                                          valign=Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        if rgba.parse(s.get_string("background-color")):
            color_btn.set_rgba(rgba)
        color_btn.connect(
            "notify::rgba",
            lambda btn, _p: s.set_string("background-color",
                                         btn.get_rgba().to_string()))
        color_row.add_suffix(color_btn)
        bg_group.add(color_row)

        transparency_row = Adw.ComboRow(
            title="Transparency mode",
            model=Gtk.StringList.new(["Theme default", "Fixed opacity",
                                      "Dynamic (windows nearby)"]))
        current = s.get_string("transparency-mode")
        if current in TRANSPARENCY_NICKS:
            transparency_row.set_selected(TRANSPARENCY_NICKS.index(current))
        transparency_row.connect(
            "notify::selected",
            lambda row, _p: s.set_string(
                "transparency-mode", TRANSPARENCY_NICKS[row.get_selected()]))
        bg_group.add(transparency_row)

        opacity_row = Adw.ActionRow(
            title="Opacity", subtitle="Used by Fixed opacity mode")
        opacity_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 1, 0.05)
        opacity_scale.set_size_request(160, -1)
        opacity_scale.set_value(s.get_double("background-opacity"))
        opacity_scale.set_valign(Gtk.Align.CENTER)
        opacity_scale.connect(
            "value-changed",
            lambda scale: s.set_double("background-opacity",
                                       scale.get_value()))
        opacity_row.add_suffix(opacity_scale)
        bg_group.add(opacity_row)

        misc_group = Adw.PreferencesGroup(title="Indicators")
        page.add(misc_group)

        indicator_row = Adw.ComboRow(
            title="Running indicator",
            model=Gtk.StringList.new([n.title() for n in INDICATOR_NICKS]))
        current = s.get_string("running-indicator-style")
        if current in INDICATOR_NICKS:
            indicator_row.set_selected(INDICATOR_NICKS.index(current))
        indicator_row.connect(
            "notify::selected",
            lambda row, _p: s.set_string(
                "running-indicator-style",
                INDICATOR_NICKS[row.get_selected()]))
        misc_group.add(indicator_row)

        return page

    # ----- editor ---------------------------------------------------------

    def _build_editor(self):
        if HAVE_SOURCEVIEW:
            self.buffer = GtkSource.Buffer()
            lang = GtkSource.LanguageManager.get_default().get_language("css")
            if lang:
                self.buffer.set_language(lang)
            scheme_mgr = GtkSource.StyleSchemeManager.get_default()
            style = Adw.StyleManager.get_default()
            scheme_id = "Adwaita-dark" if style.get_dark() else "Adwaita"
            scheme = scheme_mgr.get_scheme(scheme_id)
            if scheme:
                self.buffer.set_style_scheme(scheme)
            view = GtkSource.View(buffer=self.buffer, show_line_numbers=True,
                                  tab_width=4, insert_spaces_instead_of_tabs=True,
                                  auto_indent=True, monospace=True)
        else:
            self.buffer = Gtk.TextBuffer()
            view = Gtk.TextView(buffer=self.buffer, monospace=True)

        view.set_top_margin(8)
        view.set_left_margin(8)
        view.set_right_margin(8)

        self._loading_buffer = True
        self.buffer.set_text(read_css())
        self._loading_buffer = False
        self.buffer.connect("changed", self._on_buffer_changed)

        scrolled = Gtk.ScrolledWindow(child=view, vexpand=True, hexpand=True)
        return scrolled

    def _on_buffer_changed(self, _buffer):
        if self._loading_buffer or not self.auto_apply.get_active():
            return
        if self._apply_source:
            GLib.source_remove(self._apply_source)
        self._apply_source = GLib.timeout_add(400, self._debounced_apply)

    def _debounced_apply(self):
        self._apply_source = 0
        self.apply_css(toast=False)
        return GLib.SOURCE_REMOVE

    def apply_css(self, toast=True):
        start, end = self.buffer.get_bounds()
        text = self.buffer.get_text(start, end, True)
        try:
            write_css(text)
        except GLib.Error as e:
            self._toast(f"Could not save CSS: {e.message}")
            return
        if toast:
            self._toast("CSS applied" if self.bridge.status()
                        else "Saved — bridge extension not active")
        self._refresh_status()

    # ----- actions ---------------------------------------------------------

    def _on_load_preset(self, _action, value):
        path = os.path.join(PRESETS_DIR, value.get_string())
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            self._toast(f"Cannot load preset: {e}")
            return
        self.buffer.set_text(text)
        self.apply_css()

    def _on_open_folder(self, *_args):
        Gio.AppInfo.launch_default_for_uri(f"file://{CONFIG_DIR}", None)

    def _on_dtd_prefs(self, *_args):
        GLib.spawn_command_line_async(f"gnome-extensions prefs {DTD_UUID}")

    def _on_revert(self, *_args):
        self.buffer.set_text(self.snapshot["css"])
        write_css(self.snapshot["css"])
        if self.settings:
            for key, value in self.snapshot["gsettings"].items():
                self.settings.set_value(key, value)
        self._toast("Reverted to session start")

    def _install_shortcuts(self):
        trigger = Gtk.ShortcutTrigger.parse_string("<Control>s")
        action = Gtk.CallbackAction.new(
            lambda *_: (self.apply_css(), True)[1])
        controller = Gtk.ShortcutController()
        controller.set_scope(Gtk.ShortcutScope.GLOBAL)
        controller.add_shortcut(Gtk.Shortcut.new(trigger, action))
        self.add_controller(controller)

    # ----- status ----------------------------------------------------------

    def _refresh_status(self):
        status = self.bridge.status()
        if status:
            err = status.get("lastError")
            if err:
                self.status_label.set_label(f"⚠ bridge error: {err}")
            else:
                self.status_label.set_label(
                    f"● live (reload #{status.get('generation', 0)})")
        else:
            self.status_label.set_label("○ bridge not active")
        return GLib.SOURCE_CONTINUE

    def _toast(self, text):
        self.toaster.add_toast(Adw.Toast.new(text))


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.get_active_window() or Window(self)
        win.present()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
