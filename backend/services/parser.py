# backend/services/parser.py
"""
TASK-002: ドキュメント解析モジュール (タイムアウトガードレール付き)

対応フォーマット:
  - PDF  (.pdf)  : PyMuPDF で各ページのテキストを抽出
  - Word (.docx) : python-docx で段落テキストを抽出
  - テキスト (.txt / .md) : UTF-8 デコードそのまま返却

制約:
  - 最大ファイルサイズ: 20 MB（MAX_UPLOAD_SIZE）
  - LLM保護用の最大抽出文字数: 5,000文字（MAX_EXTRACT_CHARS）
"""

import io
import os
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document

MAX_UPLOAD_SIZE: int = int(os.getenv("MAX_UPLOAD_SIZE", 20 * 1024 * 1024))  # 20 MB

# 💡 【タイムアウト対策】LLM（Ollama）のパンクを防ぐ最大文字数の制限値
MAX_EXTRACT_CHARS: int = int(os.getenv("MAX_EXTRACT_CHARS", 5000))


class UnsupportedFileTypeError(ValueError):
    """サポートされていないファイル形式"""


class FileTooLargeError(ValueError):
    """ファイルサイズ超過"""


def parse_document(filename: str, file_bytes: bytes) -> str:
    _validate_size(file_bytes)
    ext = Path(filename).suffix.lower()
    
    # 各フォーマットからテキストを抽出
    if ext == ".pdf":
        text = _extract_pdf(file_bytes)
    elif ext in (".docx",):
        text = _extract_docx(file_bytes)
    elif ext in (".txt", ".md"):
        text = _extract_text(file_bytes)
    else:
        raise UnsupportedFileTypeError(
            f"未対応のファイル形式です: {ext}。"
            "対応形式: PDF / Word (.docx) / テキスト (.txt, .md)"
        )
        
    # 💡 【バグ・タイムアウト対策】抽出テキストが空、または画像PDFだった場合のガード
    if not text.strip():
        raise ValueError(
            f"ファイル「{filename}」からテキストを抽出できませんでした。"
            "中身が空か、スキャンされた画像ベースのファイルである可能性があります。"
        )
        
    # 💡 【重要】Ollamaの処理負荷を下げ、504エラーを防ぐための文字数カット
    if len(text) > MAX_EXTRACT_CHARS:
        text = text[:MAX_EXTRACT_CHARS] + "\n\n... [システム警告: 仕様書が長すぎるため、これ以降のテキストはタイムアウト防止のため省略されました] ..."

    return text


def _validate_size(file_bytes: bytes) -> None:
    size = len(file_bytes)
    if size > MAX_UPLOAD_SIZE:
        mb = MAX_UPLOAD_SIZE // (1024 * 1024)
        raise FileTooLargeError(
            f"ファイルサイズ ({size / 1024 / 1024:.1f} MB) が上限 {mb} MB を超えています。"
        )


def _extract_pdf(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(pages).strip()


def _extract_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs).strip()


def _extract_text(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="replace").strip()