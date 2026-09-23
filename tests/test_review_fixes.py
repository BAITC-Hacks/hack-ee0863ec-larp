import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
from hackalem.catalog import Query, ROOT, load_catalog, parse_budget
from hackalem.catalog_store import import_catalog, read_profiles
from hackalem.preferences import assess
from hackalem.recommender import Recommender
from tests.test_core import TestEncoder

class FixTests(unittest.TestCase):
    def query(self, **changes):
        return Query(**(json.loads((ROOT/'examples/dense.json').read_text(encoding='utf-8'))|changes))

    def test_fractional_budget_rejected(self):
        for value in ('1.00000000000000001',Decimal('999999999999.00001'),True):
            with self.assertRaises(ValueError):
                parse_budget(value)

    def test_invalid_unicode_rejected(self):
        for text in ('\ud800','\x00'):
            with self.assertRaises(ValueError):
                self.query(preferences=text)

    def test_conditional_offer_unknown(self):
        for text in ('Работаю без конкурсов только за доплату','Могу работать без конкурсов',
                     'Без конкурсов если заранее попросите'):
            self.assertEqual(assess('без конкурсов',text)[0]['status'],'unknown')

    def test_synthetic_exclusion_applies_to_results_and_suggestions(self):
        engine=Recommender(load_catalog(),TestEncoder,None)
        result=engine.recommend(self.query(include_synthetic=False))
        self.assertTrue(result['cards'])
        self.assertTrue(all(not c['flags']['synthetic'] for c in result['cards']))
        result=engine.recommend(self.query(include_synthetic=False,budget_kzt=0))
        self.assertTrue(result['suggestions'])
        self.assertTrue(all(not p['flags']['synthetic'] for s in result['suggestions'] for p in s['profiles']))
        with self.assertRaises(ValueError):
            self.query(include_synthetic='false')

    def test_import_backup_preserves_previous_records(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            source=folder/'seed.jsonl';db=folder/'catalog.sqlite3'
            profile=load_catalog()[0]
            source.write_text(json.dumps(profile),encoding='utf-8')
            import_catalog(source,db)
            before=read_profiles(db)
            profile['anon_name']='Updated'
            source.write_text(json.dumps(profile),encoding='utf-8')
            import_catalog(source,db)
            backups=list((folder/'backups').glob('*.sqlite3'))
            self.assertEqual(len(backups),1)
            self.assertEqual(read_profiles(backups[0]),before)
            self.assertEqual(read_profiles(db)[0]['anon_name'],'Updated')
