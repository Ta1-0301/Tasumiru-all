# backend/tests/test_pipeline.py
"""新タスク抽出パイプライン（backend/services/pipeline/）の単体テスト。

決定的な部分（structure/normalize/dedup）はLLM無しで検証する。
LLMが必要な部分（requirements/candidates/validate）は FakeLLMClient で置き換え、
実際のOllama呼び出しをせずに検証する。
"""

import json

import pytest
from fastapi import HTTPException

from backend.services.llm import BaseLLMClient
from backend.services.pipeline.llm_json import call_llm_json
from backend.services.pipeline.schema import (
    CandidateTask,
    DocumentChunk,
    Priority,
    Requirement,
    RequirementType,
    SourceReference,
)
from backend.services.pipeline.stages import (
    detect_duplicates,
    extract_candidate_task,
    identify_requirements,
    normalize_task,
)
from backend.services.pipeline.structure import decompose_document
from backend.services.pipeline.validate import validate_task
from backend.services.pipeline.runner import run_pipeline


class FakeLLMClient(BaseLLMClient):
    """プロンプト中のキーワードに応じて固定レスポンスを返すテスト用クライアント"""

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


class FlakyTimeoutClient(BaseLLMClient):
    """指定回数だけHTTPException(タイムアウト相当)を投げてから成功するテスト用クライアント"""

    def __init__(self, fail_times: int, success_response: str = "{}"):
        self.fail_times = fail_times
        self.success_response = success_response
        self.call_count = 0

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.call_count += 1
        if self.call_count <= self.fail_times:
            raise HTTPException(status_code=504, detail={"code": "LLM_TIMEOUT", "message": "timeout"})
        return self.success_response


# ---------- call_llm_json: タイムアウトへの耐性 ----------

@pytest.mark.asyncio
async def test_call_llm_json_retries_through_timeout_and_succeeds():
    client = FlakyTimeoutClient(fail_times=1, success_response='{"ok": true}')
    result, error = await call_llm_json(client, "prompt", retries=2)
    assert result == {"ok": True}
    assert error is None
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_call_llm_json_gives_up_after_persistent_timeout_without_crashing():
    client = FlakyTimeoutClient(fail_times=99, success_response='{"ok": true}')
    result, error = await call_llm_json(client, "prompt", retries=2)
    assert result is None  # クラッシュせず、呼び出し側が判断できる形で失敗を返す
    assert error is not None and "通信エラー" in error


# ---------- Stage 1: 文書構造抽出（決定的） ----------

def test_decompose_document_splits_by_article():
    text = "前文です。\n\n第1条(A): 内容A。\n\n第2条(B): 内容B。"
    chunks = decompose_document(text)
    assert [c.chunk_id for c in chunks] == ["chunk_1", "chunk_2", "chunk_3"]
    assert chunks[1].heading == "第1条(A)"
    for c in chunks:
        assert c.text in text  # 不変条件: 必ず原文の部分文字列


def test_decompose_document_splits_by_paragraph_when_no_articles():
    text = "段落1の内容です。\n\n段落2の内容です。"
    chunks = decompose_document(text)
    assert len(chunks) == 2
    for c in chunks:
        assert c.text in text


def test_decompose_document_single_short_chunk_fallback():
    text = "短いタスクです。"
    chunks = decompose_document(text)
    assert len(chunks) == 1
    assert chunks[0].text == text


def test_decompose_document_empty_text_returns_no_chunks():
    assert decompose_document("") == []
    assert decompose_document("   ") == []


# ---------- Stage 4: 正規化（決定的） ----------

def test_normalize_task_flags_empty_title():
    candidate = CandidateTask(title="", source_reference=SourceReference(chunk_id="c1", excerpt="x"))
    result = normalize_task(candidate)
    assert result.needs_review is True
    assert "タイトルが空" in result.review_reason


def test_normalize_task_flags_bundled_verbs():
    candidate = CandidateTask(
        title="認証APIを実装するとともにテストを実施する",
        source_reference=SourceReference(chunk_id="c1", excerpt="x"),
    )
    result = normalize_task(candidate)
    assert result.needs_review is True
    assert "束ねられている" in result.review_reason


def test_normalize_task_nulls_implausible_estimated_hours():
    candidate = CandidateTask(
        title="認証APIを実装する",
        estimated_hours=99999,
        source_reference=SourceReference(chunk_id="c1", excerpt="x"),
    )
    result = normalize_task(candidate)
    assert result.estimated_hours is None
    assert result.needs_review is True


def test_normalize_task_flags_missing_source_reference():
    candidate = CandidateTask(title="認証APIを実装する", source_reference=None)
    result = normalize_task(candidate)
    assert result.needs_review is True
    assert "出典が特定できない" in result.review_reason


def test_normalize_task_clean_task_not_flagged():
    candidate = CandidateTask(
        title="認証APIを実装する",
        source_reference=SourceReference(chunk_id="c1", excerpt="認証APIを実装すること"),
    )
    result = normalize_task(candidate)
    assert result.needs_review is False
    assert result.review_reason is None


# ---------- Stage 5: 重複検出（決定的） ----------

def test_detect_duplicates_keeps_more_complete_task():
    sparse = CandidateTask(title="認証APIのエンドポイントを実装する")
    rich = CandidateTask(
        title="認証APIのエンドポイントを実装すること",
        description="招待URL方式の認証を実装する",
        estimated_hours=8,
        required_skills=["FastAPI"],
    )
    kept, dropped = detect_duplicates([sparse, rich])
    assert len(kept) == 1
    assert kept[0] is rich
    assert dropped == [sparse.title]


def test_detect_duplicates_no_overlap_keeps_both():
    a = CandidateTask(title="認証APIを実装する")
    b = CandidateTask(title="Kanban画面を実装する")
    kept, dropped = detect_duplicates([a, b])
    assert len(kept) == 2
    assert dropped == []


# ---------- Stage 2: 要求事項識別（FakeLLMClient使用） ----------

@pytest.mark.asyncio
async def test_identify_requirements_parses_valid_response():
    chunk = DocumentChunk(chunk_id="chunk_1", text="認証APIを実装してください。")
    client = FakeLLMClient(responses={
        "認証APIを実装してください": json.dumps({
            "requirements": [{"text": "認証APIを実装する", "requirement_type": "explicit"}]
        }, ensure_ascii=False)
    })
    reqs, error = await identify_requirements(chunk, client)
    assert error is None
    assert len(reqs) == 1
    assert reqs[0].chunk_id == "chunk_1"
    assert reqs[0].requirement_type == RequirementType.explicit


@pytest.mark.asyncio
async def test_identify_requirements_unknown_type_falls_back_to_implicit():
    chunk = DocumentChunk(chunk_id="chunk_1", text="何かの区画")
    client = FakeLLMClient(responses={
        "何かの区画": json.dumps({
            "requirements": [{"text": "何かする", "requirement_type": "そんな種類は無い"}]
        }, ensure_ascii=False)
    })
    reqs, error = await identify_requirements(chunk, client)
    assert error is None
    assert reqs[0].requirement_type == RequirementType.implicit


@pytest.mark.asyncio
async def test_identify_requirements_malformed_json_returns_error_not_crash():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    client = FakeLLMClient(default="これはJSONではありません")
    reqs, error = await identify_requirements(chunk, client)
    assert reqs == []
    assert error is not None


# ---------- Stage 3: 候補タスク抽出（FakeLLMClient使用） ----------

@pytest.mark.asyncio
async def test_extract_candidate_task_builds_source_reference_from_chunk_not_llm():
    chunk = DocumentChunk(chunk_id="chunk_1", text="第1条: 認証APIを実装すること。")
    requirement = Requirement(
        requirement_id="chunk_1-r1", chunk_id="chunk_1",
        text="認証APIを実装する", requirement_type=RequirementType.explicit,
    )
    # LLMが出典欄を書いてこなくても(そもそも聞いていない)、source_referenceは
    # 常にchunkの実データから機械的に組み立てられることを確認する
    client = FakeLLMClient(responses={
        "認証APIを実装する": json.dumps({
            "title": "認証APIを実装する",
            "description": "招待URL方式の認証を実装する",
            "priority": "high",
            "estimated_hours": 8,
            "required_skills": ["FastAPI"],
            "acceptance_criteria": ["ログインできること"],
        }, ensure_ascii=False)
    })
    candidate, error = await extract_candidate_task(requirement, chunk, client)
    assert error is None
    assert candidate.source_reference.chunk_id == "chunk_1"
    assert candidate.source_reference.excerpt == chunk.text
    assert candidate.priority == Priority.high


@pytest.mark.asyncio
async def test_extract_candidate_task_invalid_priority_falls_back_to_unknown():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    requirement = Requirement(
        requirement_id="chunk_1-r1", chunk_id="chunk_1", text="何かする",
        requirement_type=RequirementType.implicit,
    )
    client = FakeLLMClient(responses={
        "何かする": json.dumps({"title": "何かのタスク", "priority": "超緊急"}, ensure_ascii=False)
    })
    candidate, error = await extract_candidate_task(requirement, chunk, client)
    assert error is None
    assert candidate.priority == Priority.unknown


@pytest.mark.asyncio
async def test_extract_candidate_task_missing_title_is_a_failure_not_silent_default():
    chunk = DocumentChunk(chunk_id="chunk_1", text="内容")
    requirement = Requirement(
        requirement_id="chunk_1-r1", chunk_id="chunk_1", text="何かする",
        requirement_type=RequirementType.implicit,
    )
    client = FakeLLMClient(responses={"何かする": json.dumps({"description": "タイトル無し"})})
    candidate, error = await extract_candidate_task(requirement, chunk, client)
    assert candidate is None
    assert error is not None


# ---------- Stage 7: 検証・修復 ----------

@pytest.mark.asyncio
async def test_validate_task_accepts_valid_candidate():
    candidate = CandidateTask(
        title="認証APIを実装する",
        source_reference=SourceReference(chunk_id="c1", excerpt="認証APIを実装すること"),
    )
    client = FakeLLMClient()
    task, failed = await validate_task(candidate, "T-001", client)
    assert failed is None
    assert task.task_id == "T-001"
    assert task.title == "認証APIを実装する"


@pytest.mark.asyncio
async def test_validate_task_repairs_invalid_candidate():
    # model_construct でPydanticの検証を迂回し、意図的に壊れたインスタンスを作る
    broken = CandidateTask.model_construct(
        title="認証APIを実装する",
        description=None,
        priority="invalid-priority-value",  # Enumに存在しない値
        estimated_hours=None,
        required_skills=["FastAPI"],
        source_reference=SourceReference(chunk_id="c1", excerpt="認証APIを実装すること"),
        acceptance_criteria=None,
        needs_review=False,
        review_reason=None,
    )
    client = FakeLLMClient(responses={
        "検証エラー": json.dumps({
            "title": "認証APIを実装する",
            "description": None,
            "priority": "medium",
            "estimated_hours": None,
            "required_skills": ["FastAPI"],
            "acceptance_criteria": None,
        }, ensure_ascii=False)
    })
    task, failed = await validate_task(broken, "T-001", client)
    assert failed is None
    assert task is not None
    assert task.priority == Priority.medium
    # source_referenceは修復対象外で、必ず元の値が維持されること
    assert task.source_reference.chunk_id == "c1"


@pytest.mark.asyncio
async def test_validate_task_marks_failed_when_repair_also_fails():
    broken = CandidateTask.model_construct(
        title="認証APIを実装する",
        description=None,
        priority="invalid-priority-value",
        estimated_hours=None,
        required_skills=["FastAPI"],
        source_reference=None,
        acceptance_criteria=None,
        needs_review=False,
        review_reason=None,
    )
    client = FakeLLMClient(default="修復もできません（JSONではない）")
    task, failed = await validate_task(broken, "T-001", client)
    assert task is None
    assert failed is not None
    assert failed.stage in ("validate", "validate_after_repair")


# ---------- フルパイプライン（結合テスト、FakeLLMClient使用） ----------

@pytest.mark.asyncio
async def test_run_pipeline_end_to_end_with_fake_client():
    text = "第1条: 認証APIを実装してください。"
    requirement_response = json.dumps({
        "requirements": [{"text": "認証APIを実装する", "requirement_type": "explicit"}]
    }, ensure_ascii=False)
    task_response = json.dumps({
        "title": "認証APIを実装する",
        "description": "招待URL方式の認証を実装する",
        "priority": "high",
        "estimated_hours": 8,
        "required_skills": ["FastAPI"],
        "acceptance_criteria": ["ログインできること"],
    }, ensure_ascii=False)

    client = FakeLLMClient(responses={
        "以下は仕様書本文の一区画": requirement_response,
        "以下の「要求事項」を": task_response,
    })

    result = await run_pipeline(text, client)

    assert result.chunk_count == 1
    assert result.requirement_count == 1
    assert len(result.tasks) == 1
    task = result.tasks[0]
    assert task.title == "認証APIを実装する"
    assert task.source_reference is not None
    assert task.source_reference.excerpt in text
    assert result.failed_items == []
