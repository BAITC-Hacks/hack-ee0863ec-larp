"""Verified one-condition alternatives must never become original-request matches."""
import copy
import unittest
from dataclasses import replace
from datetime import timedelta

from hackalem.catalog import WINDOW_START, WINDOW_END, belongs, load_catalog, rejection_reasons
from hackalem.cli import render
from hackalem.recommender import Recommender
from tests.test_core import TestEncoder, fail_factory, query_example


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.rows = load_catalog()
        self.engine = Recommender(self.rows, fail_factory, None)

    def test_minimum_budget_and_explicit_application(self):
        query = query_example('budget')
        original = query.as_dict()
        result = self.engine.recommend(query)
        suggestion, = result['suggestions']
        self.assertEqual((suggestion['field'], suggestion['original_value'], suggestion['suggested_value']),
                         ('budget_kzt', 100000, 800000))
        self.assertEqual(result['cards'], [])
        self.assertEqual(result['eligible_count'], 0)
        self.assertEqual(query.as_dict(), original)
        self.assertEqual(result['query'], original)
        below = replace(query, budget_kzt=799999)
        self.assertFalse(any(belongs(p, below) and not rejection_reasons(p, below) for p in self.rows))
        changed = replace(query, budget_kzt=suggestion['suggested_value'])
        applied = Recommender(self.rows, TestEncoder, None).recommend(changed)
        self.assertEqual(applied['status'], 'found')
        self.assertEqual(applied['suggestions'], [])

    def test_venue_date_and_warnings_before_and_after_choice(self):
        query = query_example('venue_busy')
        result = self.engine.recommend(query)
        suggestion, = result['suggestions']
        self.assertEqual(suggestion['field'], 'event_date')
        self.assertEqual(suggestion['suggested_value'], '2026-11-15')
        profile, = suggestion['profiles']
        self.assertEqual(profile['id'], 'HK-90012')
        self.assertTrue(profile['flags']['synthetic'])
        self.assertTrue(profile['flags']['price_imputed'])
        applied = Recommender(self.rows, TestEncoder, None).recommend(query_example('venue_free'))
        for warning in profile['warnings']:
            self.assertIn(warning, render(result))
            self.assertIn(warning, applied['cards'][0]['warnings'])
        self.assertEqual(result['cards'], [])
        self.assertEqual(result['query']['event_date'], '2026-11-14')

    def test_every_suggestion_passes_all_unchanged_constraints(self):
        for example in ('budget', 'busy', 'venue_busy', 'no_category'):
            query = query_example(example)
            for suggestion in self.engine.recommend(query)['suggestions']:
                changed = replace(query, **{suggestion['field']: suggestion['suggested_value']})
                expected = [p['id'] for p in self.rows if belongs(p, changed) and not rejection_reasons(p, changed)]
                self.assertTrue(expected)
                self.assertEqual([p['id'] for p in suggestion['profiles']], expected)
                self.assertEqual(suggestion['eligible_count'], len(expected))

    def test_no_suggestion_when_two_changes_are_required(self):
        query = replace(query_example('venue_busy'), budget_kzt=0)
        self.assertEqual(self.engine.recommend(query)['suggestions'], [])
        self.assertEqual(self.engine.recommend(query_example('no_category'))['suggestions'], [])

    def test_calendar_bounds_and_fully_booked_window(self):
        row = copy.deepcopy(next(p for p in self.rows if p['id'] == 'HK-90012'))
        days = [(WINDOW_START + timedelta(days=n)).isoformat()
                for n in range((WINDOW_END - WINDOW_START).days + 1)]
        row['busy_dates'] = days
        engine = Recommender([row], fail_factory, None)
        query = replace(query_example('venue_busy'), event_date=WINDOW_END.isoformat())
        self.assertEqual(engine.recommend(query)['suggestions'], [])
        row['busy_dates'] = days[1:]
        suggestion, = engine.recommend(query)['suggestions']
        self.assertEqual(suggestion['suggested_value'], WINDOW_START.isoformat())


if __name__ == '__main__':
    unittest.main()
