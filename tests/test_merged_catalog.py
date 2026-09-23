import unittest
from hackalem.catalog import ROOT, load_catalog

class MergedCatalogueTests(unittest.TestCase):
    def test_seed_preserves_originals_and_expanded_profiles(self):
        original=load_catalog(ROOT/'tests/fixtures/original_catalog.csv')
        rows=load_catalog()
        by_id={p['id']:p for p in rows}
        self.assertEqual(len(rows),166)
        self.assertEqual(len(by_id),166)
        for p in original:
            self.assertIn(p['id'],by_id)
            if not p['synthetic']:
                self.assertEqual(by_id[p['id']],p)
        added=[p for p in rows if p['id'].startswith('SYN-2026-')]
        self.assertEqual(len(added),100)
        for p in rows:
            if p['synthetic']:
                self.assertTrue(p['anon_name'].endswith(' (syn)'))
                self.assertIsNotNone(p['max_hours'])