# backend/tests/test_tasks_decomposer.py
"""backend/pipeline/tasks/decomposer.py の単体テスト。

実際のLLM呼び出しはせず、backend/tests/test_pipeline.py と同じ
FakeLLMClient(キーワード応答型)で置き換える。
"""

import json

import pytest

from backend.pipeline.requirements.schema import Requirement, SourceReference
from backend.pipeline.tasks.decomposer import decompose_requirement
from backend.services.llm import BaseLLMClient
from backend.services.rag.embeddings import BaseEmbeddingClient
from backend.services.rag.schema import EmbeddedChunk, SpecIndex


class FakeLLMClient(BaseLLMClient):
    def __init__(self, responses: dict[str, str] | None = None, default: str = "{}"):
        self.responses = responses or {}
        self.default = default
        self.calls: list[str] = []

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.calls.append(prompt)
        for key, resp in self.responses.items():
            if key in prompt:
                return resp
        return self.default


def _requirement(**overrides) -> Requirement:
    defaults = dict(
        id="REQ-001",
        type="functional",
        title="仕様書アップロード機能",
        description="利用者は仕様書ドキュメントをアップロードできる",
        priority="high",
        origin="explicit",
        source_reference=SourceReference(
            document_id="doc_1", section="第1条(アップロード)",
            source_text="利用者は仕様書ドキュメントをアップロードできる",
        ),
        confidence=0.9,
    )
    defaults.update(overrides)
    return Requirement(**defaults)


@pytest.mark.asyncio
async def test_decompose_requirement_parses_multiple_tasks():
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [
                {"title": "ファイルアップロードAPIを実装する", "description": "APIを実装する",
                 "priority": "high", "estimated_hours": 8, "required_skills": ["FastAPI"],
                 "acceptance_criteria": ["アップロードできること"], "confidence": 0.9},
                {"title": "ファイル選択UIを実装する", "description": "UIを実装する",
                 "priority": "medium", "estimated_hours": 4, "required_skills": ["React"],
                 "acceptance_criteria": ["ファイルを選択できること"], "confidence": 0.8},
            ]
        }, ensure_ascii=False)
    })

    candidates, error = await decompose_requirement(requirement, client)

    assert error is None
    assert len(candidates) == 2
    assert candidates[0].title == "ファイルアップロードAPIを実装する"
    assert candidates[0].requirement_ids == ["REQ-001"]


@pytest.mark.asyncio
async def test_decompose_requirement_inherits_source_reference_from_requirement_not_llm():
    """LLMがsource_referenceを書いてこなくても（そもそも聞いていない）、
    出典は常にRequirementの実データから機械的に引き継がれることを確認する
    （元の仕様書を再パースしないという方針の核心）"""
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "ファイルアップロードAPIを実装する", "description": "APIを実装する"}]
        }, ensure_ascii=False)
    })

    candidates, error = await decompose_requirement(requirement, client)

    assert error is None
    assert candidates[0].source_reference == requirement.source_reference
    assert candidates[0].source_reference.section == "第1条(アップロード)"


@pytest.mark.asyncio
async def test_decompose_requirement_invalid_priority_falls_back_to_unknown():
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "何かのタスク", "description": "d", "priority": "超緊急"}]
        }, ensure_ascii=False)
    })
    candidates, error = await decompose_requirement(requirement, client)
    assert candidates[0].priority == "unknown"


@pytest.mark.asyncio
async def test_decompose_requirement_drops_item_missing_title_or_description():
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [
                {"title": "", "description": "d"},
                {"title": "t", "description": ""},
            ]
        }, ensure_ascii=False)
    })
    candidates, error = await decompose_requirement(requirement, client)
    assert error is None
    assert candidates == []


@pytest.mark.asyncio
async def test_decompose_requirement_implausible_estimated_hours_is_nulled_not_kept():
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "t", "description": "d", "estimated_hours": "たくさん"}]
        }, ensure_ascii=False)
    })
    candidates, error = await decompose_requirement(requirement, client)
    assert candidates[0].estimated_hours is None


@pytest.mark.asyncio
async def test_decompose_requirement_missing_required_skills_defaults_to_unknown():
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "t", "description": "d"}]
        }, ensure_ascii=False)
    })
    candidates, error = await decompose_requirement(requirement, client)
    assert candidates[0].required_skills == ["unknown"]


@pytest.mark.asyncio
async def test_decompose_requirement_malformed_json_returns_error_not_crash():
    requirement = _requirement()
    client = FakeLLMClient(default="これはJSONではありません")
    candidates, error = await decompose_requirement(requirement, client)
    assert candidates == []
    assert error is not None


@pytest.mark.asyncio
async def test_decompose_requirement_non_list_tasks_key_returns_error():
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({"tasks": "not-a-list"})
    })
    candidates, error = await decompose_requirement(requirement, client)
    assert candidates == []
    assert error is not None


# --- RAG (実験的機能): spec_index/embedding_clientがNoneなら既存動作と完全に同一 ---


class FakeEmbeddingClient(BaseEmbeddingClient):
    def __init__(self, vector=None):
        self.model = "fake-embedding-v1"
        self._vector = vector or [1.0, 0.0]
        self.calls = []

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        self.calls.append((text, is_query))
        return self._vector


@pytest.mark.asyncio
async def test_decompose_requirement_without_spec_index_has_empty_related_sources():
    """ENABLE_RAG=false相当（spec_index/embedding_client未指定）の既定動作。
    既存の呼び出し方(decompose_requirement(r, client))は変更なしで動くこと、
    追加のHTTP呼び出しが一切発生しないことを確認する。"""
    requirement = _requirement()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "t", "description": "d"}]
        }, ensure_ascii=False)
    })

    candidates, error = await decompose_requirement(requirement, client)

    assert error is None
    assert candidates[0].related_sources == []


@pytest.mark.asyncio
async def test_decompose_requirement_with_spec_index_populates_related_sources():
    requirement = _requirement()
    llm_client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "t", "description": "d"}]
        }, ensure_ascii=False)
    })
    spec_index = SpecIndex(
        document_id="doc_1",
        document_hash="hash123",
        model="fake-embedding-v1",
        chunks=[
            EmbeddedChunk(chunk_id="chunk_1", text="アップロード機能の詳細", heading="第1条(アップロード)", vector=[1.0, 0.0]),
        ],
    )
    embedding_client = FakeEmbeddingClient(vector=[1.0, 0.0])

    candidates, error = await decompose_requirement(
        requirement, llm_client, spec_index=spec_index, embedding_client=embedding_client,
    )

    assert error is None
    assert len(candidates[0].related_sources) == 1
    source = candidates[0].related_sources[0]
    assert source.chunk_id == "chunk_1"
    assert source.section == "第1条(アップロード)"
    assert source.page is None  # 存在しないページ番号を生成しない
    assert 0.0 <= source.similarity <= 1.0
    # プロンプトにも実在のchunkテキストが参考として注入されていること
    assert any("アップロード機能の詳細" in prompt for prompt in llm_client.calls)


@pytest.mark.asyncio
async def test_decompose_requirement_with_empty_spec_index_has_empty_related_sources():
    """indexにchunkが無い場合、それらしい出典を作り出さず空配列を返す。"""
    requirement = _requirement()
    llm_client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "t", "description": "d"}]
        }, ensure_ascii=False)
    })
    spec_index = SpecIndex(document_id="doc_1", document_hash="hash123", model="fake-embedding-v1", chunks=[])
    embedding_client = FakeEmbeddingClient()

    candidates, error = await decompose_requirement(
        requirement, llm_client, spec_index=spec_index, embedding_client=embedding_client,
    )

    assert error is None
    assert candidates[0].related_sources == []
