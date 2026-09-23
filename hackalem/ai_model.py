"""Real pretrained multilingual MiniLM, ONNX CPU inference, no remote API.

Reference mean pooling: model card in docs/SOURCES.md. We pin the revision and
SHA-256 of every downloaded artifact. No substitute model or lexical fallback.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

# Set before importing NumPy / ONNX / the Rust tokenizer.
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
             'NUMEXPR_NUM_THREADS'):
    os.environ[_key] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'

from hackalem.cache_store import JsonCache
from hackalem.catalog import ROOT, clean, fingerprint


class ModelError(RuntimeError):
    """Expected model/dependency/download failure with actionable CLI message."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _log(text: str) -> None:
    print(text, file=sys.stderr)


def ensure_model(folder: Path, *, offline: bool = False,
                 log: Callable[[str], None] = _log) -> dict:
    lock = json.loads((ROOT / 'config/model.lock.json').read_text(encoding='utf-8'))
    folder.mkdir(parents=True, exist_ok=True)
    for item in lock['files']:
        dest = folder / item['local']
        if dest.exists():
            if sha256_file(dest) != item['sha256']:
                raise ModelError(f'Контрольная сумма {dest.name} не совпала. '
                                 f'Удалите повреждённый файл {dest} и повторите запуск.')
            continue
        if offline:
            raise ModelError('Локальная модель отсутствует. С интернетом выполните: '
                             'python main.py --prepare')
        url = (f"https://huggingface.co/{lock['repository']}/resolve/"
               f"{lock['revision']}/{item['remote']}")
        log(f"Загрузка {item['local']} с Hugging Face (один раз)...")
        fd, temp_name = tempfile.mkstemp(dir=folder, suffix='.part')
        os.close(fd)
        temp = Path(temp_name)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'HackAlem-CLI/1.0'})
            digest = hashlib.sha256()
            received = 0
            step = 0
            with urllib.request.urlopen(request, timeout=60) as response, temp.open('wb') as output:
                for chunk in iter(lambda: response.read(1024 * 1024), b''):
                    received += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
                    if received // (20 * 1024 * 1024) > step:
                        step = received // (20 * 1024 * 1024)
                        log(f'  Получено {received // (1024 * 1024)} MiB...')
            if digest.hexdigest() != item['sha256']:
                raise ModelError(f'Неверная контрольная сумма загрузки {item["local"]}. '
                                 'Непроверенная модель не будет запущена.')
            os.replace(temp, dest)
        except (OSError, urllib.error.URLError) as exc:
            raise ModelError('Не удалось скачать модель. Нужен доступ к huggingface.co '
                             'и его хранилищу файлов. Проверьте интернет и повторите '
                             f'python main.py --prepare. Причина: {exc}') from exc
        finally:
            temp.unlink(missing_ok=True)
    return lock


class MiniLMEncoder:
    """128-token sequences, batch size 1, CPU/sequential/single-thread inference."""

    def __init__(self, model_dir: Path = ROOT / 'models', *,
                 cache_dir: Path | None = ROOT / 'cache', offline: bool = False):
        try:
            import numpy as np
            import onnxruntime as ort
            import tokenizers
            from tokenizers import Tokenizer
        except (ImportError, OSError) as exc:
            raise ModelError('Не загружаются зависимости ИИ. Установите Python 3.11–3.13 '
                             '(64-bit) и выполните: python -m pip install -r requirements.txt. '
                             f'Подробности: {exc}') from exc
        self.np = np
        self.lock = ensure_model(model_dir, offline=offline)
        self.max_tokens = self.lock['max_tokens']
        self.dimension = self.lock['dimension']
        # One tokenizer without truncation for exact chunk boundaries, another
        # with fixed-length padding for identical activation quantization.
        self.splitter = Tokenizer.from_file(str(model_dir / 'tokenizer.json'))
        self.splitter.no_truncation()
        self.splitter.no_padding()
        self.tokenizer = Tokenizer.from_file(str(model_dir / 'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=self.max_tokens)
        pad_id = self.tokenizer.token_to_id('<pad>')
        if pad_id is None:
            raise ModelError('Не найден <pad> в зафиксированном токенизаторе.')
        self.tokenizer.enable_padding(length=self.max_tokens, pad_id=pad_id, pad_token='<pad>')
        settings = ort.SessionOptions()
        settings.intra_op_num_threads = 1
        settings.inter_op_num_threads = 1
        settings.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        settings.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        settings.log_severity_level = 3
        try:
            self.session = ort.InferenceSession(str(model_dir / 'model.onnx'),
                                                sess_options=settings,
                                                providers=['CPUExecutionProvider'])
        except Exception as exc:
            raise ModelError(f'ONNX Runtime не смог загрузить модель: {exc}') from exc
        self.inputs = {item.name for item in self.session.get_inputs()}
        if not self.inputs <= {'input_ids', 'attention_mask', 'token_type_ids'}:
            raise ModelError(f'Неожиданные входы ONNX: {self.inputs}')
        self.identity = fingerprint({'model': self.lock, 'pooling': 'masked-mean-l2-f64',
                                     'batch_size': 1, 'ort': ort.__version__,
                                     'tokenizers': tokenizers.__version__,
                                     'numpy': np.__version__, 'encoder_version': 1})
        self.label = self.lock['repository']
        self.cache = JsonCache(cache_dir / 'embeddings' if cache_dir else None)
        self.memory = OrderedDict()
        self.memory_limit = 1024

    def chunks(self, text: str) -> list[str]:
        """Keep all description text; split sentences, then long spans by tokens."""
        text = clean(text)
        if not text:
            raise ValueError('Нельзя анализировать пустой текст.')
        segments = re.split(r'(?<=[.!?…])\s+', text)
        output: list[str] = []
        # Reserve 4 positions for special tokens and any retokenization changes.
        limit = self.max_tokens - 4
        for segment in segments:
            encoded = self.splitter.encode(segment, add_special_tokens=False)
            if not encoded.ids:
                continue
            for start in range(0, len(encoded.ids), limit):
                end = min(start + limit, len(encoded.ids))
                left = encoded.offsets[start][0]
                right = encoded.offsets[end - 1][1]
                piece = segment[left:right].strip()
                if piece:
                    output.append(piece)
        return output or [text]

    def remember(self, key, value):
        self.memory[key] = value
        self.memory.move_to_end(key)
        while len(self.memory) > self.memory_limit:
            self.memory.popitem(last=False)

    def embed(self, text: str) -> list[float]:
        text = clean(text)
        key = fingerprint({'encoder': self.identity, 'text': text})
        if key in self.memory:
            self.memory.move_to_end(key)
            return list(self.memory[key])
        stored = self.cache.get(key)
        if isinstance(stored, list) and len(stored) == self.dimension and all(
                isinstance(v, (int, float)) and math.isfinite(v) for v in stored):
            self.remember(key, stored)
            return list(stored)
        # Refuse silent truncation; all callers must use chunks() first.
        size = len(self.splitter.encode(text).ids)
        if size > self.max_tokens:
            raise ModelError('Текст превысил окно модели. Требуется разбиение на фрагменты.')
        enc = self.tokenizer.encode(text)
        np = self.np
        values = {'input_ids': np.array([enc.ids], dtype=np.int64),
                  'attention_mask': np.array([enc.attention_mask], dtype=np.int64),
                  'token_type_ids': np.array([enc.type_ids], dtype=np.int64)}
        try:
            token_vectors = self.session.run(None, {k: values[k] for k in self.inputs})[0]
        except Exception as exc:
            raise ModelError(f'Ошибка вычисления нейросети: {exc}') from exc
        if token_vectors.ndim != 3 or token_vectors.shape[2] != self.dimension:
            raise ModelError(f'Неожиданная форма выхода ONNX: {token_vectors.shape}')
        mask = values['attention_mask'][..., None].astype(np.float64)
        pooled = (token_vectors.astype(np.float64) * mask).sum(axis=1)[0] / mask.sum()
        norm = math.sqrt(math.fsum(float(v) * float(v) for v in pooled))
        if not math.isfinite(norm) or norm == 0:
            raise ModelError('Модель вернула некорректный вектор.')
        result = [float(v) / norm for v in pooled]
        self.remember(key, result)
        self.cache.put(key, result)
        return list(result)
