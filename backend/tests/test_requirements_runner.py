# backend/tests/test_requirements_runner.py
"""backend/pipeline/requirements/runner.py の結合テスト（FakeLLMClient使用）。"""

import json

import pytest

from backend.pipeline.requirements.runner import run_requirements_pipeline, save_requirements_document
from backend.services.llm import BaseLLMClient


class FakeLLMClient(BaseLLMClient):
    def __init__(self, responses: dict[str, str] | None = None, default: str = "{}"):
        self.responses = responses or {}
        self.default = default
        self.model = "fake-model-v1"

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        for key, resp in self.responses.items():
            if key in prompt:
                return resp
        return self.default


@pytest.mark.asyncio
async def test_run_requirements_pipeline_end_to_end():
    text = (
        "第1条(目的): 本システムはチームのタスク管理を効率化するために開発する。\n\n"
        "第2条(認証): 招待URL方式による認証機能を実装すること。"
    )
    client = FakeLLMClient(responses={
        "本システムはチームのタスク管理を効率化するために開発する": json.dumps({
            "requirements": [{
                "type": "system_purpose", "title": "タスク管理の効率化",
                "description": "チームのタスク管理を効率化するために開発する",
                "priority": "unknown", "origin": "explicit", "confidence": 0.95,
            }]
        }, ensure_ascii=False),
        "招待URL方式による認証機能を実装すること": json.dumps({
            "requirements": [{
                "type": "functional", "title": "認証機能の実装",
                "description": "招待URL方式による認証機能を実装する",
                "priority": "high", "origin": "explicit", "confidence": 0.9,
            }]
        }, ensure_ascii=False),
    })

    doc = await run_requirements_pipeline("spec_a", text, client)

    assert doc.document_id == "spec_a"
    assert doc.model == "fake-model-v1"
    assert len(doc.requirements) == 2
    ids = [r.id for r in doc.requirements]
    assert ids == ["REQ-001", "REQ-002"]

    types = {r.type for r in doc.requirements}
    assert types == {"system_purpose", "functional"}

    for r in doc.requirements:
        assert r.source_reference is not None
        assert r.source_reference.document_id == "spec_a"
        assert r.source_reference.source_text in text  # 出典は必ず本文の実在部分文字列

    # クリーンな入力なので検証で問題は検出されないはず
    assert doc.issues == []


@pytest.mark.asyncio
async def test_run_requirements_pipeline_does_not_produce_tasks():
    """このフェーズではタスク分解を行わない: 出力にtask的なフィールドが無いことを確認する"""
    text = "招待URL方式による認証機能を実装すること。"
    client = FakeLLMClient(responses={
        "招待URL方式による認証機能を実装すること": json.dumps({
            "requirements": [{"type": "functional", "title": "認証機能の実装", "description": "認証機能を実装する"}]
        }, ensure_ascii=False)
    })

    doc = await run_requirements_pipeline("spec_b", text, client)
    dumped = doc.model_dump(mode="json")

    assert "tasks" not in dumped
    assert "assignee" not in json.dumps(dumped)


@pytest.mark.asyncio
async def test_run_requirements_pipeline_records_extraction_errors_without_crashing():
    text = "第1条: 内容A。\n\n第2条: 内容B。"
    client = FakeLLMClient(default="これはJSONではありません")  # 全チャンクで抽出失敗

    doc = await run_requirements_pipeline("spec_c", text, client)

    assert doc.requirements == []
    assert any(i.code == "EXTRACTION_ERROR" for i in doc.issues)


@pytest.mark.asyncio
async def test_run_requirements_pipeline_flags_hallucinated_source_via_double_check(monkeypatch):
    """extractorが正しく動いている限り発生しないが、防御的な二重チェックが機能することを確認する"""
    import backend.pipeline.requirements.runner as runner_module

    async def fake_extract(chunk, client, document_id):
        from backend.pipeline.requirements.schema import RequirementCandidate, SourceReference
        return [RequirementCandidate(
            type="functional", title="t", description="d",
            source_reference=SourceReference(
                document_id=document_id, source_text="本文には存在しない捏造テキスト",
            ),
        )], None

    monkeypatch.setattr(runner_module, "extract_requirements_from_chunk", fake_extract)

    client = FakeLLMClient()
    doc = await run_requirements_pipeline("spec_d", "実際の本文はこれだけです。", client)

    assert any(i.code == "SOURCE_NOT_FOUND" for i in doc.issues)


def test_save_requirements_document_writes_valid_json(tmp_path):
    from backend.pipeline.requirements.schema import RequirementDocument

    doc = RequirementDocument(document_id="doc_1", requirements=[], issues=[])
    out_path = save_requirements_document(doc, output_dir=tmp_path)

    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["document_id"] == "doc_1"
    assert loaded["requirements"] == []
