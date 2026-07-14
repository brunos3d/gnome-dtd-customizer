# GNOME DTD Customizer

Live styling editor for [Dash to Dock](https://micheleg.github.io/dash-to-dock/):
edit CSS and dock settings and watch the dock change **instantly** — no shell
restart, no logout.

## Components

| Piece | Path | Role |
|---|---|---|
| Bridge extension | `extension/` | Tiny GNOME Shell extension that hot-loads `~/.config/gnome-dtd-customizer/dock.css` into the running shell theme whenever the file changes |
| Customizer app | `app/dtd-customizer.py` | GTK4/libadwaita app: CSS editor with syntax highlighting + sidebar controls bound to Dash to Dock's GSettings |
| Presets | `presets/*.css` | Starting points (floating pill, glass, neon) loadable from the app menu |

## Install & run

```bash
./install.sh     # symlinks the bridge extension + checks dependencies
./run.sh         # launches the customizer app
```

**One-time caveat (Wayland):** GNOME Shell only scans for *new* extensions at
session start. After the first `./install.sh`, log out and back in once, then:

```bash
gnome-extensions enable dtd-customizer-bridge@brunos3d.github.com
```

From then on, every styling change is live. Updating the bridge's own code
later only needs a disable/enable cycle (`gnome-extensions disable/enable`),
not a logout, because the extension directory is a symlink into this repo.

## How the live update works

Two independent live channels, mirroring how the reference projects do it:

1. **CSS hot-reload (the bridge).** The shell renders from a mutable
   `St.Theme` object (`St.ThemeContext.get_for_stage(global.stage).get_theme()`).
   Stylesheets can be added/removed from it at runtime with
   `load_stylesheet()` / `unload_stylesheet()` — the shell re-resolves styles
   for all actors immediately. The bridge watches `dock.css` with a
   `Gio.FileMonitor`; on each save it copies the file to a uniquely-named
   file in `$XDG_RUNTIME_DIR` (defeats path-based caching), loads the copy,
   then unloads the previous one (new-before-old, so the dock never flashes
   unstyled). It also re-applies after a theme swap (light/dark switch).

2. **GSettings (the sidebar).** Dash to Dock already listens to its own
   `org.gnome.shell.extensions.dash-to-dock` settings and restyles the dock
   the moment a key changes — the same "settings are the live API" pattern
   Blur My Shell uses. The sidebar binds directly to those keys (icon size,
   shrink, background color, transparency mode, opacity, running indicator).

The app and the bridge also talk over D-Bus
(`dev.brunos3d.DtdCustomizerBridge` on the `org.gnome.Shell` bus name) so the
header bar can show whether the bridge is live and surface reload errors.

## Workflow

1. Type CSS in the editor — with **Auto** on, changes apply ~400 ms after you
   stop typing (Ctrl+S / Apply for manual mode).
2. Use the sidebar for the settings Dash to Dock exposes natively.
3. Menu → **Load Preset** for a starting point; Menu → **Revert session
   changes** restores both the CSS file and all touched GSettings to their
   values from app startup — the safe escape hatch.
4. Broken CSS is harmless: GNOME Shell's CSS parser skips invalid rules, and
   deleting everything from the editor simply removes your overrides.

## Useful selectors

```css
#dashtodockContainer                  /* whole dock container            */
#dashtodockContainer #dash            /* the dash                        */
.dash-background                      /* the dock's background panel     */
.dash-item-container .app-well-app    /* app icon slots                  */
.show-apps .overview-icon             /* "show applications" button      */
.dash-label                           /* hover tooltips                  */
```

The dock container carries dynamic classes you can match for state-specific
styling: position (`.bottom`, `.left`, …), `.shrink`, `.extended`, `.fixed`,
`.overview`, `.opaque`/`.transparent`.

## Assumptions & limitations

- **Shell versions:** bridge metadata covers GNOME 45–50 (developed on 50.3).
  It uses only stable St/Gio API, so newer versions likely just need a
  metadata bump.
- **Inline styles win:** Dash to Dock applies *background color, opacity and
  border color* as inline styles on the dock background whenever
  "custom background color" is on or transparency mode ≠ default. For those
  properties use the sidebar; use CSS for everything else (radius, borders,
  shadows, icon hover effects, labels, indicators…).
- **St CSS ≠ web CSS:** GNOME Shell supports a subset (no `backdrop-filter`,
  no `transform`, limited `transition-*`). Unknown properties are ignored
  silently.
- **Scope:** the CSS file is loaded into the whole shell theme, so you *can*
  also style other shell elements from here — keep selectors scoped to
  `#dashtodockContainer` to stay dock-only.
- The app writes only to `~/.config/gnome-dtd-customizer/` and the
  dash-to-dock GSettings keys listed in `SNAPSHOT_KEYS`; upstream Dash to
  Dock files are never touched.

## License

[GNU General Public License v3.0](LICENSE)
