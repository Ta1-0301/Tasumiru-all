# backend/tests/test_documents_api.py
"""POST /api/documents/parse の統合テスト（Backend依頼_仕様書ファイル変換API.md）。

DBへの保存・ジョブの起動を一切行わないこと、既存の`/api/projects*`と同じ
認証（チームセッションCookie）を使うことを中心に検証する。
"""

import pytest

from backend.services.parser import MAX_EXTRACT_CHARS


async def _create_team(client, name="開発チームA", admin_name="管理者"):
    resp = await client.post("/api/teams", json={"name": name, "admin_display_name": admin_name})
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_parse_txt_file_returns_text_and_metadata(client, db_engine):
    await _create_team(client)

    files = {"file": ("spec.txt", b"\xe4\xbb\x95\xe6\xa7\x98\xe6\x9b\xb8\xe3\x81\xa7\xe3\x81\x99\xe3\x80\x82", "text/plain")}
    resp = await client.post("/api/documents/parse", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "spec.txt"
    assert body["text"] == "仕様書です。"
    assert body["char_count"] == len("仕様書です。")
    assert body["page_count"] is None
    assert body["truncated"] is False


@pytest.mark.asyncio
async def test_parse_does_not_truncate_long_document(client, db_engine):
    await _create_team(client)

    long_text = ("あ" * (MAX_EXTRACT_CHARS + 100)).encode("utf-8")
    files = {"file": ("long_spec.txt", long_text, "text/plain")}
    resp = await client.post("/api/documents/parse", files=files)

    assert resp.status_code == 200
    body = resp.json()
    assert body["char_count"] == MAX_EXTRACT_CHARS + 100
    assert body["truncated"] is False
    assert "システム警告" not in body["text"]


@pytest.mark.asyncio
async def test_parse_returns_400_for_corrupted_pdf(client, db_engine):
    await _create_team(client)

    files = {"file": ("broken.pdf", b"%PDF-1.4 not really a pdf", "application/pdf")}
    resp = await client.post("/api/documents/parse", files=files)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "FILE_PARSE_ERROR"


@pytest.mark.asyncio
async def test_parse_rejects_unsupported_file_type(client, db_engine):
    await _create_team(client)

    files = {"file": ("spec.xlsx", b"dummy", "application/vnd.ms-excel")}
    resp = await client.post("/api/documents/parse", files=files)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.asyncio
async def test_parse_rejects_empty_document(client, db_engine):
    await _create_team(client)

    files = {"file": ("empty.txt", b"   ", "text/plain")}
    resp = await client.post("/api/documents/parse", files=files)

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "EMPTY_DOCUMENT"


@pytest.mark.asyncio
async def test_parse_rejects_oversized_file(client, db_engine, monkeypatch):
    import backend.services.parser as parser_module

    monkeypatch.setattr(parser_module, "MAX_UPLOAD_SIZE", 10)
    await _create_team(client)

    files = {"file": ("spec.txt", b"x" * 100, "text/plain")}
    resp = await client.post("/api/documents/parse", files=files)

    assert resp.status_code == 413
    assert resp.json()["detail"]["code"] == "FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_parse_requires_authentication(client, db_engine):
    files = {"file": ("spec.txt", b"hello", "text/plain")}
    resp = await client.post("/api/documents/parse", files=files)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_parse_does_not_persist_anything(client, db_engine):
    """このAPIはDB保存・ジョブ起動を一切行わない（プロジェクト一覧に影響しない）"""
    await _create_team(client)

    files = {"file": ("spec.txt", b"hello", "text/plain")}
    resp = await client.post("/api/documents/parse", files=files)
    assert resp.status_code == 200

    create_resp = await client.post("/api/projects", json={"name": "p"})
    assert create_resp.status_code == 201
    project_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/projects/{project_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["has_document"] is False
