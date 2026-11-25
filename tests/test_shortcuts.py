import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shortcuts import CATALOG, STATUSES, CATEGORIES, SOURCES, matching
from profiles import compile_profile, DEFAULTS


class CatalogTests(unittest.TestCase):
    def test_every_explicit_mapping_has_an_inventory_entry(self):
        profile = compile_profile(Path(__file__).resolve().parents[1], DEFAULTS)
        implemented = {(rule['name'], key) for rule in profile['keymap'] for key in rule['remap']}
        covered = {binding for entry in CATALOG for binding in entry.bindings}
        self.assertEqual(implemented, covered, 'Update the inventory when adding/removing an explicit mapping')

    def test_entries_have_stable_unique_ids_and_valid_decisions(self):
        self.assertEqual(len(CATALOG), len({row.id for row in CATALOG}))
        for row in CATALOG:
            self.assertIn(row.status, STATUSES)
            self.assertIn(row.category, CATEGORIES)
            self.assertIn(row.source, SOURCES)
            if row.status in ('planned', 'not_planned', 'base'):
                self.assertFalse(row.bindings)

    def test_search_handles_words_symbols_and_filters(self):
        self.assertIn('text-left', {row.id for row in matching('command left')})
        self.assertIn('text-left', {row.id for row in matching('⌘ ←')})
        self.assertIn('terminal-copy', {row.id for row in matching('copy terminal')})
        self.assertEqual([row.id for row in matching('backtick', 'planned')], ['cycle-window', 'cycle-window-back'])
        self.assertEqual(matching('no-such-action-xyz'), ())

    def test_proposed_shortcuts_are_not_reported_as_implemented(self):
        by_id = {row.id: row for row in CATALOG}
        for id in ('cycle-window', 'launcher', 'capture-area'):
            self.assertEqual(by_id[id].status, 'planned')
        self.assertEqual(by_id['minimize-as-hide'].status, 'approximation')
        self.assertEqual(by_id['copy'].status, 'base')
        self.assertIn('context', by_id['terminal-copy'].detail)
