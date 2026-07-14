// DTD Customizer Bridge
//
// Watches ~/.config/gnome-dtd-customizer/dock.css and hot-loads it into the
// running GNOME Shell theme (St.Theme). Every save of the file is reflected
// immediately on screen — no shell restart, no logout.
//
// Live-update mechanism:
//   St.ThemeContext.get_for_stage(global.stage).get_theme() is the theme the
//   shell is rendering right now. Stylesheets can be added to / removed from
//   it at runtime with load_stylesheet()/unload_stylesheet(); the shell
//   re-resolves style for all actors on the spot. To defeat any caching by
//   file path, each reload copies dock.css to a fresh uniquely-named file in
//   $XDG_RUNTIME_DIR and loads that copy, then unloads the previous one.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DBUS_IFACE = `
<node>
  <interface name="dev.brunos3d.DtdCustomizerBridge">
    <method name="Reload"/>
    <method name="GetStatus">
      <arg type="s" direction="out" name="statusJson"/>
    </method>
  </interface>
</node>`;

const DBUS_PATH = '/dev/brunos3d/DtdCustomizerBridge';

export default class DtdCustomizerBridge extends Extension {
    enable() {
        this._generation = 0;
        this._lastError = '';
        this._loadedFile = null;
        this._reloadTimeoutId = 0;

        this._configDir = GLib.build_filenamev([
            GLib.get_user_config_dir(), 'gnome-dtd-customizer',
        ]);
        this._cssPath = GLib.build_filenamev([this._configDir, 'dock.css']);
        GLib.mkdir_with_parents(this._configDir, 0o755);
        if (!GLib.file_test(this._cssPath, GLib.FileTest.EXISTS)) {
            GLib.file_set_contents(this._cssPath,
                '/* gnome-dtd-customizer — dock.css\n' +
                '   Styles saved here are applied to GNOME Shell live. */\n');
        }

        this._runtimeDir = GLib.build_filenamev([
            GLib.get_user_runtime_dir(), 'gnome-dtd-customizer',
        ]);
        GLib.mkdir_with_parents(this._runtimeDir, 0o700);

        this._cssFile = Gio.File.new_for_path(this._cssPath);
        this._monitor = this._cssFile.monitor_file(
            Gio.FileMonitorFlags.WATCH_MOVES, null);
        this._monitorId = this._monitor.connect(
            'changed', (_monitor, _file, _other, eventType) => {
                if (eventType === Gio.FileMonitorEvent.CHANGES_DONE_HINT ||
                    eventType === Gio.FileMonitorEvent.RENAMED ||
                    eventType === Gio.FileMonitorEvent.CREATED)
                    this._scheduleReload();
            });

        // A theme swap (light/dark switch, shell theme change) builds a new
        // St.Theme that doesn't contain our stylesheet — re-apply to it.
        this._themeContext = St.ThemeContext.get_for_stage(global.stage);
        this._themeChangedId = this._themeContext.connect('changed', () => {
            this._loadedFile = null;
            this._scheduleReload();
        });

        this._dbus = Gio.DBusExportedObject.wrapJSObject(DBUS_IFACE, this);
        this._dbus.export(Gio.DBus.session, DBUS_PATH);

        this._reload();
    }

    disable() {
        if (this._reloadTimeoutId) {
            GLib.source_remove(this._reloadTimeoutId);
            this._reloadTimeoutId = 0;
        }
        if (this._themeChangedId) {
            this._themeContext.disconnect(this._themeChangedId);
            this._themeChangedId = 0;
        }
        this._themeContext = null;
        if (this._monitor) {
            this._monitor.disconnect(this._monitorId);
            this._monitor.cancel();
            this._monitor = null;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
        this._unloadCurrent();
        this._cssFile = null;
    }

    _scheduleReload() {
        if (this._reloadTimeoutId)
            GLib.source_remove(this._reloadTimeoutId);
        this._reloadTimeoutId = GLib.timeout_add(
            GLib.PRIORITY_DEFAULT, 50, () => {
                this._reloadTimeoutId = 0;
                this._reload();
                return GLib.SOURCE_REMOVE;
            });
    }

    _unloadCurrent() {
        if (!this._loadedFile)
            return;
        const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
        try {
            theme.unload_stylesheet(this._loadedFile);
        } catch {
            // Theme may already have been replaced; nothing to do.
        }
        try {
            this._loadedFile.delete(null);
        } catch {
            // Best-effort cleanup of the runtime copy.
        }
        this._loadedFile = null;
    }

    _reload() {
        this._lastError = '';
        try {
            const [ok, contents] = GLib.file_get_contents(this._cssPath);
            if (!ok)
                throw new Error(`Cannot read ${this._cssPath}`);

            this._generation++;
            const copyPath = GLib.build_filenamev([
                this._runtimeDir, `dock-${this._generation}.css`,
            ]);
            GLib.file_set_contents(copyPath, contents);

            const newFile = Gio.File.new_for_path(copyPath);
            const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
            // Load the new sheet before unloading the old one so the dock
            // never flashes back to its unstyled state between the two.
            theme.load_stylesheet(newFile);
            this._unloadCurrent();
            this._loadedFile = newFile;
        } catch (e) {
            this._lastError = String(e.message ?? e);
            console.warn(`[dtd-customizer-bridge] reload failed: ${this._lastError}`);
        }
    }

    // --- D-Bus API (callable at destination org.gnome.Shell) ---

    Reload() {
        this._reload();
    }

    GetStatus() {
        return JSON.stringify({
            version: this.metadata.version,
            cssPath: this._cssPath,
            loaded: this._loadedFile !== null,
            generation: this._generation,
            lastError: this._lastError,
        });
    }
}
