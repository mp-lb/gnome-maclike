"""Audited, optional login integration with a closed, removable footprint."""
import hashlib
import errno
import json
import os
from pathlib import Path
import subprocess
import tempfile

from preferences import read_json, audited_json
from runtime import run
from system_setup import paths

NAME = 'startup.json'
UNIT = 'gnome-maclike-session.service'


class Startup:
    def __init__(self, install, config=None):
        self.install = install
        self.config = Path(config or install.config)
        self.paths = {'login': self.config/'autostart/gnome-maclike.desktop',
                      'session': self.config/'systemd/user'/UNIT}
        self.record = install.record_dir/NAME
        self.uid = os.getuid()

    def load(self):
        value = read_json(self.record, {'enabled': False, 'system': False, 'files': {}, 'dirs': []})
        if (not isinstance(value, dict) or set(value) != {'enabled', 'system', 'files', 'dirs'}
                or type(value['enabled']) is not bool or type(value['system']) is not bool
                or not isinstance(value['files'], dict) or not set(value['files']) <= set(self.paths)):
            raise ValueError('Invalid startup recovery record; preserved.')
        allowed_dirs = {str(p) for path in self.paths.values() for p in path.parents if p == self.config or p.is_relative_to(self.config)}
        if not isinstance(value['dirs'], list) or not set(value['dirs']) <= allowed_dirs:
            raise ValueError('Invalid startup directory record.')
        if any(not isinstance(v, str) or len(v) != 64 for v in value['files'].values()):
            raise ValueError('Invalid startup file record.')
        return value

    def save(self, value):
        audited_json(self.record, value)

    def observe(self):
        return {key: self.install.file_state(path) for key, path in self.paths.items()}

    def verify(self, value, missing_ok=False):
        for key, path in self.paths.items():
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise RuntimeError(f'Replaced startup path preserved: {path}')
            expected = value['files'].get(key)
            if path.exists():
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise RuntimeError(f'Modified or unowned startup file preserved: {path}')
            elif expected and not missing_ok:
                raise RuntimeError('Login integration is incomplete. Use Enable to repair or Disable to remove it.')

    def system_files(self):
        return paths(self.uid)

    def system_ready(self):
        locations = self.system_files()
        record = locations['engine'].parent/'manifest.json'
        if not record.exists():
            return False
        if any(p.is_symlink() for p in (record, *record.parents)) or record.stat().st_uid != 0 or record.stat().st_mode & 0o022:
            raise RuntimeError('System ownership record is not protected.')
        info = json.loads(record.read_text())
        if info.get('uid') != self.uid or set(info.get('files', {})) != set(locations):
            raise RuntimeError('Invalid system ownership record.')
        for name, path in locations.items():
            if not path.exists() and not path.is_symlink():
                return False
            if (any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
                    or path.stat().st_uid != 0 or path.stat().st_mode & 0o022
                    or hashlib.sha256(path.read_bytes()).hexdigest() != info['files'][name]['sha256']):
                raise RuntimeError('System keyboard integration is incomplete or modified. Use Doctor before changing it.')
        return True

    def system_change(self, action):
        args = ['/usr/bin/pkexec', '/usr/bin/python3', '-I', '-B', str(self.install.app/'system_setup.py'), action, str(self.uid)]
        if action == 'install':
            engine = self.install.app/'xremap'
            args += ['--engine', str(engine), '--sha256', self.install.load()['files']['app/xremap']]
        def observed():
            result = {name: self.install.file_state(path) for name, path in self.system_files().items()}
            base = self.system_files()['engine'].parent
            for name in ('manifest.json', 'audit.jsonl'):
                path = base/name
                result[name] = path.read_text() if path.exists() else None
            return result
        self.install.audit.change(action+' system keyboard integration', 'owned system files', observed,
                                  {'action': action}, lambda: subprocess.run(args, check=True))

    def payloads(self):
        def quote(value):
            # ExecStart's ':' prefix disables environment expansion. Escape
            # systemd specifiers and quoted-string characters separately.
            return '"'+str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('%', '%%')+'"'
        controller = quote(self.install.app/'control.py')
        unit = f'''[Unit]
Description=GNOME MacLike enabled keyboard
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=:/usr/bin/python3 -B {controller} login
ExecStop=/usr/bin/systemctl --no-ask-password stop gnome-maclike-{self.uid}.service
TimeoutStartSec=90
TimeoutStopSec=15
'''
        desktop = f'''[Desktop Entry]
Type=Application
Name=GNOME MacLike keyboard
Exec=/usr/bin/systemctl --user start {UNIT}
OnlyShowIn=GNOME;
NoDisplay=true
X-GNOME-Autostart-Phase=Applications
'''
        return {'login': desktop.encode(), 'session': unit.encode()}

    def enable(self):
        value = self.load()
        self.verify(value, missing_ok=True)
        payload = self.payloads()
        # Existing owned files must match this version; never silently replace.
        for name, data in payload.items():
            expected = hashlib.sha256(data).hexdigest()
            if name in value['files'] and value['files'][name] != expected:
                raise RuntimeError('Disable the previous login integration before enabling this version.')
            value['files'][name] = expected
        value['dirs'] = sorted(set(value['dirs']) | {str(p) for path in self.paths.values() for p in path.parents
                             if (p == self.config or p.is_relative_to(self.config)) and not p.exists()}, key=lambda p: len(Path(p).parts))
        value['system'] = True  # Journal the obligation before administrator setup.
        self.save(value)
        if not self.system_ready():
            self.system_change('install')
        for directory in value['dirs']:
            Path(directory).mkdir(mode=0o700, exist_ok=True)
        for name, data in payload.items():
            path = self.paths[name]
            if not path.exists():
                def write():
                    from control import publish
                    fd, staged = tempfile.mkstemp(dir=self.install.record_dir, prefix='.settings-')
                    try:
                        with os.fdopen(fd, 'wb') as stream:
                            stream.write(data); stream.flush(); os.fsync(stream.fileno())
                        publish(staged, path)
                    finally:
                        Path(staged).unlink(missing_ok=True)
                self.install.audit.change('install login file', path, lambda: self.install.file_state(path),
                                          {'sha256': value['files'][name]}, write)
        run(['/usr/bin/systemctl', '--user', 'daemon-reload'])
        value['enabled'] = True
        self.save(value)

    def disable(self):
        value = self.load()
        if not self.record.exists():
            return
        value['enabled'] = False
        self.save(value)  # A leftover login hook must now be a no-op.
        self.verify(value, missing_ok=True)
        if value['files']:
            run(['/usr/bin/systemctl', '--user', 'stop', UNIT])
        for name in value['files']:
            path = self.paths[name]
            self.install.audit.change('remove login file', path, lambda: self.install.file_state(path),
                                      None, lambda: path.unlink(missing_ok=True))
        run(['/usr/bin/systemctl', '--user', 'daemon-reload'])
        for directory in reversed(value['dirs']):
            try:
                Path(directory).rmdir()
            except OSError as exc:
                if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
                    raise  # Keep ownership so a failed cleanup can be retried.
        value.update(files={}, dirs=[])
        self.save(value)

    def uninstall(self):
        value = self.load()
        if not self.record.exists():
            return
        self.disable()
        if value['system']:
            self.system_change('uninstall')
        self.install.audit.change('remove startup recovery', self.record, self.load, None,
                                  lambda: self.record.unlink())

    def start_session(self):
        run(['/usr/bin/systemctl', '--user', 'reset-failed', UNIT])
        # A previous emergency stop leaves the oneshot active. Restart explicitly.
        subprocess.run(['/usr/bin/systemctl', '--user', 'restart', UNIT], check=True, timeout=100)
