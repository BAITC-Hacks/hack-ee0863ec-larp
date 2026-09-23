# Источники и происхождение

## Материалы пользователя

- `HackAlem AI_ Хакатон-задача_ умный подбор подрядчиков.docx`.
  Требования: город, дата, тип, категория, бюджет; опциональные часы/язык;
  до 3 записей, объяснение, занятость, три исхода, детерминизм.
  Дообучение на 66 строках исключено; готовые эмбеддинги разрешены.
- `hackathon dataset anonymized .csv` — единственный каталог профилей.
  Побайтовая копия включена в `data/catalog.csv`.
  SHA-256: `6a724b6b7dfb5973343e68ba18dadb60fc807d87e3d78f03ee86fb26cb089f7d`.

Внешние источники ниже использованы только для технической реализации,
а не для дополнения или исправления данных подрядчиков.

## Предобученная нейросеть

Sentence Transformers, `paraphrase-multilingual-MiniLM-L12-v2`.
Описание: семантические эмбеддинги размерности 384; masked mean pooling;
максимальная длина SentenceTransformer 128 токенов. Лицензия Apache-2.0.

https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

Зафиксированная ревизия: `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`.
Веса квантованной ONNX-модели (~118 MB), хеш подтверждён страницей файла:

https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/blob/e8f8c211226b894fcb81acc59f3b34ba3efd5f42/onnx/model_quint8_avx2.onnx

Токенизатор (~9.08 MB), хеш подтверждён страницей файла:

https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/blob/e8f8c211226b894fcb81acc59f3b34ba3efd5f42/tokenizer.json

Веса не изменены/не дообучены и не входят в архив. Загрузчик получает
публичные файлы авторов и проверяет SHA-256 перед использованием.
Объяснения в проекте извлекаются из данных, а не цитируют документацию модели.

## Runtime и токенизация

Настройка CPU-потоков и ORT_SEQUENTIAL:
https://onnxruntime.ai/docs/performance/tune-performance/threading.html

Версия ONNX Runtime с wheel для Python 3.13 / Windows x86-64:
https://pypi.org/project/onnxruntime/1.23.2/

Tokenizers, загрузка сохранённого tokenizer.json и кодирование:
https://pypi.org/project/tokenizers/0.22.1/

## Решения этой реализации, не требования организаторов

- Python, ONNX CPU и конкретная версия MiniLM.
- Дополнительное необязательное поле `preferences`.
- Язык/длительность как строгие ограничения при их заполнении.
- Запрет дат вне известного окна.
- Ранжирование `0.7 * max + 0.3 * mean` сходства фрагментов.
- Разрешение равенства через цену и ID; JSON-кэш; проверка SHA-256.
