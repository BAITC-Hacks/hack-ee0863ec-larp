# Сайт и отдельный сервер каталога

Запуск из папки проекта в PowerShell:

```powershell
.\.venv\Scripts\python.exe run_web.py
```

Откроется http://127.0.0.1:8000. Для остановки нажмите Ctrl+C в терминале.
Модель и зависимости уже установлены. На новом компьютере установите requirements.txt
и выполните main.py --prepare, как описано в [README.md](../README.md).

## Устройство

- hackalem/catalog_server.py: отдельный процесс на 127.0.0.1:8001, каталог в SQLite.
- hackalem/web_server.py: сайт и API подбора на 127.0.0.1:8000; получает каталог по HTTP.
- data/catalog.sqlite3: постоянная база подрядчиков, создаётся из CSV при первом запуске.
- web/index.html: адаптивная форма, карточки результатов и просмотр каталога.
- run_web.py: запускает оба процесса, открывает браузер, завершает процессы при Ctrl+C.

CSV используется только для первоначального заполнения пустой базы.
Изменение CSV после этого не меняет серверный каталог. Таблица contractors содержит
id и JSON profile с исходными полями подрядчика. Сайт предоставляет просмотр и подбор;
редактирование каталога через сайт пока не реализовано.
Консоль и сайт по умолчанию используют одну базу `data/catalog.sqlite3`.
Для отдельного файла в консоли можно явно передать `--catalog путь.csv`.

## Обновление каталога

Из корня проекта выполните:

```powershell
.\.venv\Scripts\python.exe -m scripts.import_catalog data/catalog.csv
```

Команда полностью заменяет каталог содержимым файла. Сначала проверяются все записи;
при ошибке старые данные сохраняются. Сайт увидит обновление при следующем запросе,
консоль — при следующем запуске. Это локальная административная команда, а не публичный API записи.

## Надёжность и ограничения

Запуск проверяет свободные порты и уникальный идентификатор каждого процесса.
Перед готовностью сайта загружаются и проверяются обе копии модели.
При отсутствии модели выполните `main.py --prepare`.

Одновременно выполняются до двух подборов. При занятости всех работников API
возвращает HTTP 429 с Retry-After. Ограничение поиска: 30 запросов в минуту с одного IP.
HTTP-сервер ограничен 24 соединениями; тайм-аут чтения — 10 секунд.
Неизменившийся каталог передаётся с HTTP 304 без повторной отправки данных.

Кэш каждого типа ограничен 2048 файлами, 64 МиБ и сроком 7 дней.
В памяти каждого работника сохраняется до 1024 эмбеддингов.
Две копии модели требуют больше памяти, чем прежняя одна.

Оценка качества подбора: [инструкция](EVALUATION.md).

Сервер каталога: GET /contractors, GET /health.
Сайт: GET /api/options, GET /api/catalog, POST /api/recommend, GET /health.
POST принимает поля Query, как в examples/dense.json.

## Отдельный фронтенд

По умолчанию разрешён интерфейс с того же адреса, что и API. Для фронтенда
на отдельном порту укажите его точный origin (схема, хост и порт, без пути):

```powershell
.\.venv\Scripts\python.exe run_web.py --allow-origin http://localhost:5173 --allow-origin http://127.0.0.1:5173
```

Фронтенд обращается к `http://127.0.0.1:8000/api/options` и
`http://127.0.0.1:8000/api/recommend`. Для POST отправляйте JSON и
`Content-Type: application/json`. Предварительный OPTIONS возвращает 204;
заголовки CORS присутствуют и на ответах с ошибкой для разрешённого origin.
Другие origins остаются запрещены, wildcard и cookies для CORS не включены.
Для отдельного запуска `python -m hackalem.web_server` доступен тот же флаг.

Новые поля карточки: `preference_checks` (пожелание, supported/conflict/unknown,
исходный фрагмент) и `preference_conflicts` (количество прямых противоречий).
`supported` означает только прямое утверждение в описании, а не проверенную услугу.
Фронтенд должен показывать `warnings`, особенно при конфликте или отсутствии
подтверждения. Старые поля карточек сохранены. `semantic_score` не включает
правило снижения приоритета за противоречия; точный порядок описан в `ranking_rule`.

Сервисы можно запускать отдельно в двух терминалах:

```powershell
.\.venv\Scripts\python.exe -m hackalem.catalog_server
.\.venv\Scripts\python.exe -m hackalem.web_server --catalog-url http://127.0.0.1:8001
```

Это локальный сайт, доступный на этом компьютере. Для публикации в интернете нужны
отдельное развёртывание и сервер, рассчитанный на публичный доступ.

## Review fixes

Search can exclude synthetic profiles from results, suggestions and catalogue display.
Budgets use exact decimal validation. Invalid Unicode, duplicate JSON fields and
nonfinite JSON numbers are rejected. Conditional promises remain unconfirmed.
Suggestions now include larger budgets and combined date/budget alternatives.
Browser requests time out after 30 seconds and display explicit retry guidance.

Imports back up a nonempty database into data/backups before replacement. Restore:

    .\.venv\Scripts\python.exe -m scripts.restore_catalog data/backups/catalog-TIMESTAMP.sqlite3

Restore backs up the current data too. Backups are excluded from Git; copy them
to separate storage and remove older backups manually when appropriate.
Cache cleanup scans periodically or at tracked capacity instead of every write.
Across multiple processes limits are soft until the next scan (30 seconds of writes).

Remaining product limits: the existing 2026 calendar is the only known availability.
Real-time calendar integration, verified contacts, booking and payment are not implemented.
Recommendation quality still needs human-rated examples; see EVALUATION.md.
