"""Conservative checks for explicit Russian contest/game preferences.

This is a small, inspectable rule layer, not a general language understanding
model. Qualified, mixed and double-negative statements remain unconfirmed.
Structured eligibility is never changed by these soft-preference checks.
"""
import re
from hackalem.catalog import normalized

CONCEPTS = (
    ('contests', 'конкурсов', r'конкурс(?:ы|ов|а|ами|ах|е|у|ом)?'),
    ('games', 'игр', r'игр(?:а|ы|у|е|ой|ою|ам|ами|ах)?'),
)
NEGATIVE = re.compile(r'\b(?:без|не|нет|никаких|никогда)\b')
OFFER = re.compile(r'\b(?:провожу|проводим|предлагаю|предлагаем|организую|организуем|устраиваю|устраиваем)\b')


def clauses(text):
    return [part.strip() for part in re.split(r'[.!?;\n]+|\s+(?:но|однако|зато)\s+', text) if part.strip()]


def absence(text, noun):
    """Only unqualified absences; 'без банальных конкурсов' is narrower."""
    if re.search(r'\b(?:если|могу|можем|возможно|только|доплат\w*|по запросу|при условии)\b', text):
        return False
    direct = rf'\b(?:без|никаких)\s+(?:{noun})\b|\b(?:{noun})\s+нет\b'
    # Carry 'без' through a plain list, but not through adjectives or a verb.
    coordinated = rf'\bбез\s+(?:конкурсов|игр)\s+и\s+(?:{noun})\b'
    refused = rf'\bне\s+(?:хочу|нужны|провожу|проводим|предлагаю|предлагаем)\s+(?:{noun})\b'
    for match in re.finditer(f'(?:{direct}|{coordinated}|{refused})', text):
        # Do not read 'не работаю без конкурсов' as an absence promise.
        if not re.search(r'\b(?:не|нет|никогда)\b', text[:match.start()]):
            return True
    return False


def requests(preferences):
    output = []
    parts = clauses(normalized(preferences))
    for key, label, noun in CONCEPTS:
        negative = any(absence(part, noun) for part in parts)
        positive = any(re.search(rf'\b(?:{noun})\b', part) and not NEGATIVE.search(part)
                       and re.search(r'\b(?:хочу|нужны|нужен|нужна|нужно|с)\b', part)
                       for part in parts)
        if negative and positive:
            output.append({'key': key, 'label': f'Пожелание о {label}', 'want': None, 'noun': noun})
        elif negative or positive:
            output.append({'key': key, 'label': ('Без ' if negative else 'Наличие ') + label,
                           'want': not negative, 'noun': noun})
    return output


def assess(preferences, description):
    checks = []
    for request in requests(preferences):
        statements = []
        for source in clauses(description):
            text = normalized(source)
            if absence(text, request['noun']):
                statements.append((False, source))
            # Only an explicit offer is positive evidence; a noun on its own is not.
            elif not NEGATIVE.search(text) and OFFER.search(text) and re.search(rf'\b{request["noun"]}\b', text):
                statements.append((True, source))
        polarities = {value for value, _ in statements}
        status, evidence = 'unknown', ''
        if request['want'] is not None and len(polarities) == 1:
            polarity = next(iter(polarities))
            status = 'supported' if polarity == request['want'] else 'conflict'
            evidence = statements[0][1]
        checks.append({'preference': request['label'], 'status': status, 'source_excerpt': evidence})
    return checks
