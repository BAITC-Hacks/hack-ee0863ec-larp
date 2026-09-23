"""Two separate processes, no disk cache: compare actual model results byte for byte."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query', type=Path, default=ROOT / 'examples/dense.json')
    args = parser.parse_args()
    command = [sys.executable, str(ROOT / 'main.py'), '--query', str(args.query.resolve()),
               '--json', '--no-cache', '--offline']
    outputs = []
    for i in range(2):
        print(f'Запуск независимого процесса {i + 1}/2 без кэша...')
        try:
            run = subprocess.run(command, capture_output=True, timeout=600)
        except subprocess.TimeoutExpired:
            print('Проверка не завершилась: превышен лимит ожидания процесса.', file=sys.stderr)
            return 1
        if run.returncode:
            print(run.stderr.decode('utf-8', errors='replace'), file=sys.stderr)
            print('Сначала выполните python main.py --prepare.', file=sys.stderr)
            return 1
        parsed = json.loads(run.stdout)
        if not parsed.get('ai_used'):
            print('Этот запрос не требует ИИ: подходящих кандидатов нет. '
                  'Используйте examples/dense.json.', file=sys.stderr)
            return 1
        outputs.append(run.stdout)
    if outputs[0] != outputs[1]:
        print('FAIL: ответы отличаются.', file=sys.stderr)
        return 1
    cards = json.loads(outputs[0])['cards']
    print('PASS: состав, порядок, оценки и объяснения полностью совпали.')
    print('ID:', ', '.join(card['id'] for card in cards))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
