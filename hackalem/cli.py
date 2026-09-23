"""Interactive console for the supplied HackAlem catalogue."""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path
from typing import Callable, TypeVar

# ai_model sets CPU/threading environment before optional numerical imports.
from hackalem.ai_model import MiniLMEncoder, ModelError
from hackalem.catalog import (ROOT, Query, canonical_json, clean, event_date, load_catalog,
                     normalized, parse_budget, parse_hours)
from hackalem.recommender import Recommender, money

T = TypeVar('T')


def render(result: dict) -> str:
    lines = ['=' * 76, 'РЕЗУЛЬТАТ ПОДБОРА', result['message']]
    for n, card in enumerate(result['cards'], 1):
        flags = ' [СИНТЕТИЧЕСКИЙ ПРОФИЛЬ]' if card['flags']['synthetic'] else ''
        lines += ['', f'{n}. {card["name"]} | {card["id"]}{flags}',
                  f'   {card["category"]} | {card["city"]} | от {money(card["price_from_kzt"])} ₸',
                  f'   Смысловая близость ИИ: {card["semantic_score"]:.6f} (не вероятность)',
                  textwrap.fill(card['explanation'], width=100, initial_indent='   ', subsequent_indent='   ')]
        for warning in card['warnings']:
            lines.append('   Важно: ' + warning)
    if result.get('suggestions'):
        lines += ['', 'ОТДЕЛЬНЫЕ ПРЕДЛОЖЕНИЯ — исходные условия не изменены.']
        for n, suggestion in enumerate(result['suggestions'], 1):
            lines.append(f'{n}. {suggestion["message"]} Подойдут по обязательным условиям: {suggestion["eligible_count"]}.')
            for profile in suggestion['profiles']:
                lines.append(f'   {profile["name"]} | {profile["id"]}')
                lines.extend('   Важно: ' + warning for warning in profile['warnings'])
    lines += ['', result['notice']]
    if result['ai_used']:
        lines.append('Модель: ' + result['model'])
    else:
        lines.append('Нейросеть не запускалась: после обязательных проверок кандидатов нет.')
    lines.append('=' * 76)
    return '\n'.join(lines)


def _ask(label: str, parser: Callable[[str], T], default: str | None = None) -> T:
    while True:
        suffix = f' [{default}]' if default is not None else ''
        text = input(label + suffix + ': ').strip()
        if normalized(text) in ('выход', 'exit', 'quit'):
            raise EOFError
        if not text and default is not None:
            text = default
        try:
            return parser(text)
        except (ValueError, TypeError) as exc:
            print('Ошибка ввода:', exc)


def _choose(label: str, values: list[str], default: str) -> str:
    print(label + ': ' + '; '.join(f'{n} — {v}' for n, v in enumerate(values, 1)))
    def parse(text: str) -> str:
        if text.isdigit() and 1 <= int(text) <= len(values):
            return values[int(text) - 1]
        found = next((v for v in values if normalized(v) == normalized(text)), None)
        if found is None:
            raise ValueError('Выберите номер или название из списка.')
        return found
    return _ask(label, parse, default)


def read_interactive_query(profiles: list[dict]) -> Query:
    # Defaults form a real query with >=3 eligible profiles, not fabricated rows.
    city = _choose('Город', sorted({p['city'] for p in profiles}), 'Алматы')
    categories = sorted({v for p in profiles for v in p['categories']})
    category = _choose('Категория', categories, 'Ведущий')
    when = _ask('Дата (23.09.2026—31.12.2026)', event_date, '14.11.2026')
    formats = sorted({v for p in profiles for v in p['event_formats']})
    fmt = _choose('Тип мероприятия', formats, 'корпоратив')
    budget = _ask('Бюджет в тенге', parse_budget, '1200000')
    hours = _ask('Длительность в часах (Enter — без ограничения)', parse_hours)
    languages = sorted({v for p in profiles for v in p['languages']})
    print('Языки: ' + ', '.join(languages))
    def language(text: str) -> str | None:
        if not text:
            return None
        found = next((v for v in languages if normalized(v) == normalized(text)), None)
        if found is None:
            raise ValueError('Укажите один язык из списка или оставьте поле пустым.')
        return found
    lang = _ask('Язык (Enter — без ограничения)', language)
    def preferences(text: str) -> str:
        text = clean(text)
        if len(text) > 2000:
            raise ValueError('Не более 2000 символов.')
        return text
    prefs = _ask('Пожелания для ИИ (необязательно)', preferences)
    return Query(city, when, fmt, category, budget, hours, lang, prefs)


def arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='HackAlem: до 3 подрядчиков с анализом описаний предобученной MiniLM.')
    parser.add_argument('--catalog', type=Path, default=None, help='CSV или JSONL')
    parser.add_argument('--database', type=Path, default=ROOT / 'data/catalog.sqlite3', help='Shared SQLite catalogue')
    parser.add_argument('--model-dir', type=Path, default=ROOT / 'models')
    parser.add_argument('--cache-dir', type=Path, default=ROOT / 'cache')
    parser.add_argument('--offline', action='store_true', help='Запретить скачивание отсутствующих весов')
    parser.add_argument('--no-cache', action='store_true', help='Не читать/писать постоянный кэш')
    parser.add_argument('--json', action='store_true', help='Чистый JSON в stdout для --query/--demo')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--query', type=Path, help='Один запрос из JSON')
    mode.add_argument('--demo', action='store_true', help='Все примеры из examples/')
    mode.add_argument('--prepare', action='store_true', help='Скачать модель и проиндексировать каталог')
    mode.add_argument('--list-options', action='store_true', help='Города/категории/форматы без запуска ИИ')
    return parser


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = arguments()
    args = parser.parse_args()
    if args.json and not (args.query or args.demo):
        parser.error('--json используется с --query или --demo.')
    try:
        if args.catalog:
            profiles = load_catalog(args.catalog)
        else:
            from hackalem.catalog_store import initialize_database, read_profiles
            initialize_database(args.database)
            profiles = read_profiles(args.database)
        if args.list_options:
            print(json.dumps({
                'profiles': len(profiles), 'cities': sorted({p['city'] for p in profiles}),
                'categories': sorted({v for p in profiles for v in p['categories']}),
                'event_formats': sorted({v for p in profiles for v in p['event_formats']}),
                'languages': sorted({v for p in profiles for v in p['languages']}),
            }, ensure_ascii=False, indent=2))
            return 0
        cache = None if args.no_cache else args.cache_dir
        factory = lambda: MiniLMEncoder(args.model_dir, cache_dir=cache, offline=args.offline)
        engine = Recommender(profiles, factory, cache)
        if args.prepare:
            engine.prepare(lambda text: print(text, file=sys.stderr))
            print('Модель и каталог готовы. Дальнейшие запросы можно выполнять с --offline.')
            return 0
        if args.query:
            query = Query(**json.loads(args.query.read_text(encoding='utf-8-sig')))
            result = engine.recommend(query)
            print(canonical_json(result) if args.json else render(result))
            return 0
        if args.demo:
            output = []
            for path in sorted((ROOT / 'examples').glob('*.json')):
                result = engine.recommend(Query(**json.loads(path.read_text(encoding='utf-8'))))
                if args.json:
                    output.append({'example': path.stem, 'result': result})
                else:
                    print('\nПример:', path.stem)
                    print(render(result))
            if args.json:
                print(canonical_json(output))
            return 0
        print(f'HackAlem AI — консольный подбор. В каталоге {len(profiles)} профилей.')
        print('Условия проверяет код; описания анализирует предобученная нейросеть.')
        print('При первом AI-запросе загружаются веса; далее возможна работа без интернета.')
        print('Enter принимает значение в скобках. «выход» завершает программу.\n')
        while True:
            query = read_interactive_query(profiles)
            result = engine.recommend(query)
            print(render(result))
            if result['suggestions']:
                choices = result['suggestions']
                choice = _choose('Применить предложение (0 — оставить условия)',
                                 [str(n) for n in range(len(choices) + 1)], '0')
                if choice != '0':
                    suggestion = choices[int(choice) - 1]
                    query = Query(**(query.as_dict() | (suggestion['changes'] if 'changes' in suggestion else {suggestion['field']: suggestion['suggested_value']})))
                    print(render(engine.recommend(query)))
            reply = input('\nEnter — новый запрос; 0 — выход: ').strip()
            if normalized(reply) in ('0', 'нет', 'n', 'exit', 'quit', 'выход'):
                break
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\nЗавершено.')
        return 0
    except (OSError, ValueError, TypeError, ModelError) as exc:
        print('Ошибка: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
