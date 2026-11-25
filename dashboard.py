"""Dashboard operations, kept separate from GTK and serialized by the installer."""
import hashlib
import json
from pathlib import Path
import subprocess

from control import APP_FILES, Install, engine_payload, preflight
from preferences import Appearance, read_preferences, save_preferences
from profiles import validate


def lifecycle(state=None, error=None, dirty=False, operation_error=None):
    """Presentation of a checked snapshot, never a claim of continuous monitoring."""
    def result(kind, title, message, action='', action_label='', banner=True):
        return dict(kind=kind, title=title, message=message, action=action,
                    action_label=action_label, banner=banner)
    if error:
        return result('unknown', 'Status unavailable', 'The check failed. Your existing changes may still be active. Retry the check or open Restore. ' + error, 'check', 'Retry check')
    if state is None:
        return result('unknown', 'Not checked', 'Existing changes may already be active. Check status to see what is running and load your saved choices.', 'check', 'Check status')
    if operation_error:
        return result('attention', 'Action incomplete', 'The last action did not finish. Recovery records were kept. Open Restore to review or retry. ' + operation_error, 'restore', 'Open Restore')
    if not state['installed']:
        return result('attention', 'Not installed', 'Install MacLike to start making changes with a saved restoration record.', 'install', 'Install')
    if state.get('problems'):
        return result('attention', 'Needs attention', ' '.join(state['problems']), 'restore', 'Open Restore')
    if state.get('update'):
        return result('attention', 'Update needed', 'This copy differs from the installed version. Review the replacement options before continuing.', 'install', 'Review update')
    if not state.get('adapter_ready', True):
        return result('attention', 'Keyboard unavailable', 'GNOME’s keyboard adapter is not available. After a first install, log out and back in, then check again. If you just unlocked, retry now. Dock and wallpaper controls remain available.', 'check', 'Retry check')
    if state.get('running') != state.get('bridge'):
        return result('attention', 'Keyboard interrupted', 'Part of the keyboard session stopped. Apply and restart to restore it, or use Stop keyboard changes in Restore.', 'apply', 'Apply and restart')
    if dirty or state.get('pending_keyboard'):
        return result('attention', 'Changes not applied', 'Your selected keyboard settings differ from the running session. Apply them to make them active.', 'apply', 'Apply changes')
    if not state.get('running') or not state['preferences']['layers']['command']:
        return result('off', 'Keyboard off', 'Native keyboard behavior is in use. Dock and wallpaper changes stay applied. Choose your layers and Apply and start when ready. Nothing starts automatically at login.', banner=False)
    return result('healthy', 'Active', 'Keyboard session and desktop adapter are running. Saved keyboard choices are applied; installed files and tracked desktop settings passed this check.', banner=False)


class Dashboard:
    def __init__(self, install=None, archive=None):
        self.install = install or Install()
        self.archive = archive

    def status(self):
        install = self.install
        present = install.record.exists()
        info = install.load() if present else None
        update = present and any(
            info['files'].get('app/' + name) != hashlib.sha256((install.source / name).read_bytes()).hexdigest()
            for name in APP_FILES if name != 'xremap')
        state = install.runtime.state()
        bridge = install.runtime.state(True)
        adapter_ready = False
        if present and hasattr(install.runtime, 'context'):
            try:
                adapter_ready = not install.runtime.context().get('locked', True)
            except (RuntimeError, subprocess.SubprocessError):
                pass
        prefs = read_preferences(install.record_dir)
        appearance = Appearance(install.record_dir)
        journal = appearance.load()
        problems = []
        pending_keyboard = False
        if present:
            install.audit.text()  # An unreadable recovery history must not look healthy.
            if (install.record_dir / 'staging').exists():
                problems.append('An installation update was interrupted. Keep the recovery record and finish the same update before starting again.')
            for name, digest in info['files'].items():
                path = install.path_for(name)
                if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    problems.append('An installed file is missing or modified. Review the saved record; modified files will be preserved during uninstall.')
                    break
            if any(appearance.desktop.read(path) != entry['after'] for path, entry in journal.items()):
                problems.append('A tracked desktop setting changed outside MacLike or was not fully applied. Restore preserves newer external values; review the saved record before reapplying.')
            if state.get('ActiveState') == 'active':
                try:
                    active = validate(json.loads((install.runtime.directory / 'preferences.json').read_text()))
                    pending_keyboard = any(active[key] != prefs[key] for key in ('keyboard', 'layers', 'excluded_apps'))
                except (OSError, ValueError):
                    problems.append('The running keyboard configuration could not be verified. Stop the session, then apply your saved choices again.')
        gallery_folder = prefs['wallpaper_folder'] or next((str(p) for p in
            (Path.home()/'Pictures/Wallpapers', Path.home()/'Downloads/wallpapers', Path.home()/'Downloads/wp') if p.is_dir()), '')
        return {'installed': present, 'update': bool(update), 'problems': problems,
                'gallery_folder': gallery_folder,
                'pending_keyboard': pending_keyboard,
                'running': state.get('ActiveState') == 'active',
                'bridge': bridge.get('ActiveState') == 'active',
                'adapter_ready': adapter_ready,
                'preferences': prefs, 'appearance': journal}

    def install_current(self):
        preflight()
        # Fetch/verify before removing anything. Failure leaves the old install intact.
        source = self.install.source
        if source == self.install.app:
            raise RuntimeError('Updates must be launched from the new source checkout.')
        payload = engine_payload(self.archive)
        if self.install.record.exists():
            self.install.uninstall()
        self.install.engine = payload
        self.install.install()
        return 'Installed. Choose your layers, then Apply and start. A first installation may need a logout/login.'

    def apply_keyboard(self, preferences):
        preferences = validate(preferences)
        preflight()
        if not self.install.record.exists():
            raise RuntimeError('Install GNOME MacLike first.')
        with self.install.operation():
            self.install.stop()
            save_preferences(self.install.record_dir, preferences)
        self.install.start()
        return 'Keyboard layers are running. Stop returns the keyboard to its original behavior.'

    def stop(self):
        with self.install.operation():
            self.install.stop()
        return 'Keyboard remapping stopped. Native key behavior is restored.'

    def appearance(self, action, value=None):
        if not self.install.record.exists():
            raise RuntimeError('Install GNOME MacLike first so changes have a recovery record.')
        with self.install.operation():
            appearance = Appearance(self.install.record_dir)
            if action == 'dock':
                appearance.dock()
            elif action == 'wallpaper':
                appearance.wallpaper(value)
            elif action in ('restore-dock', 'restore-wallpaper'):
                skipped = appearance.restore(action.removeprefix('restore-'))
                if skipped:
                    return 'Restored our changes; preserved newer changes made outside GNOME MacLike.'
            else:
                raise ValueError('Unknown appearance action.')
        return 'Desktop setting updated. Its original value is saved for restoration.'

    def save_folder(self, folder):
        # Browsing the source preview must not add files to a legacy installation.
        if self.install.record.exists() and not self.status()['update']:
            with self.install.operation():
                prefs = read_preferences(self.install.record_dir)
                prefs['wallpaper_folder'] = str(folder)
                save_preferences(self.install.record_dir, prefs)

    def restore(self):
        with self.install.operation():
            self.install.stop()
            skipped = Appearance(self.install.record_dir).restore()
        return ('Keyboard stopped and managed appearance restored.' +
                (' Newer external changes were preserved.' if skipped else ''))

    def uninstall(self, audit_export=None):
        self.install.uninstall(audit_export=audit_export)
        return 'Uninstalled. Keyboard stopped, managed desktop changes restored, owned files removed.'

    def history(self):
        text = self.install.audit.text()
        return text or 'No audit history yet. Activity before this version was not logged.'

    def export_history(self, target):
        with self.install.operation():
            self.install.audit.export(target)
        return 'Audit history exported. This copy is yours to keep after uninstall.'

    def details(self):
        install = self.install
        if not install.record.exists():
            return 'Not installed. No desktop settings have been changed by this dashboard.'
        info = install.load()
        lines = ['Installed files', *[str(install.path_for(label)) for label in sorted(info['files'])],
                 '', 'Recovery and choices', str(install.record),
                 str(install.record_dir / 'preferences.json'), str(install.record_dir / 'appearance.json'),
                 '', 'Original GNOME extension settings', json.dumps(info['desktop'], indent=2),
                 '', 'Appearance changes (before → applied)', json.dumps(Appearance(install.record_dir).load(), indent=2),
                 '', 'Runtime only', install.runtime.unit, install.runtime.bridge_unit, str(install.runtime.directory)]
        return '\n'.join(lines)
