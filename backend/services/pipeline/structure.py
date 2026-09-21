# backend/services/pipeline/structure.py
"""
Stage 1: 文書構造抽出（Document structure extraction）

ルールベースで完結させ、LLMを使わない。理由:
  - 出力される各チャンクは必ず元文書の実在の部分文字列になる、という不変条件を
    構造的に保証できる（LLMに書かせると要約・言い換えが混ざり、出典の捏造リスクが生じる）
  - 高速・決定的・無料

対応パターン:
  1. 「第N条」のような条文番号で区切れる場合はそれを使う
  2. 空行区切りの段落が複数あればそれを使う
  3. 1つの塊しかなく、かつ長い場合は文単位でさらに分割する
  4. それでも分割できなければ全体を1チャンクとする
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from backend.services.pipeline.schema import DocumentChunk

_ARTICLE_PATTERN = re.compile(r"(第[0-90-9]+条(?:\([^)（]*\))?)")
_MAX_CHUNK_CHARS = 200


def decompose_document(text: str) -> List[DocumentChunk]:
    text = text.strip()
    if not text:
        return []

    by_article = _split_by_article(text)
    if by_article:
        return by_article

    by_paragraph = _split_by_paragraph(text)
    if by_paragraph:
        return by_paragraph

    by_sentence = _split_by_sentence(text)
    if by_sentence:
        return by_sentence

    return [DocumentChunk(chunk_id="chunk_1", text=text)]


def _split_by_article(text: str) -> List[DocumentChunk]:
    matches = list(_ARTICLE_PATTERN.finditer(text))
    if not matches:
        return []

    raw: List[Tuple[Optional[str], str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            raw.append((None, preamble))

    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk_text = text[start:end].strip()
        if chunk_text:
            raw.append((m.group(1), chunk_text))

    return [
        DocumentChunk(chunk_id=f"chunk_{i + 1}", text=t, heading=h)
        for i, (h, t) in enumerate(raw)
    ]


def _split_by_paragraph(text: str) -> List[DocumentChunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) <= 1:
        return []
    return [DocumentChunk(chunk_id=f"chunk_{i + 1}", text=p) for i, p in enumerate(paragraphs)]


def _split_by_sentence(text: str) -> List[DocumentChunk]:
    if len(text) <= _MAX_CHUNK_CHARS * 1.5:
        return []

    sentences = [s for s in re.split(r"(?<=。)", text) if s.strip()]
    if len(sentences) <= 1:
        return []

    merged: List[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) > _MAX_CHUNK_CHARS:
            merged.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        merged.append(buf)

    if len(merged) <= 1:
        return []

    return [DocumentChunk(chunk_id=f"chunk_{i + 1}", text=c.strip()) for i, c in enumerate(merged)]
