"""CSV/JSONL parsing and strict event constraints. No network or ML dependency."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WINDOW_START = date(2026, 9, 23)
WINDOW_END = date(2026, 12, 31)
LIST_FIELDS = ('categories', 'event_formats', 'languages', 'busy_dates')
FLAG_FIELDS = ('synthetic', 'city_imputed', 'price_imputed')
REQUIRED = {'id', 'anon_name', 'city', 'price_from_kzt', 'max_hours', 'description',
            *LIST_FIELDS, *FLAG_FIELDS}
REASONS = {
    'busy_date': 'занят на выбранную дату',
    'budget': 'стартовая цена выше бюджета',
    'event_format': 'не берёт этот формат по каталогу',
    'language': 'нужный язык не указан',
    'duration': 'длительность превышает max_hours',
}
Profile = dict[str, Any]


def clean(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('Ожидается текстовое значение.')
    if len(value) > 20000 or any(unicodedata.category(c) in ('Cs', 'Cc') and c not in '\r\n\t' for c in value):
        raise ValueError('Invalid text length or Unicode control character.')
    return ' '.join(unicodedata.normalize('NFKC', value).split())


def normalized(value: str) -> str:
    return clean(value).casefold().replace('ё', 'е')


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def event_date(value: str) -> str:
    value = clean(value)
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            parsed = date.fromisoformat(value)
        elif re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value):
            parsed = datetime.strptime(value, '%d.%m.%Y').date()
        else:
            raise ValueError
    except ValueError as exc:
        raise ValueError('Дата: ГГГГ-ММ-ДД или ДД.ММ.ГГГГ, существующий день.') from exc
    if not WINDOW_START <= parsed <= WINDOW_END:
        raise ValueError('Календарь известен только с 23.09.2026 по 31.12.2026.')
    return parsed.isoformat()


def parse_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and normalized(value) in ('true', 'false'):
        return normalized(value) == 'true'
    raise ValueError(f'Некорректный логический флаг: {value!r}.')


def positive_number(value: Any, label: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{label}: требуется число, не логический флаг.')
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{label}: требуется число.') from exc
    if not math.isfinite(parsed) or parsed < 0 or (parsed == 0 and not allow_zero):
        raise ValueError(f'{label}: требуется конечное {"неотрицательное" if allow_zero else "положительное"} число.')
    return parsed


def parse_budget(value: Any) -> int:
    if isinstance(value, str):
        value = ''.join(clean(value).split())
    if isinstance(value, bool):
        raise ValueError('Budget must be a number, not a boolean.')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Invalid budget.') from exc
    if not amount.is_finite() or amount < 0 or amount > 10**12 or amount != amount.to_integral_value():
        raise ValueError('Бюджет: целое число тенге от 0 до 1 000 000 000 000.')
    return int(amount)


def parse_hours(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        value = clean(value).replace(',', '.')
    return positive_number(value, 'Длительность')


def _profile(raw: dict[str, Any], number: int) -> Profile:
    try:
        if not isinstance(raw, dict):
            raise ValueError('Запись должна быть объектом.')
        if None in raw or REQUIRED - raw.keys():
            raise ValueError('Неверные столбцы или отсутствуют обязательные поля.')
        p = {key: raw[key] for key in REQUIRED}
        for key in ('id', 'anon_name', 'city', 'description'):
            p[key] = clean(p[key])
            if not p[key]:
                raise ValueError(f'Пустое поле {key}.')
        for key in LIST_FIELDS:
            values = p[key].split('|') if isinstance(p[key], str) else p[key]
            if not isinstance(values, list):
                raise ValueError(f'{key}: требуется список или строка с разделителем |.')
            if any(not isinstance(v, str) for v in values):
                raise ValueError(f'{key}: все элементы должны быть строками.')
            values = [clean(v) for v in values if v.strip()]
            if not values and key != 'busy_dates':
                raise ValueError(f'Пустой список {key}.')
            if key == 'busy_dates':
                values = [event_date(v) for v in values]
            p[key] = sorted(set(values), key=lambda v: (normalized(v), v))
        for key in FLAG_FIELDS:
            p[key] = parse_flag(p[key])
        p['price_from_kzt'] = parse_budget(p['price_from_kzt'])
        p['max_hours'] = parse_hours(p['max_hours'])
        return p
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Запись {number}: {exc}') from exc


def load_catalog(path: str | Path = ROOT / 'data/catalog.csv') -> list[Profile]:
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as f:
        if path.suffix.casefold() == '.csv':
            reader = csv.DictReader(f)
            missing = REQUIRED - set(reader.fieldnames or ())
            if missing:
                raise ValueError('В CSV нет полей: ' + ', '.join(sorted(missing)))
            raw_rows = list(reader)
        elif path.suffix.casefold() == '.jsonl':
            raw_rows = [json.loads(line) for line in f if line.strip()]
        else:
            raise ValueError('Поддерживаются файлы .csv и .jsonl.')
    rows = [_profile(raw, n) for n, raw in enumerate(raw_rows, 1)]
    if not rows:
        raise ValueError('Каталог пуст.')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('В каталоге повторяются id.')
    return sorted(rows, key=lambda p: p['id'])


@dataclass(frozen=True)
class Query:
    city: str
    event_date: str
    event_format: str
    category: str
    budget_kzt: int
    hours: float | None = None
    language: str | None = None
    preferences: str = ''
    include_synthetic: bool = True

    def __post_init__(self) -> None:
        if type(self.include_synthetic) is not bool:
            raise ValueError('include_synthetic must be boolean.')
        # Normalize before both cache lookup and inference: equivalent input has
        # identical model text, not just identical cache keys.
        for key in ('city', 'event_format', 'category', 'preferences'):
            value = normalized(getattr(self, key))
            if key != 'preferences' and not value:
                raise ValueError(f'Не заполнено поле {key}.')
            if key == 'preferences' and len(value) > 2000:
                raise ValueError('Пожелания: не более 2000 символов.')
            object.__setattr__(self, key, value)
        object.__setattr__(self, 'event_date', event_date(self.event_date))
        object.__setattr__(self, 'budget_kzt', parse_budget(self.budget_kzt))
        object.__setattr__(self, 'hours', parse_hours(self.hours))
        language = None if self.language is None else normalized(self.language)
        object.__setattr__(self, 'language', language or None)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def semantic_text(self) -> str:
        context = f'{self.category} для мероприятия: {self.event_format}.'
        return f'{context} Пожелания: {self.preferences}' if self.preferences else context


def belongs(profile: Profile, query: Query) -> bool:
    if not query.include_synthetic and profile['synthetic']:
        return False
    return normalized(profile['city']) == query.city and query.category in {
        normalized(v) for v in profile['categories']}


def rejection_reasons(profile: Profile, query: Query) -> list[str]:
    checks = (
        ('busy_date', query.event_date in profile['busy_dates']),
        ('budget', profile['price_from_kzt'] > query.budget_kzt),
        ('event_format', query.event_format not in {normalized(v) for v in profile['event_formats']}),
        ('language', query.language is not None and query.language not in {
            normalized(v) for v in profile['languages']}),
        ('duration', query.hours is not None and profile['max_hours'] is not None
         and query.hours > profile['max_hours']),
    )
    return [reason for reason, failed in checks if failed]
