# backend/jobs/errors.py
"""
Phase 10 STEP 10: 例外を、フロントエンド向けの構造化エラー
(`{"code": "...", "message": "..."}`, 既存のauth/tasksルーターと同じ形)に
変換する。内部のスタックトレースは絶対にフロントエンドへ返さない
——サーバー側のログ(`logger.exception(...)`)にのみ記録する。
"""

from __future__ import annotations

from typing import Tuple

from fastapi import HTTPException


def classify_exception(exc: BaseException) -> Tuple[str, str]:
    """例外を (error_code, message) に変換する。"""
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return str(detail["code"]), str(detail.get("message") or "エラーが発生しました。")
        return f"HTTP_{exc.status_code}", str(detail)

    if isinstance(exc, (ConnectionError, OSError)):
        return "OLLAMA_UNAVAILABLE", "LLM/Ollamaサーバーに接続できませんでした。"

    if isinstance(exc, ValueError):
        return "VALIDATION_ERROR", str(exc) or "入力値が不正です。"

    return "INTERNAL_ERROR", "予期しないエラーが発生しました。"
