# backend/routers/documents.py
"""
仕様書ファイル（PDF / Word）を本文テキストに変換するAPI
（Backend依頼_仕様書ファイル変換API.md）。

**ファイル → 本文テキストの変換だけを行う。** DBへの保存もジョブの起動も
行わない。既存の`backend/services/parser.py`の解析ロジック
（`parse_document_full`）をそのまま再利用し、パイプライン自体には触れない。
認証は既存の`/api/projects*`と同じチーム/デバイスセッションCookie
(`get_current_member`)を使う——新しい認証の仕組みは作らない。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from backend.auth.dependencies import get_current_member
from backend.auth.models import TeamMember
from backend.services.parser import (
    FileTooLargeError,
    ParsedDocument,
    UnsupportedFileTypeError,
    parse_document_full,
)

router = APIRouter(prefix="/api", tags=["documents"])


@router.post("/documents/parse", response_model=ParsedDocument)
async def parse_uploaded_document(
    file: UploadFile = File(...),
    member: TeamMember = Depends(get_current_member),
):
    """アップロードされたPDF/Word/テキストファイルを本文テキストに変換する。

    依頼仕様の案A: このAPIでは`MAX_EXTRACT_CHARS`による切り詰めを行わない
    （`truncated`は常に`False`）。新しいパイプラインはRequirementsステージで
    本文をチャンク単位に処理するため、ここで事前に切り詰める必要が無い。
    """
    file_bytes = await file.read()
    try:
        return parse_document_full(file.filename, file_bytes)
    except FileTooLargeError as e:
        raise HTTPException(status_code=413, detail={"code": "FILE_TOO_LARGE", "message": str(e)})
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail={"code": "UNSUPPORTED_FILE_TYPE", "message": str(e)})
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"code": "EMPTY_DOCUMENT", "message": str(e)})
    except Exception:  # noqa: BLE001 — 壊れた/パスワード付きPDF等でライブラリが投げる例外を500にしない
        raise HTTPException(
            status_code=400,
            detail={
                "code": "FILE_PARSE_ERROR",
                "message": f"ファイル「{file.filename}」を読み取れませんでした。"
                "ファイルが壊れているか、パスワードで保護されている可能性があります。",
            },
        )
