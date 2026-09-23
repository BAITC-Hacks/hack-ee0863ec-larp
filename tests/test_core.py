"""Unit tests use an explicitly fake encoder, never a production fallback."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hackalem.ai_model import ModelError, ensure_model
from hackalem.cache_store import JsonCache
from hackalem.catalog import (ROOT, Query, belongs, canonical_json, fingerprint, load_catalog,
                     parse_budget, parse_flag, rejection_reasons)

# Original examples have fixed expected counts; keep their historical fixture.
_original_load_catalog = load_catalog
def load_catalog(path=ROOT / "tests/fixtures/original_catalog.csv"):
    return _original_load_catalog(path)
from hackalem.cli import render
from hackalem.recommender import Recommender, cosine, unit_mean


class TestEncoder:
    """TEST DOUBLE, NOT AI. Verifies control flow without downloading weights."""
    identity = 'unit-test-encoder-not-ai-v1'
    label = 'TEST DOUBLE — NOT A NEURAL MODEL'

    def __init__(self):
        self.calls = 0

    def chunks(self, text):
        return [part for part in re.split(r'(?<=[.!?])\s+', text) if part]

    def embed(self, text):
        self.calls += 1
        raw = [float(value - 127) for value in hashlib.sha256(text.encode()).digest()[:8]]
        norm = math.sqrt(math.fsum(v * v for v in raw))
        return [v / norm for v in raw]


def query_example(name='dense'):
    return Query(**json.loads((ROOT / 'examples' / f'{name}.json').read_text(encoding='utf-8')))


def fail_factory():
    raise AssertionError('No candidates: neural model must NOT be loaded.')


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_catalog()

    def test_record_count(self):
        self.assertEqual(len(self.rows), 66)

    def test_unique_ids(self):
        self.assertEqual(len({p['id'] for p in self.rows}), 66)

    def test_categories_split(self):
        self.assertEqual(len({c for p in self.rows for c in p['categories']}), 17)

    def test_flags(self):
        self.assertEqual(sum(p['synthetic'] for p in self.rows), 13)
        self.assertEqual(sum(p['city_imputed'] for p in self.rows), 8)
        self.assertEqual(sum(p['price_imputed'] for p in self.rows), 18)

    def test_null_hours(self):
        self.assertEqual(sum(p['max_hours'] is None for p in self.rows), 9)

    def test_invalid_flag(self):
        with self.assertRaises(ValueError):
            parse_flag('not_a_boolean')

    def test_jsonl_equals_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.jsonl'
            path.write_text('\n'.join(json.dumps(p, ensure_ascii=False) for p in self.rows), encoding='utf-8')
            self.assertEqual(load_catalog(path), self.rows)

    def test_duplicate_id_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.jsonl'
            row = json.dumps(self.rows[0], ensure_ascii=False)
            path.write_text(row + '\n' + row, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'повторяются id'):
                load_catalog(path)

    def test_missing_columns_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.csv'
            path.write_text('id,city\n1,Алматы\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'нет полей'):
                load_catalog(path)

    def test_empty_catalog_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.jsonl'
            path.write_text('', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Каталог пуст'):
                load_catalog(path)


class QueryTests(unittest.TestCase):
    def test_equivalent_inputs_normalize_identically(self):
        a = query_example()
        raw = a.as_dict() | {'city': ' АЛМАТЫ ', 'category': '  ВеДуЩиЙ ',
                             'event_date': '14.11.2026', 'budget_kzt': '1 200 000',
                             'hours': '6,0', 'language': ' РУССКИЙ ',
                             'preferences': a.preferences.upper()}
        b = Query(**raw)
        self.assertEqual(canonical_json(a.as_dict()), canonical_json(b.as_dict()))
        self.assertEqual(a.semantic_text(), b.semantic_text())

    def test_bad_dates_rejected(self):
        for when in ('2026-01-01', '2027-01-01', '2026-11-31', '01/10/26'):
            with self.subTest(when=when), self.assertRaises(ValueError):
                Query(**(query_example().as_dict() | {'event_date': when}))

    def test_budget_validation(self):
        for budget in (-1, True, float('nan'), float('inf'), 'none', '100,5', 12.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                parse_budget(budget)
        self.assertEqual(parse_budget('1\u00a0200\u00a0000'), 1200000)
        self.assertEqual(parse_budget(0), 0)

    def test_hours_validation(self):
        for hours in (0, -2, True, float('inf'), float('nan')):
            with self.subTest(hours=hours), self.assertRaises(ValueError):
                Query(**(query_example().as_dict() | {'hours': hours}))

    def test_optional_fields(self):
        q = Query(**(query_example().as_dict() | {'hours': '', 'language': '  ', 'preferences': ''}))
        self.assertIsNone(q.hours)
        self.assertIsNone(q.language)

    def test_preference_limit(self):
        with self.assertRaises(ValueError):
            Query(**(query_example().as_dict() | {'preferences': 'x' * 2001}))


class MatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_catalog()
        cls.by_id = {p['id']: p for p in cls.rows}

    def engine(self, rows=None, encoder=None, cache=None):
        return Recommender(rows if rows is not None else self.rows,
                           lambda: encoder if encoder is not None else TestEncoder(), cache)

    def test_dense_returns_three_of_four(self):
        result = self.engine().recommend(query_example())
        self.assertEqual(result['eligible_count'], 4)
        self.assertEqual(len(result['cards']), 3)
        self.assertTrue(result['ai_used'])

    def test_no_category_no_model(self):
        result = Recommender(self.rows, fail_factory, None).recommend(query_example('no_category'))
        self.assertEqual(result['status'], 'no_category_in_city')
        self.assertFalse(result['ai_used'])

    def test_busy_no_model(self):
        result = Recommender(self.rows, fail_factory, None).recommend(query_example('busy'))
        self.assertEqual(result['status'], 'no_matches')
        self.assertEqual(result['exclusion_counts']['busy_date'], 4)
        self.assertEqual(result['exclusion_counts']['event_format'], 1)

    def test_budget_no_model(self):
        result = Recommender(self.rows, fail_factory, None).recommend(query_example('budget'))
        self.assertEqual(result['status'], 'no_matches')

    def test_rare_exactly_one_no_fabrication(self):
        result = self.engine().recommend(query_example('rare'))
        self.assertEqual([c['id'] for c in result['cards']], ['HK-90001'])
        self.assertTrue(result['cards'][0]['flags']['synthetic'])
        self.assertIn('всего 2', result['message'])

    def test_venue_calendar(self):
        engine = self.engine()
        self.assertEqual(engine.recommend(query_example('venue_busy'))['cards'], [])
        self.assertEqual([c['id'] for c in engine.recommend(query_example('venue_free'))['cards']], ['HK-90012'])

    def test_changed_date_changes_eligible_pool(self):
        a, b = query_example(), query_example('other_date')
        eligible_a = {p['id'] for p in self.rows if belongs(p, a) and not rejection_reasons(p, a)}
        eligible_b = {p['id'] for p in self.rows if belongs(p, b) and not rejection_reasons(p, b)}
        self.assertEqual(len(eligible_a), 4)
        self.assertEqual(len(eligible_b), 5)
        self.assertNotEqual(eligible_a, eligible_b)

    def test_null_hours_not_zero(self):
        p = self.by_id['HK-90001']
        q = Query(**(query_example('rare').as_dict() | {'hours': 24}))
        self.assertNotIn('duration', rejection_reasons(p, q))

    def test_duration_is_hard_constraint(self):
        p = self.by_id['HK-90012']
        q = Query(**(query_example('venue_free').as_dict() | {'hours': 11}))
        self.assertIn('duration', rejection_reasons(p, q))

    def test_language_is_hard_constraint(self):
        p = self.by_id['HK-90001']
        q = Query(**(query_example('rare').as_dict() | {'language': 'английский'}))
        self.assertIn('language', rejection_reasons(p, q))

    def test_price_is_inclusive(self):
        p = self.by_id['HK-90001']
        q = Query(**(query_example('rare').as_dict() | {'budget_kzt': 250000}))
        self.assertNotIn('budget', rejection_reasons(p, q))

    def test_output_explanations_are_actual_source_spans(self):
        result = self.engine().recommend(query_example())
        for card in result['cards']:
            self.assertIn(card['description_excerpt'], self.by_id[card['id']]['description'])
            self.assertIn('2026-11-14', card['explanation'])

    def test_score_is_not_probability(self):
        result = self.engine().recommend(query_example())
        self.assertIn('не вероятность', render(result))

    def test_every_card_satisfies_all_constraints(self):
        engine = self.engine()
        for when in ('2026-09-23', '2026-10-01', '2026-11-14', '2026-12-25'):
            for city in ('Алматы', 'Астана'):
                for category in ('Ведущий', 'Фотограф', 'Банкетный зал', 'Флорист'):
                    q = Query(city, when, 'свадьба', category, 4000000, 6, 'русский')
                    result = engine.recommend(q)
                    self.assertLessEqual(len(result['cards']), 3)
                    self.assertEqual(len({c['id'] for c in result['cards']}), len(result['cards']))
                    for card in result['cards']:
                        self.assertTrue(belongs(self.by_id[card['id']], q))
                        self.assertEqual(rejection_reasons(self.by_id[card['id']], q), [])

    def test_semantic_vectors_change_order_not_just_price(self):
        class ControlledEncoder(TestEncoder):
            def chunks(self, text):
                return [text]
            def embed(self, text):
                return [0.0, 1.0] if text == 'low semantic similarity' else [1.0, 0.0]
        good = copy.deepcopy(self.by_id['HK-90001'])
        cheap = copy.deepcopy(good)
        good.update(id='T-2', description='high semantic similarity', price_from_kzt=250000)
        cheap.update(id='T-1', description='low semantic similarity', price_from_kzt=100000)
        result = self.engine([cheap, good], ControlledEncoder()).recommend(query_example('rare'))
        self.assertEqual(result['cards'][0]['id'], 'T-2')

    def test_ties_use_price_then_id(self):
        class EqualEncoder(TestEncoder):
            def embed(self, text):
                return [1.0, 0.0]
        result = self.engine(encoder=EqualEncoder()).recommend(query_example())
        self.assertEqual([c['id'] for c in result['cards']], ['HK-44923', 'HK-29829', 'HK-27222'])

    def test_repeated_uncached_engines_identical(self):
        first = self.engine().recommend(query_example())
        second = self.engine().recommend(query_example())
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(render(first), render(second))

    def test_row_order_does_not_change_output(self):
        self.assertEqual(self.engine().recommend(query_example()),
                         self.engine(list(reversed(self.rows))).recommend(query_example()))

    def test_result_cache_survives_new_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self.engine(cache=Path(folder)).recommend(query_example())
            encoder = TestEncoder()
            second = self.engine(encoder=encoder, cache=Path(folder)).recommend(query_example())
            self.assertEqual(encoder.calls, 0)
            self.assertEqual(first, second)

    def test_changed_data_invalidate_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            first = self.engine(cache=Path(folder)).recommend(query_example())
            rows = copy.deepcopy(self.rows)
            for row in rows:
                if row['id'] == first['cards'][0]['id']:
                    row['busy_dates'].append('2026-11-14')
            second = self.engine(rows, cache=Path(folder)).recommend(query_example())
            self.assertNotEqual(first['dataset_sha256'], second['dataset_sha256'])
            self.assertNotIn(first['cards'][0]['id'], [c['id'] for c in second['cards']])


class UtilityTests(unittest.TestCase):
    def test_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = JsonCache(Path(folder))
            cache.put('a', {'тест': 1})
            self.assertEqual(cache.get('a'), {'тест': 1})

    def test_cache_corruption_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = JsonCache(Path(folder))
            cache.put('a', {'a': 1})
            (Path(folder) / 'a.json').write_text('{broken', encoding='utf-8')
            self.assertIsNone(cache.get('a'))

    def test_cache_checksum_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = JsonCache(Path(folder))
            cache.put('a', {'a': 1})
            p = Path(folder) / 'a.json'
            value = json.loads(p.read_text())
            value['value'] = {'a': 2}
            p.write_text(json.dumps(value))
            self.assertIsNone(cache.get('a'))

    def test_missing_offline_model_gives_clear_error(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ModelError, 'отсутствует'):
            ensure_model(Path(folder), offline=True)

    def test_corrupt_model_hash_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'model.onnx').write_bytes(b'not a model')
            with self.assertRaisesRegex(ModelError, 'сумма'):
                ensure_model(Path(folder), offline=True)

    def test_unit_mean(self):
        v = unit_mean([[1, 0], [0, 1]])
        self.assertAlmostEqual(sum(x * x for x in v), 1)

    def test_dimension_mismatch(self):
        with self.assertRaises(ValueError):
            cosine([1], [1, 2])

    def test_bad_vector_rejected(self):
        with self.assertRaises(ValueError):
            unit_mean([[0, 0]])

    def test_cli_empty_result_runs_without_ai(self):
        completed = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--catalog', str(ROOT / 'tests/fixtures/original_catalog.csv'), '--query',
                                    str(ROOT / 'examples/no_category.json'), '--json', '--offline'],
                                   capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'], 'no_category_in_city')

    def test_cli_help(self):
        completed = subprocess.run([sys.executable, str(ROOT / 'main.py'), '--help'],
                                   capture_output=True, timeout=20)
        self.assertEqual(completed.returncode, 0)
        self.assertIn(b'--prepare', completed.stdout)


if __name__ == '__main__':
    unittest.main()
