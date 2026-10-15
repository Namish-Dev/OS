# CachyOS + Hyprland setup

The tracker and the assistant are separate processes:

```text
Hyprland session -> always-on tracker -> local SQLite activity history
terminal/voice UI -> on-demand assistant -> permission-controlled tools
```

## First run

1. Copy/clone this project to a stable location, for example
   `~/Projects/personal-os`.
2. Create a virtual environment and install dependencies:

   ```bash
   cd ~/Projects/personal-os
   python -m venv .venv
   .venv/bin/python -m pip install -r requirements-dev.txt
   ```

3. Enable the Personal OS Chrome extension and package/install the VS Code
   bridge when it is ready for your editor. Both report only local metadata to
   `127.0.0.1`; neither communicates with a cloud service.
4. In Hyprland, import session variables to the user systemd manager. Add this
   once to `~/.config/hypr/hyprland.conf`:

   ```ini
   exec-once = dbus-update-activation-environment --systemd WAYLAND_DISPLAY XDG_CURRENT_DESKTOP HYPRLAND_INSTANCE_SIGNATURE
   ```

   This is required because `hyprctl` uses the current Hyprland IPC session.
5. Start once manually inside Hyprland to verify collection:

   ```bash
   .venv/bin/python activity/activity_tracker.py
   ```

6. Install the always-on user service:

   ```bash
   chmod +x scripts/install-linux-user-service.sh
   scripts/install-linux-user-service.sh ~/Projects/personal-os
   systemctl --user status personal-os-tracker.service
   ```

The service runs after login, restarts if it fails, and requires no sudo.
Logs are available with:

```bash
journalctl --user -u personal-os-tracker.service -f
```

## Asking the assistant

The always-on tracker only observes and records. The future text/voice
assistant will be started on demand and read the same local database. It will
use the permission gate before actions such as closing windows; there will be
no unrestricted shell access. A wake word is a later optional voice frontend,
not a requirement for background tracking.

## Current limitations

- Verify `hyprctl -j activewindow` works in your session before enabling the
  service.
- The VS Code bridge source is present but still needs packaging as a VSIX.
- Terminal command content is intentionally not collected yet.
