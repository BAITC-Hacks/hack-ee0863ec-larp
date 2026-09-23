"""Opt-in tests that require the REAL downloaded model; never report mocks as AI."""
import json
import math
import os
import unittest

from hackalem.ai_model import MiniLMEncoder
from hackalem.catalog import ROOT, Query, canonical_json, load_catalog
from hackalem.recommender import Recommender, cosine


@unittest.skipUnless(os.environ.get('RUN_AI_TESTS') == '1',
                     'Requires real model: prepare it, then set RUN_AI_TESTS=1.')
class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = MiniLMEncoder(cache_dir=None, offline=True)

    def test_real_384_dimension_embedding(self):
        v = self.encoder.embed('Ведущий для корпоративного мероприятия')
        self.assertEqual(len(v), 384)
        self.assertAlmostEqual(math.fsum(x*x for x in v), 1.0, places=6)

    def test_russian_semantic_smoke(self):
        a = self.encoder.embed('Нужен ведущий для свадебного торжества')
        b = self.encoder.embed('Ищем ведущего на свадьбу')
        c = self.encoder.embed('Дифференциальные уравнения в квантовой механике')
        self.assertGreater(cosine(a, b), cosine(a, c))

    def test_chunks_do_not_overflow_token_window(self):
        for row in load_catalog():
            for chunk in self.encoder.chunks(row['description']):
                self.assertLessEqual(len(self.encoder.splitter.encode(chunk).ids), 128)
                self.assertIn(chunk, row['description'])

    def test_two_real_sessions_equal(self):
        raw = json.loads((ROOT / 'examples/dense.json').read_text(encoding='utf-8'))
        rows = load_catalog()
        first = Recommender(rows, lambda: self.encoder, None).recommend(Query(**raw))
        second_encoder = MiniLMEncoder(cache_dir=None, offline=True)
        second = Recommender(rows, lambda: second_encoder, None).recommend(Query(**raw))
        self.assertEqual(len(first['cards']), 3)
        self.assertTrue(first['ai_used'])
        self.assertEqual(canonical_json(first), canonical_json(second))
