#!/usr/bin/python3
"""A native, optional dashboard. The window does not handle keyboard events."""
import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime
from pathlib import Path
import sys
import subprocess
import threading

sys.dont_write_bytecode = True
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

from dashboard import Dashboard, lifecycle
from profiles import DEFAULTS, LAYERS
from shortcuts import CATALOG, CATEGORIES, SOURCES, STATUSES, matching

CHROME = ('google-chrome', 'Google-chrome', 'chromium', 'Chromium',
          'chromium-browser', 'chromium_chromium', 'org.chromium.Chromium')


def label(text, css=None):
    widget = Gtk.Label(label=text, xalign=0, wrap=True)
    if css:
        widget.add_css_class(css)
    return widget


def button(title, callback, style=None):
    widget = Gtk.Button(label=title)
    if style:
        widget.add_css_class(style)
    widget.connect('clicked', lambda *_: callback())
    return widget


class Window(Adw.ApplicationWindow):
    def __init__(self, application, backend):
        super().__init__(application=application, title='GNOME MacLike', default_width=980, default_height=800)
        self.backend = backend
        self.busy = False
        self.loaded = False
        self.state = {}
        self.checked_at = None
        self.check_error = None
        self.operation_error = None
        self.loading_preferences = False
        self.recovery_controls = []
        self.switches = {}
        self.guarded = []
        self.preview_folder = None
        self.refreshing = False
        self.gallery_loading = False
        self.gallery_generation = 0
        self.gallery_job = None
        self.images = ThreadPoolExecutor(max_workers=1, thread_name_prefix='wallpapers')
        self.image_cache = OrderedDict()  # Worker-only, bounded, memory-only thumbnails.
        self.connect('close-request', self.close_requested)
        self.toast = Adw.ToastOverlay()
        self.set_content(self.toast)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class('background')
        self.toast.set_child(root)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title='GNOME MacLike', subtitle='Your desktop, with a familiar feel'))
        self.health_box = Gtk.Box(spacing=6)
        self.health_icon = Gtk.Image(icon_name='dialog-question-symbolic')
        self.health_label = Gtk.Label(label='Not checked')
        self.health_box.append(self.health_icon)
        self.health_box.append(self.health_label)
        header.pack_start(self.health_box)
        root.append(header)
        self.banner = Adw.Banner()
        root.append(self.banner)
        self.banner.set_revealed(True)
        self.banner.connect('button-clicked', lambda *_: self.status_action())
        self.stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(8)
        switcher.set_margin_bottom(8)
        root.append(switcher)
        root.append(self.stack)
        self.stack.set_vexpand(True)
        self.keyboard_page()
        self.shortcuts_page()
        self.wallpaper_page()
        self.dock_page()
        self.restore_page()
        for row in self.switches.values():
            row.connect('notify::active', lambda *_: self.selection_changed())
        self.hardware.connect('notify::selected', lambda *_: self.selection_changed())
        self.chrome.connect('notify::active', lambda *_: self.selection_changed())
        self.exclusions.connect('changed', lambda *_: self.selection_changed())
        self.render_status()
        self.sensitivity()

    def close_requested(self, *_):
        if self.busy:
            self.toast.add_toast(Adw.Toast(title='Wait for the current operation to finish, or cancel its authentication prompt.'))
            return True
        self.gallery_generation += 1
        self.images.shutdown(wait=False, cancel_futures=True)
        return False

    def page(self, title, icon, subtitle):
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        content.set_margin_top(24)
        content.set_margin_bottom(28)
        content.set_margin_start(26)
        content.set_margin_end(26)
        heading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        heading.append(label(title, 'title-1'))
        heading.append(label(subtitle, 'dim-label'))
        content.append(heading)
        clamp = Adw.Clamp(maximum_size=900, tightening_threshold=750)
        clamp.set_child(content)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=clamp)
        self.stack.add_titled_with_icon(scroll, title.lower(), title, icon)
        return content

    def group(self, page, title, description=None):
        group = Adw.PreferencesGroup(title=title)
        if description:
            group.set_description(description)
        page.append(group)
        return group

    def action_row(self, group, title, subtitle, action, callback, style=None, managed=True):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        row.set_subtitle_lines(0)
        control = button(action, callback, style)
        control.set_valign(Gtk.Align.CENTER)
        row.add_suffix(control)
        group.add(row)
        if managed:
            self.guarded.append(control)
        return control

    def keyboard_page(self):
        page = self.page('Keyboard', 'input-keyboard-symbolic',
                         'Enable once. Your keyboard choices stay on across logins until you Disable.')
        group = self.group(page, 'Keyboard preference')
        self.status_row = Adw.ActionRow(title='Not checked', subtitle='Doctor checks whether your enabled preference is working.')
        self.apply_button = button('Enable', self.apply_keyboard, 'suggested-action')
        self.stop_button = button('Disable', lambda: self.work(self.backend.stop))
        for control in (self.stop_button, self.apply_button):
            control.set_valign(Gtk.Align.CENTER)
            self.status_row.add_suffix(control)
            self.guarded.append(control)
        group.add(self.status_row)
        self.hardware = Adw.ComboRow(title='Keyboard layout', model=Gtk.StringList.new(['PC keyboard', 'Apple keyboard']))
        self.hardware.set_subtitle('On PC keyboards, left Alt is Command and left Super is Option.')
        group.add(self.hardware)
        group = self.group(page, 'Mapping layers', 'Choose your layers, then Enable or Save changes.')
        for key, (title, subtitle) in LAYERS.items():
            row = Adw.SwitchRow(title=title, subtitle=subtitle, active=True)
            row.set_subtitle_lines(0)
            self.switches[key] = row
            group.add(row)
        self.switches['command'].connect('notify::active', lambda *_: self.layer_sensitivity())
        group = self.group(page, 'Application exceptions',
                           'Keep the base modifier swap, but skip terminal, desktop and text-navigation shortcuts in these apps.')
        self.exclusions = Adw.EntryRow(title='Application names, separated by commas')
        group.add(self.exclusions)
        self.chrome = Adw.SwitchRow(title='Use only the base swap in Chrome / Chromium',
                                    subtitle='Skips optional shortcuts, including delete to line start.')
        group.add(self.chrome)
        page.append(label('Text navigation: Command-←/→ goes to line edges; Command-↑/↓ to document edges; '
                          'Option-←/→ moves by words. Add Shift to select. These mappings also apply outside '
                          'text fields and replace Option-arrow browser navigation. Embedded terminals follow '
                          'their host app, not the standalone-terminal rule.', 'dim-label'))

    def layer_sensitivity(self):
        enabled = self.loaded and self.state.get('installed') and not self.state.get('update') and not self.state.get('problems') and not self.check_error and not self.busy and not self.refreshing
        active = self.switches['command'].get_active() and enabled
        self.switches['command'].set_sensitive(enabled)
        for key, row in self.switches.items():
            if key != 'command':
                row.set_sensitive(active)

    def selected(self):
        prefs = copy.deepcopy(self.state.get('preferences', DEFAULTS))
        prefs['keyboard'] = 'apple' if self.hardware.get_selected() == 1 else 'pc'
        prefs['layers'] = {key: row.get_active() for key, row in self.switches.items()}
        names = [name.strip() for name in self.exclusions.get_text().split(',') if name.strip()]
        if self.chrome.get_active():
            names.extend(CHROME)
        prefs['excluded_apps'] = list(dict.fromkeys(names))
        if self.preview_folder:
            prefs['wallpaper_folder'] = str(self.preview_folder)
        return prefs

    def apply_keyboard(self):
        prefs = self.selected()
        self.work(lambda: self.backend.apply_keyboard(prefs))

    def shortcuts_page(self):
        page = self.page('Shortcuts', 'input-keyboard-symbolic',
                         'Every explicit MacLike mapping, common app shortcuts, and the additions we have considered.')
        page.append(label('Command is left Alt on a PC keyboard, or left Super on an Apple keyboard. '
                          'Option is left Super on a PC keyboard. Backspace means the Mac key labelled Delete.', 'dim-label'))
        toolbar = Gtk.Box(spacing=12)
        self.shortcut_search = Gtk.SearchEntry(placeholder_text='Search an action or keys, e.g. copy or command left', hexpand=True)
        self.shortcut_filter_keys = ['all', *STATUSES]
        self.shortcut_filter = Gtk.DropDown(model=Gtk.StringList.new(['All decisions', *STATUSES.values()]))
        self.shortcut_filter.set_tooltip_text('Filter by implementation status')
        self.shortcut_filter.update_property([Gtk.AccessibleProperty.LABEL], ['Shortcut implementation status'])
        toolbar.append(self.shortcut_search)
        toolbar.append(self.shortcut_filter)
        page.append(toolbar)
        self.shortcut_count = label('', 'dim-label')
        page.append(self.shortcut_count)
        page.append(label('Mapped entries need a running session, enabled layers and no app exclusion. '
                          'Plans are not active mappings; those keys may still reach apps through the base swap.', 'dim-label'))
        self.shortcut_rows = {}
        self.shortcut_groups = {}
        for category in CATEGORIES:
            group = self.group(page, category)
            self.shortcut_groups[category] = group
            for item in (row for row in CATALOG if row.category == category):
                row = Adw.ExpanderRow(title=item.action, subtitle=item.keys)
                row.set_use_markup(False)
                badge = Gtk.Label(label=STATUSES[item.status], valign=Gtk.Align.CENTER)
                badge.add_css_class('dim-label')
                row.add_suffix(badge)
                details = Adw.ActionRow(title='Behavior and scope', subtitle=item.detail)
                details.set_use_markup(False)
                details.set_subtitle_lines(0)
                row.add_row(details)
                layer = LAYERS[item.layer][0] if item.layer in LAYERS else ('Always available while remapping' if item.layer == 'always' else 'No mapping layer yet')
                decision = Adw.ActionRow(title=layer, subtitle=f'{item.priority} · Reference ID: {item.id}')
                decision.set_use_markup(False)
                title, url = SOURCES[item.source]
                source = Gtk.LinkButton(uri=url, label='Reference', valign=Gtk.Align.CENTER)
                source.set_tooltip_text(title)
                decision.add_suffix(source)
                row.add_row(decision)
                group.add(row)
                self.shortcut_rows[item.id] = row
        self.shortcut_empty = label('No matching shortcuts. Try another search or choose All decisions.', 'dim-label')
        page.append(self.shortcut_empty)
        self.shortcut_search.connect('search-changed', lambda *_: self.filter_shortcuts())
        self.shortcut_filter.connect('notify::selected', lambda *_: self.filter_shortcuts())
        self.filter_shortcuts()

    def filter_shortcuts(self):
        status = self.shortcut_filter_keys[self.shortcut_filter.get_selected()]
        found = matching(self.shortcut_search.get_text(), status)
        ids = {row.id for row in found}
        categories = {row.category for row in found}
        for id, row in self.shortcut_rows.items():
            row.set_visible(id in ids)
        for category, group in self.shortcut_groups.items():
            group.set_visible(category in categories)
        self.shortcut_count.set_text(f'{len(found)} of {len(CATALOG)} entries · Implementation status, not live activation')
        self.shortcut_empty.set_visible(not found)

    def wallpaper_page(self):
        page = self.page('Wallpapers', 'preferences-desktop-wallpaper-symbolic',
                         'Your own collection. Images stay in their original folder and are never bundled or uploaded.')
        toolbar = Gtk.Box(spacing=12)
        toolbar.append(button('Choose folder…', self.choose_folder))
        toolbar.append(button('Restore previous wallpaper', lambda: self.work(lambda: self.backend.appearance('restore-wallpaper'))))
        self.guarded.append(toolbar.get_last_child())
        self.fivek = Gtk.CheckButton(label='5K landscape only', active=True)
        self.fivek.connect('toggled', lambda *_: self.load_gallery())
        toolbar.append(self.fivek)
        page.append(toolbar)
        self.gallery_label = label('Choose a folder to browse wallpapers.', 'dim-label')
        page.append(self.gallery_label)
        self.gallery = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                   min_children_per_line=3, max_children_per_line=3, row_spacing=16, column_spacing=16)
        css = Gtk.CssProvider()
        css.load_from_string('.wallpaper-tile { padding: 0; border-radius: 12px; }')
        Gtk.StyleContext.add_provider_for_display(self.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        page.append(self.gallery)

    def choose_folder(self):
        chooser = Gtk.FileChooserNative(title='Choose a wallpaper folder', transient_for=self,
                                         action=Gtk.FileChooserAction.SELECT_FOLDER, accept_label='Choose')
        def selected(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                self.preview_folder = Path(dialog.get_file().get_path())
                self.load_gallery()
                self.work(lambda: self.backend.save_folder(self.preview_folder), quiet=True)
            dialog.destroy()
        chooser.connect('response', selected)
        chooser.show()

    def load_gallery(self):
        # Snapshot GTK state here; directory reads and image decoding never run
        # on the GTK thread. One worker and a generation token bound rapid toggles.
        self.gallery_generation += 1
        generation = self.gallery_generation
        if self.gallery_job:
            self.gallery_job.cancel()
        child = self.gallery.get_first_child()
        while child:
            following = child.get_next_sibling()
            self.gallery.remove(child)
            child = following
        folder = self.preview_folder
        if not folder:
            self.gallery_loading = False
            self.gallery_label.set_text('Choose a folder to browse wallpapers. No image files are copied.')
            return
        fivek = self.fivek.get_active()
        self.gallery_loading = True
        self.gallery_label.set_text(f'{folder}\nLoading images…')

        def add_tile(path, width, height, pixbuf):
            if generation != self.gallery_generation:
                return False
            picture = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
            picture.set_content_fit(Gtk.ContentFit.COVER)
            picture.set_can_shrink(True)
            frame = Gtk.AspectFrame(ratio=1.6, obey_child=False, child=picture)
            frame.set_size_request(210, 135)
            tile = Gtk.Button(child=frame)
            tile.add_css_class('card')
            tile.add_css_class('wallpaper-tile')
            tile.set_overflow(Gtk.Overflow.HIDDEN)
            tile.set_tooltip_text(f'{path.name}\nClick to preview and see details')
            tile.update_property([Gtk.AccessibleProperty.LABEL], [f'Preview {path.name}'])
            tile.connect('clicked', lambda _: self.preview_wallpaper(path, width, height, pixbuf))
            self.gallery.append(tile)
            return False

        def done(count, below, skipped, error):
            if generation != self.gallery_generation:
                return False
            self.gallery_loading = False
            text = (f'{folder}\n{count} images shown' +
                    (f' · {below} below the 5K landscape filter' if below else '') +
                    (f' · {skipped} unreadable or oversized' if skipped else ''))
            self.gallery_label.set_text(f'Could not load folder: {error}' if error else text)
            return False

        def worker():
            count = below = skipped = 0
            error = None
            try:
                candidates = sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'))[:200]
                for path in candidates:
                    if generation != self.gallery_generation:
                        return
                    try:
                        stat = path.stat()
                        key = (str(path), stat.st_mtime_ns, stat.st_size)
                        cached = self.image_cache.get(key)
                        if cached:
                            width, height, pixbuf = cached
                            self.image_cache.move_to_end(key)
                        else:
                            fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
                            if not fmt or width * height > 200_000_000:
                                skipped += 1
                                continue
                        if fivek and not (width >= 5120 and height >= 2880 and width >= height):
                            below += 1
                            continue
                        if not cached:
                            # Reuse this scaled image in the preview too: never
                            # decode a full-resolution original when opening it.
                            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 650, 400, True)
                            self.image_cache[key] = (width, height, pixbuf)
                            if len(self.image_cache) > 64:
                                self.image_cache.popitem(last=False)
                    except (GLib.Error, TypeError, OSError):
                        skipped += 1
                        continue
                    if generation != self.gallery_generation:
                        return
                    GLib.idle_add(add_tile, path, width, height, pixbuf)
                    count += 1
            except Exception as exc:
                error = str(exc)
            GLib.idle_add(done, count, below, skipped, error)
        self.gallery_job = self.images.submit(worker)

    def preview_wallpaper(self, path, width, height, pixbuf):
        dialog = Adw.AlertDialog(heading='Use this wallpaper?', body=f'{path.name}\n{width:,} × {height:,}')
        dialog.set_extra_child(Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pixbuf)))
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('apply', 'Set wallpaper' if self.state.get('enabled') else 'Save wallpaper choice')
        dialog.set_response_appearance('apply', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled('apply', bool(self.state.get('installed')) and not self.state.get('update') and not self.busy)
        dialog.connect('response', lambda _, response: self.work(lambda: self.backend.appearance('wallpaper', path)) if response == 'apply' else None)
        dialog.present(self)

    def dock_page(self):
        page = self.page('Dock', 'view-grid-symbolic', 'Familiar placement, with a distinctly Linux panel.')
        preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        preview.add_css_class('card')
        preview.set_margin_top(6)
        preview.append(Gtk.Label(label='Desktop', vexpand=True, height_request=130))
        bar = Gtk.Box(spacing=16, halign=Gtk.Align.CENTER, margin_top=16, margin_bottom=16)
        for icon in ('system-file-manager-symbolic', 'web-browser-symbolic', 'utilities-terminal-symbolic', 'view-app-grid-symbolic'):
            bar.append(Gtk.Image(icon_name=icon, pixel_size=28))
        preview.append(Gtk.Separator())
        preview.append(bar)
        page.append(preview)
        group = self.group(page, 'Bottom panel', 'Uses the existing Ubuntu Dock / Dash to Dock extension. No new extension is installed.')
        self.action_row(group, 'Bottom, full width, centered icons',
                        'Changes four settings. Icon size, pinned apps and other preferences stay as they are.',
                        'Apply panel', lambda: self.work(lambda: self.backend.appearance('dock')), 'suggested-action')
        self.action_row(group, 'Restore previous dock', 'Restores the values saved before this app first changed them.',
                        'Restore', lambda: self.work(lambda: self.backend.appearance('restore-dock')))
        self.dock_status = label('No dock changes recorded.', 'dim-label')
        page.append(self.dock_status)

    def restore_page(self):
        page = self.page('Doctor', 'applications-engineering-symbolic', 'Check your setup, inspect its history, or remove it completely.')
        group = self.group(page, 'Your exit routes')
        self.recovery_controls.append(self.action_row(group, 'Disable MacLike', 'Restores keyboard, dock and wallpaper settings and keeps automatic startup off. Your MacLike choices are saved for the next Enable.',
                        'Disable', lambda: self.work(self.backend.stop), managed=False))
        self.recovery_controls.append(self.action_row(group, 'Uninstall GNOME MacLike', 'Disables startup, removes the system integration, restores managed settings and removes installed files and saved choices. Your wallpaper images stay untouched.',
                        'Uninstall', self.uninstall_clicked, 'destructive-action', managed=False))
        page.append(label('Restoration means your values from before this app changed them—not factory defaults. '
                          'If you change a managed setting elsewhere, its newer value is preserved. '
                          'Modified installation files and unknown files block removal instead of being deleted. '
                          'If authentication or cleanup fails, recovery records remain so you can retry.', 'dim-label'))
        group = self.group(page, 'Troubleshooting')
        self.check_button = self.action_row(group, 'Run Doctor',
                        'Use this if something seems wrong or you changed settings outside MacLike. It only reads the current state; periodic checks are not needed.',
                        'Run Doctor', self.refresh, managed=False)
        group = self.group(page, 'Footprint and recovery record')
        self.action_row(group, 'Inspect the saved record', 'Exact installed paths, original settings and managed appearance values.',
                        'View details', self.show_details, managed=False)
        self.action_row(group, 'Change history', 'Timestamped intent and observed results, including original and new values. Earlier versions did not record a full history.',
                        'View history', lambda: self.show_details(history=True), managed=False)
        self.action_row(group, 'Keep a copy of the history', 'Exports a private local JSON Lines file. Normal uninstall removes the app’s internal log.',
                        'Export…', self.export_history, managed=False)
        page.append(label('Enable installs a tracked login hook and a protected keyboard service. First setup and '
                          'removal need administrator authentication; normal logins do not. Disable removes the login hook. '
                          'Uninstall removes the system integration too. Closing this window keeps your preference. '
                          'Physical Ctrl+Alt+Esc stops this session without automatically restarting it.', 'dim-label'))
        group = self.group(page, 'If this window will not open',
                           'Physical Ctrl+Alt+Esc stops the remapper. To restore settings and uninstall afterward, run this in a normal terminal. Ubuntu may request authentication.')
        app_path = getattr(getattr(self.backend, 'install', None), 'app', Path.home()/'.local/share/gnome-maclike')
        import shlex
        command = label('python3 -B ' + shlex.quote(str(app_path/'control.py')) + ' uninstall', 'monospace')
        command.set_selectable(True)
        group.add(command)

    def show_details(self, history=False):
        dialog = Adw.AlertDialog(heading='Change history' if history else 'Installation and restoration record')
        view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text('Reading recovery record…')
        def worker():
            try:
                text = self.backend.history() if history else self.backend.details()
            except Exception as exc:
                text = str(exc)
            GLib.idle_add(view.get_buffer().set_text, text)
        threading.Thread(target=worker, daemon=True).start()
        scroll = Gtk.ScrolledWindow(child=view, min_content_height=320, min_content_width=560)
        dialog.set_extra_child(scroll)
        dialog.add_response('close', 'Close')
        dialog.present(self)

    def export_history(self, uninstall=False):
        chooser = Gtk.FileChooserNative(title='Save uninstall history' if uninstall else 'Export change history',
                                         transient_for=self, action=Gtk.FileChooserAction.SAVE,
                                         accept_label='Uninstall and save' if uninstall else 'Export')
        chooser.set_current_name('maclike-uninstall.jsonl' if uninstall else 'maclike-history.jsonl')
        def selected(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                path = Path(dialog.get_file().get_path())
                action = (lambda: self.backend.uninstall(audit_export=path)) if uninstall else (lambda: self.backend.export_history(path))
                self.work(action)
            dialog.destroy()
        chooser.connect('response', selected)
        chooser.show()

    def uninstall_clicked(self):
        dialog = Adw.AlertDialog(heading='Uninstall GNOME MacLike?',
            body='Restore managed changes and remove installed files, choices and the internal log. You can save a history file that includes the uninstall result.')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('export', 'Save history and uninstall…')
        dialog.add_response('remove', 'Uninstall without a copy')
        dialog.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        def selected(_, response):
            if response == 'export':
                self.export_history(uninstall=True)
            elif response == 'remove':
                self.work(self.backend.uninstall)
        dialog.connect('response', selected)
        dialog.present(self)

    def confirm(self, title, body, action):
        dialog = Adw.AlertDialog(heading=title, body=body)
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('confirm', 'Continue')
        dialog.set_response_appearance('confirm', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect('response', lambda _, response: self.work(action) if response == 'confirm' else None)
        dialog.present(self)

    def install_clicked(self):
        if self.state.get('installed'):
            self.confirm('Replace the installed version?',
                         'This stops the old session, restores its managed desktop settings, then installs this version. Saved layer choices reset. Nothing starts until you apply it.',
                         self.backend.install_current)
        else:
            self.work(self.backend.install_current)

    def work(self, action, quiet=False):
        if self.busy or self.refreshing:
            return
        self.busy = True
        self.operation_error = None
        self.sensitivity()
        self.render_status()
        def worker():
            try:
                result, error = action(), None
            except Exception as exc:
                result, error = None, str(exc)
                if isinstance(exc, subprocess.CalledProcessError) and exc.cmd and Path(exc.cmd[0]).name == 'pkexec':
                    error = ('Administrator authentication was cancelled or declined.' if exc.returncode == 126 else
                             'Desktop authentication could not start. Open GNOME MacLike from your applications menu or a normal terminal.')
            GLib.idle_add(done, result, error)
        def done(result, error):
            self.busy = False
            self.operation_error = error
            if error:
                dialog = Adw.AlertDialog(heading='The operation did not finish', body=error + '\n\nNo further steps were run. Any existing recovery record has been kept so you can retry.')
                dialog.add_response('close', 'Close')
                dialog.present(self)
            elif result and not quiet:
                self.toast.add_toast(Adw.Toast(title=result, timeout=8))
            if result and result.startswith('Uninstalled.') and self.backend.install.source == self.backend.install.app:
                self.close()
            else:
                self.refresh(clear_operation_error=False)
        threading.Thread(target=worker, daemon=True).start()

    def selection_changed(self):
        if self.loaded and not self.loading_preferences:
            self.render_status()

    def render_status(self):
        dirty = self.loaded and any(self.selected()[key] != self.state.get('preferences', DEFAULTS)[key]
                                   for key in ('keyboard', 'layers', 'excluded_apps'))
        self.lifecycle = lifecycle(self.state if self.checked_at else None, self.check_error,
                                   dirty, self.operation_error)
        applied = (self.checked_at and not self.check_error and self.state.get('running')
                   and self.state.get('bridge') and self.state.get('adapter_ready', True)
                   and not self.state.get('pending_keyboard') and not dirty
                   and not self.state.get('problems') and not self.state.get('update'))
        self.apply_button.set_label('Save changes' if dirty and self.state.get('enabled') else 'Enable')
        self.apply_button.set_visible(not (applied and self.state.get('enabled')))
        if applied:
            self.apply_button.remove_css_class('suggested-action')
        else:
            self.apply_button.add_css_class('suggested-action')
        info = self.lifecycle
        if self.busy or self.refreshing:
            info = dict(kind='unknown', title='Working…' if self.busy else 'Checking…', banner=False,
                        message='Ubuntu may request authentication.' if self.busy else 'Reading the current state. You can keep browsing.')
        icons = {'healthy': 'emblem-ok-symbolic', 'unknown': 'dialog-question-symbolic',
                 'attention': 'dialog-warning-symbolic', 'off': 'media-playback-pause-symbolic'}
        self.health_icon.set_from_icon_name(icons[info['kind']])
        self.health_label.set_text(info['title'])
        for css in ('success', 'warning', 'dim-label'):
            self.health_icon.remove_css_class(css)
        self.health_icon.add_css_class({'healthy': 'success', 'attention': 'warning'}.get(info['kind'], 'dim-label'))
        checked = f'Last checked at {self.checked_at}. For troubleshooting, run Doctor. Periodic checks are not needed.' if self.checked_at else 'No successful check in this window yet.'
        self.health_box.set_tooltip_text(info['message'] + '\n\n' + checked)
        self.banner.set_title(info['message'])
        self.banner.set_button_label(info.get('action_label', ''))
        self.banner.set_revealed(info['banner'])
        self.status_row.set_title(info['title'])
        self.status_row.set_subtitle(info['message'] + (' Last checked at ' + self.checked_at + '.' if self.checked_at and not self.busy and not self.refreshing else ''))

    def status_action(self):
        action = self.lifecycle.get('action')
        if action == 'check':
            self.refresh()
        elif action == 'install':
            self.install_clicked()
        elif action == 'apply':
            self.apply_keyboard()
        elif action == 'restore':
            self.stack.set_visible_child_name('doctor')

    def sensitivity(self):
        idle = not self.busy and not self.refreshing
        enabled = bool(self.state.get('installed')) and not self.state.get('update') and not self.state.get('problems') and not self.check_error and idle
        for control in self.guarded:
            control.set_sensitive(enabled)
        self.apply_button.set_sensitive(bool(self.state.get('installed')) and not self.state.get('update')
                                        and self.state.get('can_enable', not self.state.get('problems'))
                                        and not self.check_error and idle)
        self.stop_button.set_sensitive(idle and (bool(self.state.get('enabled')) or bool(self.state.get('running')) or bool(self.state.get('bridge')) or bool(self.state.get('appearance')) or self.check_error is not None))
        for control in self.recovery_controls:
            control.set_sensitive(idle)
        self.hardware.set_sensitive(enabled)
        self.exclusions.set_sensitive(enabled)
        self.chrome.set_sensitive(enabled)
        self.layer_sensitivity()
        self.banner.set_sensitive(idle)
        self.check_button.set_sensitive(idle)

    def refresh(self, clear_operation_error=True):
        # systemctl and file reads run off the GTK event loop.
        if self.refreshing or self.busy:
            return
        self.refreshing = True
        if clear_operation_error:
            self.operation_error = None
        self.check_button.set_label('Checking…')
        self.render_status()
        self.sensitivity()
        def worker():
            try:
                state, error = self.backend.status(), None
            except Exception as exc:
                state, error = {}, str(exc)
            GLib.idle_add(done, state, error)
        def done(state, error):
            self.refreshing = False
            self.check_button.set_label('Run Doctor')
            if self.busy:
                return
            self.check_error = error
            self.checked_at = datetime.now().strftime('%H:%M:%S') if not error else None
            if not error:
                self.state = state
            if not self.loaded and not error:
                self.loading_preferences = True
                prefs = state.get('preferences', DEFAULTS)
                self.hardware.set_selected(1 if prefs['keyboard'] == 'apple' else 0)
                for key, row in self.switches.items():
                    row.set_active(prefs['layers'][key])
                self.exclusions.set_text(', '.join(name for name in prefs['excluded_apps'] if name not in CHROME))
                self.chrome.set_active(any(name in CHROME for name in prefs['excluded_apps']))
                self.layer_sensitivity()
                folder = prefs['wallpaper_folder']
                if not folder:
                    folder = state.get('gallery_folder', '')
                self.preview_folder = self.preview_folder or (Path(folder) if folder else None)
                self.load_gallery()
                self.loaded = True
                self.loading_preferences = False
            count = sum('dash-to-dock' in p for p in state.get('appearance', {}))
            self.dock_status.set_text(f'{count} dock settings saved for restoration.' if count else 'No dock changes recorded by this app.')
            self.render_status()
            self.sensitivity()
        threading.Thread(target=worker, daemon=True).start()


class Application(Adw.Application):
    def __init__(self, backend):
        super().__init__(application_id='dev.mplb.GnomeMacLike', flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.backend = backend

    def do_activate(self):
        window = self.get_active_window()
        if not window:
            window = Window(self, self.backend)
        window.present()



def main():
    parser = argparse.ArgumentParser(description='GNOME MacLike desktop dashboard')
    parser.add_argument('--archive', type=Path, help='Verified Xremap release archive for offline installation')
    args = parser.parse_args()
    return Application(Dashboard(archive=args.archive)).run([])


if __name__ == '__main__':
    raise SystemExit(main())
