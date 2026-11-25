import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control import Install
from startup import Startup
from system_setup import SystemSetup, payloads
from test_install import FakeDesktop, FakeRuntime, SOURCE, snapshot
from dashboard import lifecycle
from profiles import DEFAULTS
from refresh_gui import refresh_dashboard


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = Install(self.root/'data', self.root/'state', FakeDesktop(), SOURCE, b'engine', FakeRuntime())
        self.install.install()
        self.startup = Startup(self.install)
        self.commands = patch('startup.run', return_value='').start()
        self.addCleanup(patch.stopall)
        patch.object(self.startup, 'system_ready', return_value=True).start()
        self.system = patch.object(self.startup, 'system_change').start()

    def test_enable_disable_enable_uninstall_restores_entire_footprint(self):
        self.startup.enable()
        self.assertTrue(self.startup.load()['enabled'])
        self.assertTrue(all(p.is_file() for p in self.startup.paths.values()))
        # A new object / login reads persisted intent, not process memory.
        self.assertTrue(Startup(self.install).load()['enabled'])
        self.startup.disable()
        self.assertFalse(self.startup.load()['enabled'])
        self.assertFalse(any(p.exists() for p in self.startup.paths.values()))
        self.startup.enable()
        self.startup.uninstall()
        self.system.assert_called_once_with('uninstall')
        self.install.uninstall()
        self.assertEqual(snapshot(self.root), {})

    def test_cancelled_administrator_setup_is_disabled_and_retryable(self):
        with patch.object(self.startup, 'system_ready', return_value=False), \
             patch.object(self.startup, 'system_change', side_effect=PermissionError('cancelled')):
            with self.assertRaises(PermissionError):
                self.startup.enable()
        self.assertFalse(self.startup.load()['enabled'])
        self.assertTrue(self.startup.load()['system'])
        self.assertFalse(any(p.exists() for p in self.startup.paths.values()))
        self.startup.enable()
        self.assertTrue(self.startup.load()['enabled'])

    def test_each_interrupted_user_publication_can_be_retried_or_uninstalled(self):
        from control import publish
        for target in self.startup.paths.values():
            def fail(source, path):
                if path == target:
                    raise OSError('power loss')
                return publish(source, path)
            with patch('control.publish', side_effect=fail):
                with self.assertRaises(OSError):
                    self.startup.enable()
            self.assertFalse(self.startup.load()['enabled'])
            self.startup.enable()
            self.startup.disable()

    def test_disable_commits_off_before_a_failed_stop_and_login_then_does_nothing(self):
        self.startup.enable()
        with patch('startup.run', side_effect=RuntimeError('stop failed')):
            with self.assertRaises(RuntimeError):
                self.startup.disable()
        self.assertFalse(self.startup.load()['enabled'])
        with patch.object(self.install, 'start') as start:
            self.install.login()
            start.assert_not_called()
        self.startup.disable()

    def test_foreign_modified_and_symlinked_startup_files_are_preserved(self):
        self.startup.enable()
        path = self.startup.paths['login']
        original = path.read_bytes()
        path.write_bytes(b'personal changes')
        with self.assertRaisesRegex(RuntimeError, 'preserved'):
            self.startup.disable()
        self.assertEqual(path.read_bytes(), b'personal changes')
        self.assertFalse(self.startup.load()['enabled'])
        path.unlink()
        personal = self.root/'personal'; personal.write_bytes(b'keep')
        path.symlink_to(personal)
        with self.assertRaisesRegex(RuntimeError, 'preserved'):
            self.startup.disable()
        self.assertEqual(personal.read_bytes(), b'keep')
        path.unlink(); path.write_bytes(original)
        self.startup.disable()

    def test_uninstall_failure_keeps_system_obligation_and_app_for_retry(self):
        self.startup.enable()
        with patch.object(self.startup, 'system_change', side_effect=PermissionError('cancelled')):
            with self.assertRaises(PermissionError):
                self.startup.uninstall()
        self.assertTrue(self.startup.load()['system'])
        self.assertFalse(self.startup.load()['enabled'])
        self.assertTrue(self.install.record.exists())
        self.startup.uninstall()

    def test_disabled_and_enabled_but_failed_are_distinct(self):
        state = dict(installed=True, update=False, running=False, bridge=False,
                     adapter_ready=True, preferences=DEFAULTS, enabled=False)
        self.assertEqual(lifecycle(state)['title'], 'Disabled')
        state['enabled'] = True
        self.assertEqual(lifecycle(state)['title'], 'Enabled, but not running')
        self.assertEqual(lifecycle(state)['action'], 'apply')

    def test_lifecycle_migration_recovers_each_module_and_preserves_preferences(self):
        import hashlib
        from preferences import save_preferences
        save_preferences(self.install.record_dir, DEFAULTS)
        before = (self.install.record_dir/'preferences.json').read_bytes()
        for name in ('runtime.py', 'bridge.py', 'startup.py', 'system_setup.py'):
            info = self.install.load()
            target = self.install.app/name
            target.write_bytes(b'# old\n')
            info['files']['app/'+name] = hashlib.sha256(target.read_bytes()).hexdigest()
            self.install.save(info)
            replace = os.replace
            def fail(source, dest):
                if dest == target:
                    raise OSError('publication interrupted')
                replace(source, dest)
            with patch('refresh_gui.os.replace', side_effect=fail):
                with self.assertRaises(OSError):
                    refresh_dashboard(self.install, lifecycle=True)
            refresh_dashboard(self.install, lifecycle=True)
            self.assertEqual(target.read_bytes(), (SOURCE/name).read_bytes())
            self.assertEqual((self.install.record_dir/'preferences.json').read_bytes(), before)
        self.install.uninstall()
        self.assertEqual(snapshot(self.root), {})


class SystemSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.setup = SystemSetup(1000, self.root, self.calls.append)
        for parent in {p.parent for p in self.setup.paths.values()} - {self.setup.base}:
            parent.mkdir(parents=True)
        self.setup.base.parent.mkdir(parents=True)
        for path in self.root.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
        self.before = snapshot(self.root)

    def test_system_footprint_roundtrip_and_idempotence(self):
        self.setup.install(b'engine', 'test-user')
        self.setup.install(b'engine', 'test-user')
        self.setup.verify(self.setup.load())
        self.setup.uninstall()
        self.setup.uninstall()
        self.assertEqual(snapshot(self.root), self.before)

    def test_interrupted_system_publications_recover_and_remove(self):
        link = os.link
        for target in self.setup.paths.values():
            def fail(source, dest):
                if dest == target:
                    raise OSError('power loss')
                link(source, dest)
            with patch('system_setup.os.link', side_effect=fail):
                with self.assertRaises(OSError):
                    self.setup.install(b'engine', 'test-user')
            self.setup.install(b'engine', 'test-user')
            self.setup.uninstall()
            self.assertEqual(snapshot(self.root), self.before)

    def test_partial_system_install_can_be_removed_without_completing(self):
        with patch('system_setup.os.link', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.setup.install(b'engine', 'test-user')
        self.setup.uninstall()
        self.assertEqual(snapshot(self.root), self.before)

    def test_modified_system_file_blocks_removal_before_any_other_file_is_deleted(self):
        self.setup.install(b'engine', 'test-user')
        self.setup.paths['unit'].write_text('external changes')
        before = snapshot(self.root)
        with self.assertRaisesRegex(RuntimeError, 'preserved'):
            self.setup.uninstall()
        self.assertEqual(snapshot(self.root), before)

    def test_policy_authorizes_only_start_stop_for_exact_user_and_unit(self):
        import shutil
        if not shutil.which('node'):
            self.skipTest('Node is optional; used here to exercise the polkit JavaScript policy.')
        # Execute the policy function against permitted and forbidden requests.
        script = '''let rule; const polkit={addRule:f=>rule=f, Result:{YES:true}};
POLICY
for (const [user, unit, verb, id, expected] of CASES) {
 const got=rule({id, lookup:k=>k==='unit'?unit:verb}, {user});
 if (Boolean(got)!==expected) throw Error(JSON.stringify([user,unit,verb,id]));
}'''
        cases = []
        for user in ('test-user', 'someone-else'):
            for unit in ('gnome-maclike-1000.service', 'sshd.service', 'gnome-maclike-1001.service'):
                for verb in ('start', 'stop', 'restart', 'set-property'):
                    for action in ('org.freedesktop.systemd1.manage-units', 'org.freedesktop.systemd1.manage-unit-files'):
                        cases.append([user, unit, verb, action, user=='test-user' and unit=='gnome-maclike-1000.service' and verb in ('start','stop') and action.endswith('.manage-units')])
        script = script.replace('POLICY', payloads(1000, 'test-user', b'engine')['policy'].decode()).replace('CASES', json.dumps(cases))
        subprocess.run(['node', '-e', script], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
