# Shortcut selection and coverage

We port habits that make the desktop feel familiar: switching apps and windows,
closing or minimizing, editing and selecting text, navigating text, working with
tabs, and copying/pasting in terminals. We reuse the Linux equivalent where it
exists. We do not aim to make every application behave exactly like its Mac build.

The app's **Shortcuts** page is the inventory of what we have accounted for. It
includes every explicit current mapping, common shortcuts inherited through the
base modifier swap, approximations, planned additions and deliberate exclusions.
Search by action or keys, filter by decision, then expand a row for behavior,
scope, layer, priority and its reference. Browsing it changes no settings and
requires no setup check.

## Evidence and its limits

[Apple's reference](https://support.apple.com/en-us/102650) is our broad starting
point: common actions, session controls, Finder, text editing, accessibility and
links to application-specific references. It is not a finite specification of
everything every Mac app can bind. Apple's
[text-editing reference](https://support.apple.com/en-me/guide/pages/tanc0ffef022/mac),
[capture reference](https://support.apple.com/en-ie/102646), and
[Chrome's Mac/Linux reference](https://support.google.com/chrome/answer/157179)
help separate platform conventions from application behavior. Descriptions in our
catalog explain our implementation; they are not a copy of Apple's guide.

We also read three discussions on 2026-11-25:

| Discussion | Qualitative signals used |
| --- | --- |
| [Daily shortcuts, r/MacOS](https://www.reddit.com/r/MacOS/comments/1g7a583/some_extremely_useful_mac_keyboard_shortcuts_that/) | Switching/hiding, URL focus, same-app windows, moving files and previewing files. |
| [Most-used shortcuts, r/mac](https://www.reddit.com/r/mac/comments/18bwyi3/) | Launcher/search, window handling, screenshots, URL focus and zoom. |
| [Power-user favorites, r/MacOS](https://www.reddit.com/r/MacOS/comments/1qjyvmr/macos_power_users_whats_your_musthave_keyboard/) | Capture variants, switching/hiding and line-edge text movement; also custom tools that are not OS defaults. |

These are self-selected anecdotes, not a representative population survey or a
frequency ranking. They corroborate our user's workflow priorities and suggest
gaps to review. A Reddit claim does not establish a key's actual meaning; verify
that against the relevant vendor reference and the destination application's
behavior. Some comments conflate hiding and minimizing or mix custom bindings
with defaults, which is exactly why our catalog needs explicit distinctions.

## Selection philosophy

1. **Prefer inherited behavior.** If Command-to-Control already produces the
   intended application action, document it instead of adding another rule.
2. **Prefer existing GNOME actions.** Translate desktop habits into native
   facilities. Do not build another window manager, launcher or screenshot app.
3. **Prioritize common workflows.** Chrome/Chromium, standalone terminals and
   Files are the compatibility targets. Familiar navigation and editing come
   before obscure menu accelerators.
4. **Keep exceptions bounded.** A terminal category rule earns its place because
   clipboard and process control genuinely differ. A Files rule must be an
   explicit product decision, not the beginning of arbitrary widget detection.
5. **Name approximations.** Minimizing one window is not macOS Hide. Sending a
   Control chord is not proof that every app implements the same action.
6. **Preserve recovery and important input.** Never add a global deletion,
   confirmation-bypassing logout or process-killing command merely because Mac
   has a similar chord. Protect language input and accessibility workflows.
7. **Accept omissions.** Apple-only services, hardware-specific combinations,
   niche app menus and custom launcher commands are not requirements for a
   familiar Ubuntu desktop. Prefer a layer toggle or Stop to accumulating hacks.

This refines the conflict policy in [MENTAL_MODEL.md](MENTAL_MODEL.md). Each new
mapping needs an owner, scope, displaced behavior, escape route and live trial.
Known missing-context and embedded-terminal limitations remain limitations; this
catalog does not fix them or certify live behavior.

## Priorities

| Decision | Scope |
| --- | --- |
| Keep and validate | Base editing/browser shortcuts, app and same-app window switching, Control+Up overview / Control+Down desktop reveal, quit/lock, the minimize approximation, terminal clipboard and text navigation. |
| Next | Command+M, launcher/search, plain-style paste and basic screenshot entrypoints. |
| Later | Capture-to-clipboard variants, fullscreen, browser tab/history translation and a deliberate Files policy. |
| Not planned | App Exposé (Control+Down deliberately means Show Desktop), bulk-close/hide emulation, global force quit, session/power shortcuts, empty-Trash commands, Apple services/hardware and wholesale app-menu emulation. |

“Next” and “Later” express priority, not a delivery date. Planned entries are not
implemented. The base swap may still emit a combination for a planned or excluded
entry, so those labels do not mean the physical keys are disabled or harmless.

Command+Backspace now uses the native Control+Shift+Backspace binding in
Chrome/Chromium and Codex (Chatgpt app), documented
in [Chromium's editing implementation](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/third_party/blink/renderer/core/editing/editing_behavior.cc).
[GTK's multiline text view](https://github.com/GNOME/gtk/blob/main/gtk/gtktextview.c)
uses paragraph deletion, with different behavior at line boundaries (including
deleting the entire first paragraph at document start in a local GTK test).
Other apps and standalone terminals keep their existing behavior; no generic
selection macro or shell-specific line-kill command is injected.

## What the catalog guarantees

[shortcuts.py](shortcuts.py) is the single data source for the GUI. Each entry has
a stable ID, keys, action, category, implementation status, scope/limitations,
layer, reference and priority. Explicit mappings link to the compiled rule/key
pairs. A test fails when a rule is added or removed without corresponding
inventory coverage, including navigation variants and emergency-stop aliases.

The status labels mean:

| Label | Meaning |
| --- | --- |
| Mapped | An explicit translation/request exists; its layer, context and running session still matter. |
| Uses app shortcut | Inherited Control behavior; the target app decides the result. |
| Approximation | Implemented, with an intentional difference described in the entry. |
| Planned | Reviewed and prioritized, but no dedicated mapping exists yet. |
| Not planned | Reviewed and outside the current product scope. |
| Native / recovery | Preserved terminal behavior or the remapper's emergency exit. |

This is an implementation inventory, not a live “enabled” or “verified in every
app” indicator. There is no finite enumeration of all inherited application
shortcuts: the catalog includes common examples and an explicit app-defined
shortcut family. Browser numbered tabs and Shift navigation variants are listed
individually; terminal actions have their own scoped entries.

Future requests should capture the desired action, Mac chord, target application
or scope, and current Linux behavior. Stable IDs make duplicates and decisions
traceable. A request form can come later; it must not imply that every submitted
shortcut will be implemented. No form, telemetry or automatic submission is added
in this version.
