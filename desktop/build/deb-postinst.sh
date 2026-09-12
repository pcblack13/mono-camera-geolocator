#!/bin/bash
# Mono Camera Geolocator deb post-install.
#
# ★ Replaces electron-builder's default, whose sandbox heuristic is WRONG on
#   Ubuntu >= 24.04: it tests `unshare --user` AS ROOT, but root is exempt from
#   the AppArmor restriction that blocks UNPRIVILEGED user namespaces — so it
#   concluded "namespaces work", skipped the SUID bit, and the app crashed at
#   launch for every normal user. The SUID sandbox helper is Chromium's designed
#   fallback and safe to enable unconditionally; Chromium prefers namespaces at
#   runtime whenever they actually work.
#
# ★ The install dir is SPACELESS on purpose: Chromium's zygote launcher execvp's
#   its own path split on spaces — '/opt/Mono Camera Geolocator' died at launch
#   with "failed to execvp: /opt/Mono". The human name lives in the .desktop entry.

APP_DIR='/opt/MonoCameraGeolocator'
BIN="$APP_DIR/mono-camera-geolocator"
LINK='/usr/bin/mono-camera-geolocator'
ALT_NAME='mono-camera-geolocator'

if type update-alternatives 2>/dev/null >&1; then
    if [ -L "$LINK" ] && [ -e "$LINK" ] && [ "$(readlink "$LINK")" != "/etc/alternatives/$ALT_NAME" ]; then
        rm -f "$LINK"
    fi
    update-alternatives --install "$LINK" "$ALT_NAME" "$BIN" 100 || ln -sf "$BIN" "$LINK"
else
    ln -sf "$BIN" "$LINK"
fi

# ★ Unconditional: owned by root via dpkg, SUID so the sandbox works with OR
#   without unprivileged user namespaces.
chown root:root "$APP_DIR/chrome-sandbox" || true
chmod 4755 "$APP_DIR/chrome-sandbox" || true

if hash update-mime-database 2>/dev/null; then
    update-mime-database /usr/share/mime || true
fi

if hash update-desktop-database 2>/dev/null; then
    update-desktop-database /usr/share/applications || true
fi
