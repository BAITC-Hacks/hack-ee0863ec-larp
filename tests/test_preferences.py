"""Regression examples are explicit fixtures, not a quality benchmark."""
import copy
import os
import unittest

from hackalem.catalog import Query, load_catalog
from hackalem.preferences import assess
from hackalem.recommender import Recommender
from tests.test_core import TestEncoder


def fixtures():
    base = load_catalog()[0]
    texts = {
        'contests': 'Ведущий корпоративных мероприятий. Провожу шумные конкурсы и активные игры с гостями.',
        'no_contests': 'Ведущий корпоративных мероприятий. Работаю без конкурсов и без навязчивых игр.',
        'business': 'Ведущий корпоративных мероприятий. Провожу деловые конференции и официальные церемонии.',
    }
    rows = []
    for key, text in texts.items():
        profile = copy.deepcopy(base)
        profile.update(id=key, anon_name=key, categories=['Ведущий'], city='Алматы', price_from_kzt=100000,
                       event_formats=['корпоратив'], languages=['русский'], max_hours=8, busy_dates=[], description=text)
        rows.append(profile)
    return rows


def query(wish):
    return Query('Алматы', '2026-10-15', 'корпоратив', 'Ведущий', 1000000, preferences=wish)


class PreferenceTests(unittest.TestCase):
    def test_explicit_absence_and_conflict(self):
        self.assertEqual(assess('Без конкурсов', 'Работаю без конкурсов.')[0]['status'], 'supported')
        self.assertEqual(assess('Без конкурсов', 'Провожу конкурсы.')[0]['status'], 'conflict')
        self.assertEqual(assess('Хочу конкурсы', 'Работаю без конкурсов.')[0]['status'], 'conflict')

    def test_no_mention_is_unknown_not_supported(self):
        self.assertEqual(assess('Без конкурсов', 'Ведущий с опытом.')[0]['status'], 'unknown')

    def test_qualifiers_do_not_become_absolute_promises(self):
        self.assertEqual(assess('Без конкурсов', 'Работаю без банальных конкурсов.')[0]['status'], 'unknown')
        self.assertEqual(assess('Без банальных конкурсов', 'Провожу конкурсы.'), [])
        self.assertEqual(assess('Без игр', 'Работаю без навязчивых игр.')[0]['status'], 'unknown')

    def test_mixed_and_double_negation_is_not_claimed_as_support(self):
        for text in ['Не работаю без конкурсов.', 'Провожу конкурсы. Работаю без конкурсов.']:
            self.assertEqual(assess('Без конкурсов', text)[0]['status'], 'unknown')
        checks = assess('Без конкурсов. Хочу конкурсы.', 'Работаю без конкурсов.')
        self.assertEqual(checks[0]['status'], 'unknown')

    def test_negation_in_plain_list(self):
        for text in ['Работаю без конкурсов и игр.', 'Работаю без конкурсов и без игр.']:
            checks = assess('Без конкурсов и игр', text)
            self.assertEqual(len(checks), 2)
            self.assertTrue(all(c['status'] == 'supported' for c in checks))

    def test_soft_conflicts_do_not_change_eligibility(self):
        rows = fixtures()
        result = Recommender(rows, TestEncoder, None).recommend(query('Без конкурсов'))
        self.assertEqual(result['eligible_count'], 3)
        self.assertEqual(len(result['cards']), 3)
        self.assertEqual(result['cards'][-1]['id'], 'contests')
        self.assertTrue(result['cards'][-1]['warnings'])
        for card in result['cards']:
            for check in card['preference_checks']:
                if check['source_excerpt']:
                    original = next(p['description'] for p in rows if p['id'] == card['id'])
                    self.assertIn(check['source_excerpt'], original)


@unittest.skipUnless(os.environ.get('RUN_AI_TESTS') == '1', 'Requires the real local neural model.')
class RealPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hackalem.ai_model import MiniLMEncoder
        cls.encoder = MiniLMEncoder(cache_dir=None, offline=True)

    def test_opposite_requests_change_top_card_and_quote(self):
        engine = Recommender(fixtures(), lambda: self.encoder, None)
        negative = engine.recommend(query('Без конкурсов и игр'))
        positive = engine.recommend(query('Хочу конкурсы и игры'))
        self.assertEqual(negative['cards'][0]['id'], 'no_contests')
        self.assertIn('без конкурсов', negative['cards'][0]['description_excerpt'])
        self.assertEqual(positive['cards'][0]['id'], 'contests')
        self.assertIn('Провожу', positive['cards'][0]['description_excerpt'])
        self.assertEqual(negative, engine.recommend(query('Без конкурсов и игр')))
        self.assertEqual(negative, Recommender(list(reversed(fixtures())), lambda: self.encoder, None).recommend(query('Без конкурсов и игр')))

    def test_paraphrase_without_supported_rule_still_uses_neural_model(self):
        rows = fixtures()[:2]
        rows[0]['description'] = 'Громкие танцевальные батлы, шумные конкурсы и дискотека.'
        rows[1]['description'] = 'Камерные вечера с ненавязчивым общением и деликатным юмором.'
        result = Recommender(rows, lambda: self.encoder, None).recommend(query('Спокойный праздник для небольшой компании'))
        self.assertEqual(result['cards'][0]['id'], 'no_contests')
        self.assertTrue(result['ai_used'])
