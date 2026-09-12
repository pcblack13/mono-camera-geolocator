/**
 * `desktop/preload.js` — the ONE narrow native surface the renderer gets.
 *
 * ★ WHY THIS EXISTS: Chromium's in-process GTK file chooser is broken on modern
 *   GNOME in BOTH modes we shipped — GTK4 needs two attempts to take a file and
 *   GTK3 SIGTRAPs the whole app while browsing (field reports on 1.2.1/1.2.2).
 *   The picker therefore moves OUT of the app process (zenity / main-process
 *   dialog, see main.js); the renderer asks for a file and receives its bytes.
 *
 * ★ Security posture is unchanged in spirit: contextIsolation stays on,
 *   nodeIntegration stays off, and this bridge exposes exactly one capability —
 *   "ask the USER to pick a file" — not fs, not ipc, not shell.
 */

'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('leNative', {
  /**
   * Open the system file picker. `filters`: [{name, extensions:['tif',…]}].
   * Resolves to {files: [{name, data: Uint8Array}], skipped: [{name, reason}]} —
   * `files` is empty if the user cancelled; `skipped` lists picks that could not
   * be loaded (unreadable, or beyond the 1 GiB bytes-over-IPC ceiling).
   */
  pickFiles: (filters, multiple) => ipcRenderer.invoke('le:pick-files', filters, multiple),
  /**
   * Same dialogs, but resolves to [{name, path, size}] WITHOUT reading a byte.
   * The route for multi-GB files (DEMs, videos): the local API opens the path
   * directly (`source_path`), so the file never transits IPC or an HTTP body.
   */
  pickPaths: (filters, multiple) => ipcRenderer.invoke('le:pick-paths', filters, multiple),
  /**
   * Pick a folder. Resolves to an absolute path, '' if cancelled. Used by the live
   * capture flow to let the surveyor save a copy into a directory of their choice.
   */
  pickDirectory: () => ipcRenderer.invoke('le:pick-directory'),
  /**
   * ★ DISPLAY SIZE — the app's page zoom, for big screens (a 50-inch TV draws a
   *   laptop-sized UI otherwise). `get()` → { preference: 'auto' | factor,
   *   zoom: factor in force, auto: what 'auto' means on this display, steps }.
   *   `set(preference)` applies it to every window and persists it. `onChange`
   *   fires whenever it changes (a menu pick, Ctrl +/−/0, a window moving to
   *   another display); returns the unsubscribe.
   */
  zoom: {
    get: () => ipcRenderer.invoke('le:zoom-get'),
    set: (preference) => ipcRenderer.invoke('le:zoom-set', preference),
    /** One size up (+1) or down (−1) from what is in force — Ctrl + / Ctrl −. */
    step: (direction) => ipcRenderer.invoke('le:zoom-step', direction),
    onChange: (callback) => {
      const handler = (_event, info) => callback(info);
      ipcRenderer.on('le:zoom-changed', handler);
      return () => ipcRenderer.removeListener('le:zoom-changed', handler);
    },
  },
});
