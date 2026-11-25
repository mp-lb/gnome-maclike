"""Compile a few optional layers into ordinary upstream Xremap configuration."""
import copy
import json
from pathlib import Path
import re

LAYERS = {
    'command': ('Command key', 'Left Alt becomes Command on PC keyboards; left Super becomes Option.'),
    'control': ('Separate physical Control', 'Control becomes Super in apps. Standalone terminals keep Control.'),
    'terminal': ('Terminal shortcuts', 'Command-C/V copies and pastes; Command-T/W opens and closes tabs.'),
    'desktop': ('Desktop shortcuts', 'Command-Tab switches apps; Command-backtick cycles their windows. Q quits; H minimizes; Control-Command-Q locks. Control-Up: overview. Control-Down: show desktop.'),
    'navigation': ('Text navigation', 'Command-arrows: line/document edges. Option-arrows: words. Shift selects. Option-Backspace: delete a word. Command-Backspace: delete to line start in Chrome/Chromium and Codex.'),
}
DEFAULTS = {'keyboard': 'pc', 'layers': {key: True for key in LAYERS}, 'excluded_apps': [], 'wallpaper_folder': ''}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Unrecognized dashboard preferences; preserved for review.')
    if value['keyboard'] not in ('pc', 'apple'):
        raise ValueError('Choose a PC or Apple keyboard.')
    if not isinstance(value['layers'], dict) or set(value['layers']) != set(LAYERS):
        raise ValueError('Unrecognized keyboard layers.')
    if any(type(v) is not bool for v in value['layers'].values()):
        raise ValueError('Layer selections must be on or off.')
    if not isinstance(value['excluded_apps'], list) or len(value['excluded_apps']) > 100:
        raise ValueError('Invalid application exclusions.')
    if any(not isinstance(v, str) or not re.fullmatch(r'[\w. -]{1,150}', v) for v in value['excluded_apps']):
        raise ValueError('Use application names, separated by commas; regular expressions are not accepted.')
    if not isinstance(value['wallpaper_folder'], str) or len(value['wallpaper_folder']) > 4096:
        raise ValueError('Invalid wallpaper folder.')
    return copy.deepcopy(value)


def compile_profile(source, preferences):
    prefs = validate(preferences)
    layers = prefs['layers']
    if not layers['command']:
        return {'keymap': [{'name': 'Emergency stop', 'remap': {'Ctrl-Alt-Esc': {'action': 'exit'}}}]}
    source = Path(source)
    config = json.loads((source / 'config.json').read_text())
    terminal_apps = config['modmap'][0]['application']['only']
    hardware = json.loads((source / (prefs['keyboard'] + '.json')).read_text())
    if not layers['control']:
        config['modmap'] = [config['modmap'][-1]]  # Both physical Controls stay Control.
    config['modmap'].extend(hardware['modmap'])
    keymaps = []
    for mapping in config['keymap']:
        name = mapping['name']
        emergency = name.startswith('Emergency')
        terminal = name.startswith('Terminal')
        if not emergency and not layers['terminal' if terminal else 'desktop']:
            continue
        if not emergency:
            mapping.setdefault('application', {'only': '/.+/'})
            if prefs['excluded_apps']:
                mapping['application']['not'] = prefs['excluded_apps']
        keymaps.append(mapping)
    if layers['desktop']:
        overview_match = {'only': '/.+/'}
        if prefs['excluded_apps']:
            overview_match['not'] = prefs['excluded_apps']
        # Same lifetime as Command+Tab: hold Super until the existing Command
        # release hook releases it. Grave is the physical key above Tab.
        cycle_window = [{'press': 'Grave'}, {'release': 'Grave'}]
        enter_windows = [{'release': 'Ctrl_R'}, {'press': 'Super_L'},
                         *cycle_window, {'set_mode': 'switcher'}]
        keymaps.append({'name': 'Open the native same-app window switcher', 'mode': 'command', 'exact_match': True,
                        'application': overview_match,
                        'remap': {'Grave': enter_windows, 'Shift-Grave': enter_windows}})
        # GNOME may own focus while its switcher is open. Do not require an app
        # name for subsequent presses. Physical Shift remains held for reverse.
        keymaps.append({'name': 'Cycle the native same-app window switcher', 'mode': 'switcher', 'exact_match': True,
                        'application': {'not': prefs['excluded_apps']},
                        'remap': {'Grave': cycle_window, 'Shift-Grave': cycle_window}})
        # Physical Control is Super_R in apps and Ctrl in standalone terminals
        # (or when the separate-Control layer is off). Tap the managed overlay
        # key, rather than relying on a user-defined toggle-overview binding.
        keymaps.append({'name': 'Control Up opens overview', 'mode': 'default', 'exact_match': True,
                        'application': overview_match,
                        'remap': {'Super_R-Up': 'Super_L', 'Ctrl-Up': 'Super_L'}})
        # Keep the toggle available when revealing the desktop leaves no focused
        # app. The native Super+D action restores windows on the next press.
        keymaps.append({'name': 'Control Down toggles desktop', 'mode': 'default', 'exact_match': True,
                        'application': {'not': prefs['excluded_apps']},
                        'remap': {'Super_R-Down': 'Super_L-d', 'Ctrl-Down': 'Super_L-d'}})
    if layers['navigation']:
        app_match = {'only': '/.+/'}
        if prefs['excluded_apps']:
            app_match['not'] = prefs['excluded_apps']
        # Command holds Ctrl_R outside Xremap's modifier tracker. Lift it for
        # line edges; keep it for document edges. Shift stays an ordinary key.
        command = {}
        for direction, target in [('Left', 'Home'), ('Right', 'End')]:
            for shift in ('', 'Shift-'):
                command[shift + direction] = [{'release': 'Ctrl_R'}, shift + target, {'press': 'Ctrl_R'}]
        for direction, target in [('Up', 'Home'), ('Down', 'End')]:
            for shift in ('', 'Shift-'):
                command[shift + direction] = shift + target
        keymaps.append({'name': 'Command text navigation', 'mode': 'command', 'exact_match': True,
                        'application': app_match, 'remap': command})
        # Native Chromium action. GTK's similarly named action can delete the
        # entire first paragraph at column zero; terminals have shell semantics.
        # Keep this bounded rather than injecting a selection/deletion macro.
        keymaps.append({'name': 'Command delete to line start', 'mode': 'command', 'exact_match': True,
                        'application': {'only': '/(?i)^(chromium|chromium-browser|google-chrome|google-chrome-stable|google-chrome-beta|google-chrome-unstable|chatgpt|codex)$/',
                                        'not': prefs['excluded_apps']},
                        'remap': {'BackSpace': 'Shift-BackSpace'}})
        option = {}
        for direction in ('Left', 'Right'):
            for shift in ('', 'Shift-'):
                option['Alt_L-' + shift + direction] = 'Ctrl_L-' + shift + direction
        # Only normal mode: Command+Option combinations belong to the app.
        keymaps.append({'name': 'Option word navigation', 'mode': 'default', 'exact_match': True,
                        'application': app_match, 'remap': option})
        # Native Ctrl+Backspace in GUI text fields. Standalone shells already
        # receive Alt+Backspace, their conventional backward-word command.
        keymaps.append({'name': 'Option word deletion', 'mode': 'default', 'exact_match': True,
                        'application': {'only': '/.+/', 'not': terminal_apps + prefs['excluded_apps']},
                        'remap': {'Alt_L-BackSpace': 'Ctrl_L-BackSpace'}})
    config['keymap'] = keymaps
    return config
