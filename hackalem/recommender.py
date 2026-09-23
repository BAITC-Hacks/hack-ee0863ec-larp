"""Strict eligibility + pretrained semantic ranking + source-grounded explanation."""
from __future__ import annotations

import math
from collections import Counter
from pathlib import Path
from typing import Callable, Protocol

from hackalem.cache_store import JsonCache
from hackalem.catalog import (FLAG_FIELDS, REASONS, ROOT, Profile, Query, belongs, fingerprint,
                     rejection_reasons, normalized)

APP_VERSION = 'hackalem-ai-console-1.0'
# Deliberate engineering constants, NOT learned relevance labels/probabilities.
BEST_CHUNK_WEIGHT = 0.7
MEAN_CHUNK_WEIGHT = 0.3


class Encoder(Protocol):
    identity: str
    label: str
    def chunks(self, text: str) -> list[str]: ...
    def embed(self, text: str) -> list[float]: ...


def unit_mean(vectors: list[list[float]]) -> list[float]:
    if not vectors or not vectors[0] or any(len(v) != len(vectors[0]) for v in vectors):
        raise ValueError('Некорректные размерности векторов.')
    result = [math.fsum(row[i] for row in vectors) / len(vectors)
              for i in range(len(vectors[0]))]
    norm = math.sqrt(math.fsum(x * x for x in result))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError('Невозможно нормировать вектор запроса.')
    return [x / norm for x in result]


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError('Размерности векторов не совпадают.')
    value = math.fsum(x * y for x, y in zip(left, right))
    if not math.isfinite(value):
        raise ValueError('Некорректная семантическая оценка.')
    return max(-1.0, min(1.0, value))


def money(value: int) -> str:
    return f'{value:,}'.replace(',', ' ')


def _card(profile: Profile, query: Query, score: float, quote: str) -> dict:
    facts = [f'В каталоге нет занятости на {query.event_date}',
             f'формат «{query.event_format}» указан',
             f'цена от {money(profile["price_from_kzt"])} ₸ при бюджете {money(query.budget_kzt)} ₸']
    if query.language:
        facts.append(f'язык: {query.language}')
    if query.hours is not None:
        facts.append('длительность присутствия неприменима (max_hours = null)'
                     if profile['max_hours'] is None else
                     f'лимит {profile["max_hours"]:g} ч при запросе {query.hours:g} ч')
    # The neural network selects this actual source span. It does not generate
    # facts, reviews, availability or prices; descriptions are self-reports.
    excerpt = quote if len(quote) <= 320 else quote[:317].rsplit(' ', 1)[0] + '…'
    warnings = []
    if profile['synthetic']:
        warnings.append('Синтетический профиль организаторов.')
    if profile['price_imputed']:
        warnings.append('Цена проставлена при подготовке датасета, не подтверждена подрядчиком.')
    if profile['city_imputed']:
        warnings.append('Город проставлен при подготовке датасета.')
    return {
        'id': profile['id'], 'name': profile['anon_name'],
        'category': next(c for c in profile['categories']
                         if normalized(c) == query.category),
        'categories': profile['categories'], 'city': profile['city'],
        'price_from_kzt': profile['price_from_kzt'],
        'languages': profile['languages'], 'max_hours': profile['max_hours'],
        'semantic_score': score,
        'explanation': '; '.join(facts) + f'. ИИ выделил фрагмент описания: «{excerpt}»',
        'description_excerpt': quote,
        'flags': {k: profile[k] for k in FLAG_FIELDS},
        'warnings': warnings,
    }


class Recommender:
    def __init__(self, profiles: list[Profile], encoder_factory: Callable[[], Encoder],
                 cache_dir: Path | None = ROOT / 'cache'):
        self.profiles = sorted(profiles, key=lambda p: p['id'])
        self.dataset_hash = fingerprint(self.profiles)
        self.factory = encoder_factory
        self._encoder: Encoder | None = None
        self.result_cache = JsonCache(cache_dir / 'results' if cache_dir else None)
        self.profile_vectors: dict[str, tuple[list[str], list[list[float]]]] = {}
        # Source changes invalidate result cache, even when version was not bumped.
        self.code_hash = fingerprint({name: (ROOT / 'hackalem' / name).read_text(encoding='utf-8')
                                      for name in ('catalog.py', 'recommender.py', 'ai_model.py')})

    @property
    def encoder(self) -> Encoder:
        if self._encoder is None:
            self._encoder = self.factory()
        return self._encoder

    def _profile_index(self, profile: Profile) -> tuple[list[str], list[list[float]]]:
        if profile['id'] not in self.profile_vectors:
            chunks = self.encoder.chunks(profile['description'])
            self.profile_vectors[profile['id']] = (
                chunks, [self.encoder.embed(chunk) for chunk in chunks])
        return self.profile_vectors[profile['id']]

    def prepare(self, progress: Callable[[str], None] | None = None) -> None:
        _ = self.encoder
        for n, profile in enumerate(self.profiles, 1):
            self._profile_index(profile)
            if progress and (n % 10 == 0 or n == len(self.profiles)):
                progress(f'Проанализировано профилей: {n}/{len(self.profiles)}')

    def recommend(self, query: Query) -> dict:
        base = [p for p in self.profiles if belongs(p, query)]
        eligible, exclusions = [], []
        for p in base:
            reasons = rejection_reasons(p, query)
            if reasons:
                exclusions.append({'id': p['id'], 'name': p['anon_name'], 'reasons': reasons})
            else:
                eligible.append(p)
        counts = Counter(reason for item in exclusions for reason in item['reasons'])
        if not base:
            status = 'no_category_in_city'
            message = f'В каталоге нет категории «{query.category}» в городе «{query.city}».'
        elif not eligible:
            status = 'no_matches'
            message = f'Кандидатов в городе и категории: {len(base)}, но никто не проходит все условия.'
        else:
            status = 'found'
            message = f'Подходит {len(eligible)} из {len(base)}. Показано {min(3, len(eligible))}.'
            if len(eligible) < 3:
                message += (f' В этом городе и категории всего {len(base)} профилей.'
                            if len(base) < 3 else ' Остальные исключены по обязательным условиям.')
        if counts:
            message += ' Причины: ' + '; '.join(
                f'{REASONS[key]} — {counts[key]}' for key in REASONS if counts[key]) + '.'
            message += ' У одного профиля может быть несколько причин.'
        result = {
            'status': status, 'message': message, 'query': query.as_dict(),
            'city_category_count': len(base), 'eligible_count': len(eligible),
            'cards': [], 'exclusions': exclusions,
            'exclusion_counts': {r: counts[r] for r in REASONS if counts[r]},
            'dataset_sha256': self.dataset_hash, 'app_version': APP_VERSION,
            'model': None, 'ai_used': False,
            'ranking_rule': 'semantic_score DESC (6 decimals), price_from_kzt ASC, id ASC',
            'score_formula': '0.7 * best_chunk_cosine + 0.3 * mean_chunk_cosine',
            'notice': 'Оценка ИИ — смысловая близость, не вероятность и не оценка качества. '
                      'Цена «от» не является окончательной сметой; '
                      'доступность — только по учебному календарю. '
                      'Пожелания учитываются как предпочтение, не как подтверждённая услуга.',
        }
        # With no candidates there is nothing to analyze; no fake AI score.
        if not eligible:
            return result
        encoder = self.encoder
        key = fingerprint({'query': query.as_dict(), 'dataset': self.dataset_hash,
                           'model': encoder.identity, 'version': APP_VERSION,
                           'code': self.code_hash})
        cached = self.result_cache.get(key)
        if isinstance(cached, dict):
            return cached
        query_vector = unit_mean([encoder.embed(text) for text in encoder.chunks(query.semantic_text())])
        ranked = []
        for profile in eligible:
            chunks, vectors = self._profile_index(profile)
            scores = [cosine(query_vector, vector) for vector in vectors]
            # Earlier source span is the tie-break for explanation extraction.
            best = max(range(len(scores)), key=lambda i: (round(scores[i], 10), -i))
            score = round(BEST_CHUNK_WEIGHT * scores[best] +
                          MEAN_CHUNK_WEIGHT * (math.fsum(scores) / len(scores)), 6)
            ranked.append((score, profile, chunks[best]))
        ranked.sort(key=lambda item: (-item[0], item[1]['price_from_kzt'], item[1]['id']))
        result['cards'] = [_card(p, query, score, quote) for score, p, quote in ranked[:3]]
        result['model'] = encoder.label
        result['model_fingerprint'] = encoder.identity
        result['ai_used'] = True
        self.result_cache.put(key, result)
        return result
