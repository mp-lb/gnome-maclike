"""Reviewed shortcut inventory. Describes behavior; never installs mappings.

Stable IDs support future requests. bindings links explicit entries to compiled
Xremap rules, so tests can detect missing inventory coverage when rules change.
"""
from dataclasses import dataclass

SOURCES = {
    'apple': ('Apple shortcut reference', 'https://support.apple.com/en-us/102650'),
    'text': ('Apple Pages text shortcuts', 'https://support.apple.com/en-me/guide/pages/tanc0ffef022/mac'),
    'chrome': ('Chrome shortcut reference', 'https://support.google.com/chrome/answer/157179'),
    'capture': ('Apple screenshot reference', 'https://support.apple.com/en-ie/102646'),
    'gnome': ('GNOME shortcut reference', 'https://help.gnome.org/gnome-help/shell-keyboard-shortcuts.html'),
    'project': ('MacLike mental model', 'https://github.com/mp-lb/gnome-maclike/blob/main/MENTAL_MODEL.md'),
}
STATUSES = {'mapped': 'Mapped', 'base': 'Uses app shortcut',
            'approximation': 'Approximation', 'planned': 'Planned',
            'not_planned': 'Not planned', 'native': 'Native / recovery'}
CATEGORIES = ('Apps and windows', 'Editing', 'Text navigation', 'Tabs and browsing',
              'Terminal', 'Files', 'Desktop and capture', 'Outside our scope', 'Recovery')


@dataclass(frozen=True)
class Shortcut:
    id: str
    keys: str
    action: str
    category: str
    status: str
    detail: str
    layer: str = 'command'
    source: str = 'apple'
    bindings: tuple = ()
    priority: str = 'Current'


def build_catalog():
    rows = []
    def add(id, keys, action, category, status, detail, layer='command', source='apple', bindings=(), priority='Current'):
        rows.append(Shortcut(id, keys, action, category, status, detail, layer, source, tuple(bindings), priority))

    switch = (('Hold the native app switcher until Command is released', 'Tab'),
              ('Cycle the native app switcher', 'Tab'))
    for suffix, keys, action in [('', 'Cmd+Tab', 'Switch apps'), ('-reverse', 'Cmd+Shift+Tab', 'Switch apps backward')]:
        add('switch-apps'+suffix, keys, action, 'Apps and windows', 'mapped',
            'Uses GNOME’s Super+Tab switcher. Hold Command to cycle; release it to choose. Depends on the native GNOME binding.',
            'desktop', bindings=switch)
    add('minimize-as-hide', 'Cmd+H', 'Hide / minimize', 'Apps and windows', 'approximation',
        'Minimizes the focused window using Super+H. It does not hide every window of an app as macOS Hide does.',
        'desktop', bindings=[('Command H minimizes the focused window', 'h')])
    add('quit', 'Cmd+Q', 'Quit app', 'Apps and windows', 'mapped',
        'Requests normal application quit through GNOME. Save dialogs may appear; some apps do not support the request.',
        'desktop', bindings=[('Command quit when desktop context is available', 'q')])
    add('lock', 'Control+Cmd+Q', 'Lock screen', 'Desktop and capture', 'mapped',
        'Calls GNOME’s lock service. Physical Control + the Command-position key + Q. This is lock, not sleep or logout.',
        'desktop', bindings=[('Control Command Q locks the screen', 'Ctrl-q'), ('Control Command Q locks the screen', 'Super_R-q')])
    add('overview', 'Control+↑', 'Window overview / Mission Control', 'Desktop and capture', 'mapped',
        'Opens GNOME’s native overview. Uses the physical Control key, including in standalone terminals. Control alone does not open overview. The original GNOME overlay setting is saved and restored by Stop or uninstall; a newer external edit is preserved.',
        'desktop', bindings=[('Control Up opens overview', 'Super_R-Up'), ('Control Up opens overview', 'Ctrl-Up')])
    add('show-desktop', 'Control+↓', 'Show / restore desktop', 'Desktop and capture', 'approximation',
        'Deliberate MacLike choice: Control+Up shows windows; Control+Down reveals the desktop. Press Down again with Control to restore the windows. Sends GNOME’s Super+D shortcut, including from standalone terminals and when no app is focused. macOS uses Control+Down for App Exposé instead. Requires the native Super+D Show Desktop binding.',
        'desktop', 'project', [('Control Down toggles desktop', 'Super_R-Down'), ('Control Down toggles desktop', 'Ctrl-Down')])
    add('app-expose', 'macOS Control+↓', 'Show current app windows', 'Apps and windows', 'not_planned',
        'MacLike deliberately assigns Control+Down to Show Desktop. Use Control+Up for the all-window overview; no filtered App Exposé is implemented.', 'desktop', 'apple', (), 'Not planned')

    # These are examples of the base translation, not per-application patches.
    for id, key, action in [('cut','X','Cut'), ('copy','C','Copy'), ('paste','V','Paste'),
                            ('undo','Z','Undo'), ('redo','Shift+Z','Redo'), ('select-all','A','Select all'),
                            ('find','F','Find'), ('find-next','G','Find next'), ('find-previous','Shift+G','Find previous'),
                            ('save','S','Save'), ('save-as','Shift+S','Save as'), ('open','O','Open'), ('print','P','Print')]:
        add(id, 'Cmd+'+key, action, 'Editing', 'base',
            'Sends Ctrl+'+key+'. The focused app decides what it means; not every app uses this convention. Recognized terminals have separate C/V rules.')
    for id, key, action in [('bold','B','Bold'), ('italic','I','Italic'), ('underline','U','Underline')]:
        add(id, 'Cmd+'+key, action, 'Editing', 'base',
            'Sends Ctrl+'+key+' in a text editor that supports it. Elsewhere this combination can mean something different.', source='text')
    add('app-defined', 'Cmd + an app shortcut', 'Other Control-based app actions', 'Editing', 'base',
        'Command holds Linux Control. App-defined Ctrl combinations inherit this unless a desktop, terminal or navigation rule overrides them. This is an open-ended family, not a promise of full macOS compatibility.', source='project')

    for direction, symbol, edge, target in [('Left','←','Line start','Home'), ('Right','→','Line end','End'),
                                           ('Up','↑','Document start','Ctrl+Home'), ('Down','↓','Document end','Ctrl+End')]:
        for shifted in (False, True):
            key = ('Shift-' if shifted else '') + direction
            add('text-'+direction.lower()+('-select' if shifted else ''),
                'Cmd+'+('Shift+' if shifted else '')+symbol,
                ('Select to ' + edge.lower()) if shifted else edge, 'Text navigation', 'mapped',
                'Sends '+('Shift+' if shifted else '')+target+'. The app interprets the destination; line edges are not necessarily the entire multiline input. Applies outside text fields too.',
                'navigation', 'text', [('Command text navigation', key)])
    for direction, symbol, word in [('Left','←','Previous word'), ('Right','→','Next word')]:
        for shifted in (False, True):
            add('word-'+direction.lower()+('-select' if shifted else ''),
                'Option+'+('Shift+' if shifted else '')+symbol,
                ('Select ' + word.lower()) if shifted else word, 'Text navigation', 'mapped',
                'Sends Ctrl+'+('Shift+' if shifted else '')+direction+'. Replaces the usual Alt-arrow browser history action while this layer applies.',
                'navigation', 'text', [('Option word navigation', 'Alt_L-'+('Shift-' if shifted else '')+direction)])

    for id, keys, action, target in [
        ('new-tab','T','New tab','Ctrl+T'), ('new-window','N','New window','Ctrl+N'),
        ('close-tab','W','Close tab / document','Ctrl+W'), ('close-window','Shift+W','Close window','Ctrl+Shift+W'),
        ('reopen-tab','Shift+T','Reopen closed tab','Ctrl+Shift+T'), ('private-window','Shift+N','Private window','Ctrl+Shift+N'),
        ('address','L','Address bar','Ctrl+L'), ('reload','R','Reload','Ctrl+R'),
        ('reload-bypass','Shift+R','Reload without cache','Ctrl+Shift+R'),
        ('zoom-in','+','Zoom in','Ctrl++'), ('zoom-out','-','Zoom out','Ctrl+-'), ('zoom-reset','0','Reset zoom','Ctrl+0')]:
        add(id, 'Cmd+'+keys, action, 'Tabs and browsing', 'base',
            'Sends '+target+'. Uses the browser’s Linux shortcut; other apps may differ. Terminal T/N/W have their own entries.', source='chrome')
    for suffix, shift, action in [('', '', 'Next browser tab'), ('-back', 'Shift+', 'Previous browser tab')]:
        add('control-tab'+suffix, 'Control+'+shift+'Tab', action, 'Tabs and browsing', 'mapped',
            'Physical Control in Chrome/Chromium: sends native Ctrl+Tab or Ctrl+Shift+Tab. Command+Tab still switches apps. App exclusions disable this exception. With Separate physical Control off, these work natively.',
            'control', 'chrome', [('Control Tab cycles browser tabs', 'Super_R-'+('Shift-' if shift else '')+'Tab')])
    for digit in range(1,10):
        add('tab-'+str(digit), 'Cmd+'+str(digit), 'Last tab' if digit==9 else 'Tab '+str(digit),
            'Tabs and browsing', 'base', 'Sends Ctrl+'+str(digit)+'. Uses the browser’s tab selection convention.', source='chrome')
    for id, keys, detail in [('open-link','Cmd+click','Ctrl-click opens a link in a background tab.'),
                             ('open-link-front','Cmd+Shift+click','Ctrl-Shift-click opens a link in a foreground tab.')]:
        add(id, keys, 'Open link in a new tab', 'Tabs and browsing', 'base',
            detail+' Uses a held Control modifier; no mouse interception. Other controls may interpret the click differently.', source='chrome')

    for id, key, action, target in [('copy','c','Copy','Ctrl+Shift+C'), ('paste','v','Paste','Ctrl+Shift+V'),
                                   ('tab','t','New terminal tab','Ctrl+Shift+T'), ('window','n','New terminal window','Ctrl+Shift+N'),
                                   ('close-tab','w','Close terminal tab','Ctrl+Shift+W'), ('close-window','Shift-w','Close terminal window','Ctrl+Shift+Q')]:
        add('terminal-'+id, 'Cmd+'+key.replace('Shift-', 'Shift+').upper().replace('SHIFT','Shift'), action,
            'Terminal', 'mapped', 'Sends '+target+' in recognized standalone terminals. Terminal bindings vary; embedded terminals follow their host app. Missing context disables this exception.',
            'terminal', 'project', [('Terminal copy and close', key)])
    for key, action in [('C','Interrupt'), ('D','End of input'), ('Z','Suspend'), ('L','Clear / redraw')]:
        add('terminal-control-'+key.lower(), 'Physical Control+'+key, action, 'Terminal', 'native',
            'Physical Control stays Control in recognized standalone terminals. The terminal, shell or program interprets it; raw-mode applications can differ.', 'control', 'project')

    def planned(id, keys, action, category, detail, priority='Next', source='apple'):
        add(id, keys, action, category, 'planned', 'Not mapped yet. '+detail, '', source, priority=priority)
    for suffix, shift, action in [('', '', 'Next window of this app'), ('-back', 'Shift+', 'Previous window of this app')]:
        key = 'Shift-Grave' if shift else 'Grave'
        add('cycle-window'+suffix, 'Cmd+'+shift+'`', action, 'Apps and windows', 'mapped',
            'Uses GNOME’s native same-app window switcher. Hold Command and tap the physical key above Tab to cycle; add Shift to reverse. Release Command to select. GNOME decides which windows belong to an app and workspace. Requires its Super+Above_Tab / Shift+Super+Above_Tab bindings.',
            'desktop', 'gnome', [('Open the native same-app window switcher', key), ('Cycle the native same-app window switcher', key)])
    planned('minimize','Cmd+M','Minimize window','Apps and windows','Reuse GNOME minimize; Command+H currently provides an approximation.')
    planned('launcher','Cmd+Space','Search / launcher','Desktop and capture','Prefer GNOME’s existing overview/search. Do not install a separate launcher or take over input-method shortcuts blindly.')
    add('delete-word','Option+Backspace','Delete previous word','Text navigation','mapped',
        'Sends native Ctrl+Backspace in known non-terminal apps. The app defines word boundaries. Standalone terminals keep Alt+Backspace for the shell to interpret; no terminal-specific deletion sequence is injected.',
        'navigation', 'text', [('Option word deletion', 'Alt_L-BackSpace')])
    add('delete-line','Cmd+Backspace','Delete to line start','Text navigation','mapped',
        'Chrome/Chromium and Codex (Chatgpt app): sends Ctrl+Shift+Backspace for native deletion to line start in text fields. Other apps and standalone terminals keep their existing behavior. A web app or browser-hosted terminal can intercept this shortcut. No selection macro or clipboard change.',
        'navigation', 'text', [('Command delete to line start', 'BackSpace')])
    planned('paste-style','Cmd+Option+Shift+V','Paste without source formatting','Editing','Choose a bounded convention; some apps already accept Cmd+Shift+V via the base swap.',source='text')
    for id, keys, action in [('capture-screen','Cmd+Shift+3','Capture screen'), ('capture-area','Cmd+Shift+4','Capture area'),
                              ('capture-window','Cmd+Shift+4, then Space','Capture window'), ('capture-ui','Cmd+Shift+5','Screenshot controls')]:
        planned(id,keys,action,'Desktop and capture','Reuse GNOME’s screenshot facilities; match the intent rather than duplicate Apple’s capture UI.',source='capture')
    for id,keys,action in [('capture-screen-clipboard','Control+Cmd+Shift+3','Capture screen to clipboard'),
                         ('capture-area-clipboard','Control+Cmd+Shift+4','Capture area to clipboard')]:
        planned(id,keys,action,'Desktop and capture','Clipboard behavior must be explicit; do not silently save a file instead.','Later','capture')
    planned('fullscreen','Control+Cmd+F','Fullscreen','Apps and windows','Desktop and app fullscreen differ. Choose and document one behavior.','Later')
    for id,keys,action in [('browser-next-tab','Cmd+Option+→','Next browser tab'), ('browser-prev-tab','Cmd+Option+←','Previous browser tab')]:
        planned(id,keys,action,'Tabs and browsing','Use a conventional tab action without confusing app switching or text navigation.','Later','chrome')
    planned('browser-back','Cmd+[','Browser back','Tabs and browsing','No dedicated translation today. Keep text-navigation arrows consistent.','Later','chrome')
    planned('browser-forward','Cmd+]','Browser forward','Tabs and browsing','No dedicated translation today.','Later','chrome')
    for id, keys, action, note in [
        ('files-parent','Cmd+↑','Parent folder','Currently collides with document navigation.'),
        ('files-open','Cmd+↓','Open selection','Currently collides with document navigation.'),
        ('files-hidden','Cmd+Shift+.','Hidden files','Would need a file-manager-scoped convention.'),
        ('files-location','Cmd+Shift+G','Go to folder','Would need a file-manager-scoped convention.'),
        ('files-rename','Return','Rename selection','Bare Return must not be intercepted globally.'),
        ('files-trash','Cmd+Backspace','Move to Trash','Must be scoped to file management; never globally translate into deletion.'),
        ('files-move','Cmd+Option+V','Move copied files','Finder’s copy-then-move workflow is not equivalent to blindly sending Linux paste.'),
        ('files-preview','Space','Quick Look','Do not claim a preview service is present or install one implicitly.')]:
        planned(id,keys,action,'Files',note+' Requires a deliberate Files policy before implementation.','Later')

    for id, keys, action, reason in [
        ('hide-others','Cmd+Option+H','Hide other apps','No general all-app hide model; keep the current window-only approximation explicit.'),
        ('minimize-all','Cmd+Option+M','Minimize all app windows','Avoid adding custom window bookkeeping for the first version.'),
        ('close-all','Cmd+Option+W','Close all app windows','No global bulk-close emulation; use the application’s own controls.'),
        ('force-quit','Cmd+Option+Esc','Force quit','Do not add a global process-killing shortcut; use GNOME’s process controls when needed.'),
        ('logout','Cmd+Shift+Q','Log out','Not a sleep shortcut. Keep session termination in GNOME’s system menu.'),
        ('logout-now','Cmd+Option+Shift+Q','Immediate logout','No confirmation-bypassing session termination.'),
        ('empty-trash','Cmd+Shift+Backspace','Empty Trash','No global bulk deletion shortcut.'),
        ('empty-trash-now','Cmd+Option+Shift+Backspace','Empty Trash immediately','No confirmation-bypassing deletion.'),
        ('sleep','Option+Cmd+Power','Sleep','Hardware and power-button semantics are outside this mapping set.'),
        ('restart','Control+Cmd+Power','Restart','Hardware and session termination are outside this mapping set.'),
        ('shutdown','Control+Option+Cmd+Power','Shut down','Use GNOME’s existing power controls.'),
        ('settings','Cmd+,','App preferences','There is no universal Linux counterpart; leave application behavior alone.'),
        ('lookup','Control+Cmd+D','Dictionary lookup','Would require a new service or widget integration.'),
        ('voiceover','Cmd+F5','VoiceOver','Preserve Linux accessibility controls rather than emulate Apple’s services.'),
        ('input-source','Control+Space','Input source switching','Preserve the user’s input method; do not reserve language-switching keys.'),
        ('quick-note','Fn+Q','Quick Note','Apple application integration is outside scope.'),
        ('siri','Cmd, Cmd','Siri','Do not emulate Apple-only services.'),
        ('touchbar','Cmd+Shift+6','Touch Bar capture','No corresponding hardware requirement for Ubuntu.')]:
        add(id,keys,action,'Outside our scope','not_planned',reason,'','capture' if id=='touchbar' else 'apple',priority='Excluded')
    add('stop','Physical Ctrl+Alt+Esc','Stop remapping','Recovery','native',
        'Emergency exit handled by Xremap, independent of the focused app. Physical Ctrl+Super+Esc is also accepted. With the Command layer off, Ctrl+Alt+Esc remains available.',
        'always','project',[(name,key) for name,keys in [
            ('Emergency stop with Command held',('Ctrl-Esc','Super_R-Esc')),
            ('Emergency stop with Option held',('Ctrl-Alt_L-Esc','Super_R-Alt_L-Esc'))] for key in keys])
    return tuple(sorted(rows,key=lambda row:CATEGORIES.index(row.category)))


CATALOG = build_catalog()


def normalize(text):
    for before, after in [('⌘','cmd'), ('command','cmd'), ('control','ctrl'), ('⇧','shift'), ('⌥','option'), ('alt','option'),
                          ('←','left'), ('→','right'), ('↑','up'), ('↓','down'), ('`','backtick'), ('+',' ')]:
        text = text.lower().replace(before, after)
    return text


def matching(query='', status='all'):
    words = normalize(query).split()
    return tuple(row for row in CATALOG if (status=='all' or row.status==status) and
                 all(word in normalize(' '.join((row.keys,row.action,row.category,row.detail,row.id,row.layer,
                                                STATUSES[row.status],row.priority))) for word in words))
