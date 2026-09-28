# backend/tests/test_parser.py
"""backend/services/parser.py の単体テスト。

`parse_document_full`（Backend依頼_仕様書ファイル変換API.md用、案A: 切り詰めない）
を中心に検証する。既存の`parse_document`（レガシー`/api/tasks/generate`用、
MAX_EXTRACT_CHARSで切り詰める）の挙動は変えていないことも確認する。
"""

import io

import pytest
from docx import Document

from backend.services.parser import (
    MAX_EXTRACT_CHARS,
    FileTooLargeError,
    UnsupportedFileTypeError,
    parse_document,
    parse_document_full,
)


def _docx_bytes(paragraphs) -> bytes:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- parse_document_full: text/docx ---

def test_parse_document_full_reads_txt():
    result = parse_document_full("spec.txt", "仕様書の本文です。".encode("utf-8"))
    assert result.filename == "spec.txt"
    assert result.text == "仕様書の本文です。"
    assert result.char_count == len(result.text)
    assert result.page_count is None
    assert result.truncated is False


def test_parse_document_full_reads_docx():
    result = parse_document_full("spec.docx", _docx_bytes(["第1条: 認証機能を実装する"]))
    assert "第1条: 認証機能を実装する" in result.text
    assert result.page_count is None
    assert result.truncated is False


# --- parse_document_full: 案A（切り詰めない） ---

def test_parse_document_full_does_not_truncate_long_text():
    long_text = "あ" * (MAX_EXTRACT_CHARS + 500)
    result = parse_document_full("spec.txt", long_text.encode("utf-8"))
    assert result.char_count == MAX_EXTRACT_CHARS + 500
    assert result.truncated is False
    assert "システム警告" not in result.text  # 警告文がtextに混入しない


def test_parse_document_legacy_still_truncates_long_text():
    """既存のparse_document()（レガシーAPI用）の切り詰め挙動は変えていない"""
    long_text = "あ" * (MAX_EXTRACT_CHARS + 500)
    text = parse_document("spec.txt", long_text.encode("utf-8"))
    assert len(text) > MAX_EXTRACT_CHARS  # 警告文の分だけ元の上限より長い
    assert "システム警告" in text


# --- errors ---

def test_parse_document_full_rejects_unsupported_extension():
    with pytest.raises(UnsupportedFileTypeError):
        parse_document_full("spec.xlsx", b"dummy")


def test_parse_document_full_rejects_empty_text():
    with pytest.raises(ValueError):
        parse_document_full("spec.txt", b"   \n\t  ")


def test_parse_document_full_rejects_oversized_file(monkeypatch):
    import backend.services.parser as parser_module
    monkeypatch.setattr(parser_module, "MAX_UPLOAD_SIZE", 10)
    with pytest.raises(FileTooLargeError):
        parse_document_full("spec.txt", b"x" * 100)


# --- page_count (PDF) ---

def test_parse_document_full_returns_page_count_for_pdf():
    import fitz

    # 既定フォントはCJKグリフを描画できないため、ページ数の検証にはASCIIを使う
    # （日本語ファイルでもpage_countの抽出ロジック自体は変わらない）
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    page = doc[0]
    page.insert_text((72, 72), "Specification page 1")
    pdf_bytes = doc.tobytes()
    doc.close()

    result = parse_document_full("spec.pdf", pdf_bytes)
    assert result.page_count == 2
    assert "Specification" in result.text
