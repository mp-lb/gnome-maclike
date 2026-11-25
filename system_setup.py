#!/usr/bin/python3
"""One-time administrator provisioning. Standard library only; run with -I -B.

The root-owned engine is fixed. Polkit permits this user to start/stop only this
unit, never to replace its command or create arbitrary transient root services.
The socket backend delegates launch actions to the unprivileged allowlist.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def paths(uid, root=Path('/')):
    name = f'gnome-maclike-{uid}'
    base = root / f'var/lib/{name}'
    return {'engine': base/'xremap', 'session_check': base/'check_session.py',
            'unit': root/f'etc/systemd/system/{name}.service',
            'policy': root/f'usr/share/polkit-1/rules.d/50-{name}.rules'}


def payloads(uid, username, engine):
    base = f'/var/lib/gnome-maclike-{uid}'
    runtime = f'/run/user/{uid}/gnome-maclike'
    unit = f'''[Unit]
Description=GNOME MacLike managed keyboard {uid}
BindsTo=user@{uid}.service
After=user@{uid}.service
ConditionPathExists={runtime}/active.json
ConditionPathExists={runtime}/desktop.sock

[Service]
Type=exec
ExecCondition=/usr/bin/python3 -I -B {base}/check_session.py
ExecStart={base}/xremap --desktop=socket --no-window-logging --allow-launch=true --watch=device "--output-device-name=GNOME MacLike (Xremap)" {runtime}/active.json
Environment=XREMAP_SOCKET=/run/user/{{uid}}/gnome-maclike/desktop.sock RUST_LOG=error
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_DAC_OVERRIDE
ProtectSystem=strict
ProtectHome=tmpfs
BindReadOnlyPaths={runtime}
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX
RestrictSUIDSGID=yes
DevicePolicy=closed
DeviceAllow=char-input r
DeviceAllow=/dev/uinput rw
TimeoutStopSec=5s
Restart=no
'''
    policy = '''// Owned by GNOME MacLike. No arbitrary commands or unit edits.
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == USER && action.lookup("unit") == UNIT) {
        var verb = action.lookup("verb");
        if (verb == "stop" || verb == "start")
            return polkit.Result.YES;
    }
});
'''.replace('USER', json.dumps(username)).replace('UNIT', json.dumps(f'gnome-maclike-{uid}.service'))
    # User-manager processes may have no polkit login session. The fixed root
    # service checks logind itself before allowing an engine to grab devices.
    check = f'''import os, stat, subprocess, sys
def read(*args):
    return subprocess.check_output(['/usr/bin/loginctl', *args], text=True, timeout=5).strip()
try:
    session = read('show-user', '{uid}', '-p', 'Display', '--value')
    values = dict(line.split('=', 1) for line in read('show-session', session, '-p', 'User', '-p', 'Type', '-p', 'Active', '-p', 'Remote').splitlines())
    good = values == {{'User':'{uid}', 'Type':'wayland', 'Active':'yes', 'Remote':'no'}}
    sock = os.lstat('{runtime}/desktop.sock')
    config = os.lstat('{runtime}/active.json')
    good = good and stat.S_ISSOCK(sock.st_mode) and sock.st_uid == {uid} and stat.S_ISREG(config.st_mode) and config.st_uid == {uid}
except Exception:
    good = False
sys.exit(0 if good else 1)
'''
    return {'engine': engine, 'session_check': check.encode(), 'unit': unit.encode(), 'policy': policy.encode()}


class SystemSetup:
    def __init__(self, uid, root=Path('/'), runner=None):
        if not isinstance(uid, int) or uid < 1000:
            raise ValueError('Expected a regular user ID.')
        self.uid = uid
        self.paths = paths(uid, Path(root))
        self.base = self.paths['engine'].parent
        self.record = self.base/'manifest.json'
        self.log = self.base/'audit.jsonl'
        self.runner = runner or (lambda args: subprocess.run(args, check=True, timeout=20))

    def safe_parents(self, path):
        for parent in path.parents:
            if parent.is_symlink() or not parent.is_dir():
                raise RuntimeError(f'Replaced or missing system directory: {parent}')
            if parent.stat().st_uid not in (0, os.geteuid()) or parent.stat().st_mode & 0o022:
                # Tests use /tmp, whose sticky parent is safe above their private root.
                if parent.stat().st_mode & 0o1000:
                    continue
                raise RuntimeError(f'Untrusted system directory: {parent}')

    def event(self, action, **data):
        fd = os.open(self.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o644)
        os.fchmod(fd, 0o644)  # Readable by Doctor; contains paths/hashes, not input.
        with os.fdopen(fd, 'a') as stream:
            stream.write(json.dumps(dict(time=time.time(), action=action, **data))+'\n')
            stream.flush(); os.fsync(stream.fileno())

    def load(self):
        self.safe_parents(self.record)
        if self.record.is_symlink() or self.record.stat().st_uid != os.geteuid() or self.record.stat().st_mode & 0o022:
            raise RuntimeError('Untrusted system ownership record.')
        info = json.loads(self.record.read_text())
        if set(info) != {'version', 'uid', 'files'} or info['version'] != 1 or info['uid'] != self.uid or set(info['files']) != set(self.paths):
            raise RuntimeError('Invalid system ownership record.')
        for entry in info['files'].values():
            if set(entry) != {'sha256', 'mode'} or entry['mode'] not in (0o644, 0o755) or not isinstance(entry['sha256'], str) or len(entry['sha256']) != 64:
                raise RuntimeError('Invalid system file record.')
        allowed = {'manifest.json', 'audit.jsonl', 'xremap', 'check_session.py'} | {'.staged-'+name for name in self.paths}
        if any(p.name not in allowed or p.is_symlink() for p in self.base.iterdir()):
            raise RuntimeError('Unexpected system files preserved.')
        return info

    def verify(self, info):
        for name, path in self.paths.items():
            self.safe_parents(path)
            if os.path.lexists(path):
                expected = info['files'][name]
                if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o777 != expected['mode'] or digest(path.read_bytes()) != expected['sha256']:
                    raise RuntimeError(f'Modified system file preserved: {path}')

    def install(self, engine, username):
        payload = payloads(self.uid, username, engine)
        info = {'version': 1, 'uid': self.uid, 'files': {
            name: {'sha256': digest(data), 'mode': 0o755 if name == 'engine' else 0o644}
            for name, data in payload.items()}}
        if os.path.lexists(self.base):
            if self.load() != info:
                raise RuntimeError('Different system installation preserved; uninstall it before replacing.')
        else:
            for path in self.paths.values():
                self.safe_parents(path.parent if path.parent == self.base else path)
                if os.path.lexists(path):
                    raise RuntimeError(f'Existing system file preserved: {path}')
            self.base.mkdir(mode=0o755)
            with self.record.open('x') as stream:
                json.dump(info, stream); stream.flush(); os.fsync(stream.fileno())
            self.record.chmod(0o644)
            self.event('baseline', before=None, requested=info)
        self.verify(info)
        for name, data in payload.items():
            path = self.paths[name]
            if path.exists():
                continue
            stage = self.base/('.staged-'+name)
            self.event('install intent', path=str(path), before=None, requested=info['files'][name])
            fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            stage.chmod(info['files'][name]['mode'])
            # Hard link publishes without replacing a destination that appeared.
            os.link(stage, path)
            stage.unlink()
            self.event('install completed', path=str(path), after=info['files'][name])
        self.runner(['/usr/bin/systemctl', 'daemon-reload'])
        self.event('provisioned')

    def uninstall(self):
        if not os.path.lexists(self.base):
            if any(os.path.lexists(p) for p in self.paths.values()):
                raise RuntimeError('System files exist without ownership; preserved.')
            return
        info = self.load()
        self.verify(info)  # Validate every file before removing anything.
        try:
            self.runner(['/usr/bin/systemctl', 'stop', f'gnome-maclike-{self.uid}.service'])
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 5:  # An interrupted install may never load a unit.
                raise
        for name in ('policy', 'unit', 'session_check', 'engine'):
            path = self.paths[name]
            self.event('remove intent', path=str(path), before=info['files'][name], requested=None)
            path.unlink(missing_ok=True)
            self.event('remove completed', path=str(path), after=None)
        self.runner(['/usr/bin/systemctl', 'daemon-reload'])
        for name in self.paths:
            (self.base/('.staged-'+name)).unlink(missing_ok=True)
        self.event('uninstalled')
        self.log.unlink(missing_ok=True)
        self.record.unlink()
        self.base.rmdir()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'replace', 'uninstall'))
    parser.add_argument('uid', type=int)
    parser.add_argument('--engine', type=Path)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    if os.geteuid() != 0 or int(os.environ.get('PKEXEC_UID', '-1')) != args.uid:
        raise RuntimeError('Run through the normal user’s administrator authentication prompt.')
    setup = SystemSetup(args.uid)
    if args.action in ('install', 'replace'):
        engine = args.engine.read_bytes()
        if digest(engine) != args.sha256:
            raise RuntimeError('Engine changed before administrator setup.')
        if args.action == 'replace':
            # Replacement is an explicit administrator operation. Both sides
            # retain the same partial-install/removal recovery guarantees.
            setup.uninstall()
        setup.install(engine, pwd.getpwuid(args.uid).pw_name)
    else:
        setup.uninstall()


if __name__ == '__main__':
    main()
