# backend/tests/test_tasks_runner.py
"""backend/pipeline/tasks/runner.py の結合テスト（FakeLLMClient使用）。"""

import json

import pytest

from backend.pipeline.requirements.schema import Requirement, RequirementDocument, SourceReference
from backend.pipeline.tasks.runner import run_task_decomposition_pipeline, save_tasks_document
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


def _requirement_document() -> RequirementDocument:
    return RequirementDocument(
        document_id="spec_a",
        requirements=[
            Requirement(
                id="REQ-001", type="functional", title="仕様書アップロード機能",
                description="利用者は仕様書ドキュメントをアップロードできる",
                source_reference=SourceReference(
                    document_id="spec_a", section="第1条(アップロード)",
                    source_text="利用者は仕様書ドキュメントをアップロードできる",
                ),
                confidence=0.9,
            ),
        ],
    )


@pytest.mark.asyncio
async def test_run_task_decomposition_pipeline_end_to_end():
    requirement_document = _requirement_document()
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

    doc = await run_task_decomposition_pipeline(requirement_document, client)

    assert doc.document_id == "spec_a"
    assert doc.model == "fake-model-v1"
    assert len(doc.tasks) == 2
    assert [t.id for t in doc.tasks] == ["TASK-001", "TASK-002"]

    for t in doc.tasks:
        assert t.requirement_ids == ["REQ-001"]
        assert t.source_reference is not None
        # 出典はRequirementの実データそのもの（元の仕様書を再パースしていない）
        assert t.source_reference == requirement_document.requirements[0].source_reference
        assert t.needs_review is False

    assert doc.issues == []


@pytest.mark.asyncio
async def test_run_task_decomposition_pipeline_flags_but_does_not_fix_invalid_task():
    requirement_document = _requirement_document()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{
                "title": "アップロードボタンの色を変更する", "description": "ボタンの色を変える",
                # acceptance_criteriaもestimated_hoursも無い、些末なUI変更
            }]
        }, ensure_ascii=False)
    })

    doc = await run_task_decomposition_pipeline(requirement_document, client)

    assert len(doc.tasks) == 1
    task = doc.tasks[0]
    assert task.needs_review is True
    assert any("OVERLY_GRANULAR_TASK" in r for r in task.review_reasons)
    assert any("MISSING_ACCEPTANCE_CRITERIA" in r for r in task.review_reasons)
    # 修復されていない: acceptance_criteriaは空のまま、タイトルも書き換えられていない
    assert task.acceptance_criteria == []
    assert task.title == "アップロードボタンの色を変更する"


@pytest.mark.asyncio
async def test_run_task_decomposition_pipeline_does_not_assign_members_or_dependencies():
    """このフェーズではメンバー割り当て・依存関係の構築を行わない"""
    requirement_document = _requirement_document()
    client = FakeLLMClient(responses={
        "利用者は仕様書ドキュメントをアップロードできる": json.dumps({
            "tasks": [{"title": "ファイルアップロードAPIを実装する", "description": "APIを実装する",
                       "acceptance_criteria": ["アップロードできること"]}]
        }, ensure_ascii=False)
    })

    doc = await run_task_decomposition_pipeline(requirement_document, client)
    dumped = json.dumps(doc.model_dump(mode="json"), ensure_ascii=False)

    assert "assignee" not in dumped
    assert "depends_on" not in dumped
    assert "dependencies" not in dumped


@pytest.mark.asyncio
async def test_run_task_decomposition_pipeline_records_decomposition_errors_without_crashing():
    requirement_document = _requirement_document()
    client = FakeLLMClient(default="これはJSONではありません")  # 全要求で分解失敗

    doc = await run_task_decomposition_pipeline(requirement_document, client)

    assert doc.tasks == []
    assert any(i.code == "DECOMPOSITION_ERROR" for i in doc.issues)


@pytest.mark.asyncio
async def test_run_task_decomposition_pipeline_uses_original_text_only_for_source_verification(monkeypatch):
    """防御的な出典再検証だけのために元の仕様書テキストが使われることを確認する"""
    import backend.pipeline.tasks.runner as runner_module

    async def fake_decompose(requirement, client):
        from backend.pipeline.tasks.schema import SourceReference as SR
        from backend.pipeline.tasks.schema import TaskCandidate
        return [TaskCandidate(
            requirement_ids=[requirement.id], title="t", description="d",
            acceptance_criteria=["c"],
            source_reference=SR(document_id="spec_a", source_text="本文には存在しない捏造テキスト"),
        )], None

    monkeypatch.setattr(runner_module, "decompose_requirement", fake_decompose)

    requirement_document = _requirement_document()
    client = FakeLLMClient()
    doc = await run_task_decomposition_pipeline(
        requirement_document, client, original_document_text="実際の本文はこれだけです。"
    )

    assert any(i.code == "SOURCE_NOT_FOUND" for i in doc.issues)


def test_save_tasks_document_writes_valid_json(tmp_path):
    from backend.pipeline.tasks.schema import TaskDocument

    doc = TaskDocument(document_id="spec_a", tasks=[], issues=[])
    out_path = save_tasks_document(doc, output_dir=tmp_path)

    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["document_id"] == "spec_a"
    assert loaded["tasks"] == []
