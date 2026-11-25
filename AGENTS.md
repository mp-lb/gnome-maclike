# GNOME MacLike

Native Python GTK 4/libadwaita dashboard for GNOME on Ubuntu. Canonical repository:
https://github.com/mp-lb/gnome-maclike. Local checkout: `~/Work/gnome-maclike`.

## Product boundaries

- Familiar Mac keyboard behavior with a distinctively Linux desktop.
- Xremap is the keyboard engine. Keep mapping layers small and predictable.
- Installation and changes must have a reliable restoration path. Preserve
  before-values, newer external edits and unknown files; never guess ownership.
- Record configuration mutations in the local audit history before changing them,
  followed by observed results. Keep recovery baselines separate from history.
- No background GUI polling, decoding or filesystem work on the GTK event loop.
- No packages, udev rules or input-group membership changes. Explicit Enable may
  provision the owned keyboard service and graphical-login hook. Track their
  exact footprint; Disable removes automatic startup, Uninstall removes both.
- User wallpapers and private machine state never belong in this repository.
- No Fssstack, Electron, ArcNet, cloud resources or release publishing are configured.

## Development

Use Python 3 and the system GTK 4/libadwaita bindings. Run `python3 -B gui.py`.
Keep bytecode disabled; generated caches must never undermine uninstall ownership.
Tests use isolated files/settings and must not alter the user's desktop.

Before committing, run:

```sh
python3 -B -m unittest discover -s tests -q
git diff --check
```

Set `XREMAP_TEST_BINARY` to a checksum-verified pinned Xremap binary to validate
all mapping combinations. Set `XREMAP_TEST_SYSTEMD=1` only for local transient
user-service tests. For GUI changes, also run in a graphical session:

```sh
GSK_RENDERER=cairo python3 -B tests/gui_responsiveness.py
GSK_RENDERER=cairo python3 -B tests/gui_smoke.py /tmp/gnome-maclike-preview
```

Inspect the rendered pages. Test installation/update/uninstall fault paths when
changing ownership or recovery code. Never stop at source changes: when asked to
apply an update, verify the installed copy and reopen it in a fresh process.
During the current interactive development loop, keep the product window closed
while changing it and reopen only the tested installed version. The keyboard
session is independent of that window. User settings persist across restarts.

The helper `refresh_gui.py --dashboard` can update compatible dashboard modules
without reinstalling or resetting settings. It deliberately rejects remapper,
mapping or extension changes. Full installation identity migrations need an
explicit recoverable migration, not string replacement in installed manifests.
`refresh_gui.py --keyboard` additionally permits compatible `profiles.py`
updates, only with the keyboard session stopped. Retry interrupted publication
with the same mode. Start the session afterward to compile the updated rules;
preferences and restoration records persist.
`--lifecycle` additionally migrates runtime/bridge and startup modules while
stopped. Enable provisions the root-owned engine/condition, fixed unit and narrow
Polkit rule once, plus user login files. Disable removes login files and keeps
the inactive system integration; Uninstall removes it with authentication.
Lifecycle changes require fault tests for partial publication/removal and must
distinguish enabled intent from observed service health. Do not add auto-restart
loops that defeat the emergency stop.
