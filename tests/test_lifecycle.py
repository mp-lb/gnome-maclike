import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard import Dashboard, lifecycle
from profiles import DEFAULTS
from control import Install
from preferences import Appearance, DOCK, save_preferences
from test_install import FakeDesktop, FakeRuntime, SOURCE
from test_dashboard import MemoryDconf


class LifecycleTests(unittest.TestCase):
    def state(self, **changes):
        return dict(installed=True, update=False, running=True, bridge=True,
                    adapter_ready=True, preferences=copy.deepcopy(DEFAULTS), **changes)

    def test_unknown_is_not_inactive_and_has_a_check_action(self):
        result = lifecycle()
        self.assertEqual(result['kind'], 'unknown')
        self.assertEqual(result['action'], 'check')
        self.assertIn('already be active', result['message'])
        self.assertNotEqual(lifecycle(self.state(), error='timeout')['kind'], 'healthy')

    def test_healthy_hides_banner_but_stopped_is_neutral_not_broken(self):
        self.assertEqual(lifecycle(self.state())['kind'], 'healthy')
        self.assertFalse(lifecycle(self.state())['banner'])
        state = self.state()
        state.update(running=False, bridge=False)
        self.assertEqual(lifecycle(state)['kind'], 'off')
        self.assertFalse(lifecycle(state)['banner'])
        self.assertIn('Dock and wallpaper', lifecycle(state)['message'])

    def test_unhealthy_snapshots_have_an_explanation_and_resolution(self):
        for change, action in [({'installed':False}, 'install'), ({'update':True}, 'install'),
                               ({'adapter_ready':False}, 'check'), ({'bridge':False}, 'apply'),
                               ({'running':False}, 'apply'), ({'pending_keyboard':True}, 'apply'),
                               ({'problems':['File changed.']}, 'restore')]:
            state = self.state(); state.update(change)
            result = lifecycle(state)
            self.assertEqual(result['kind'], 'attention')
            self.assertEqual(result['action'], action)
            self.assertTrue(result['banner'])
            self.assertTrue(result['message'])
        self.assertEqual(lifecycle(self.state(), dirty=True)['action'], 'apply')
        self.assertEqual(lifecycle(self.state(), operation_error='Cancelled')['kind'], 'attention')

    def test_real_status_detects_file_damage_external_changes_and_unapplied_choices(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = FakeRuntime()
            runtime.state = lambda user=False: {'LoadState':'loaded', 'ActiveState':'active'}
            runtime.context = lambda: {'locked':False}
            runtime.directory = Path(temp)/'run'
            runtime.directory.mkdir()
            import json
            (runtime.directory/'preferences.json').write_text(json.dumps(DEFAULTS))
            install = Install(Path(temp)/'data', Path(temp)/'state', FakeDesktop(), SOURCE, b'engine', runtime)
            install.install()
            memory = MemoryDconf()
            with patch('preferences.Dconf', return_value=memory):
                backend = Dashboard(install)
                self.assertEqual(lifecycle(backend.status())['kind'], 'healthy')
                prefs = copy.deepcopy(DEFAULTS); prefs['layers']['navigation'] = False
                save_preferences(install.record_dir, prefs)
                self.assertTrue(backend.status()['pending_keyboard'])
                appearance = Appearance(install.record_dir, memory)
                appearance.apply({DOCK+'dock-position': "'BOTTOM'"})
                memory.write(DOCK+'dock-position', "'RIGHT'")
                self.assertTrue(backend.status()['problems'])
                appearance.restore()
                (install.app/'gui.py').write_text('external edit')
                self.assertIn('installed file', backend.status()['problems'][0])

