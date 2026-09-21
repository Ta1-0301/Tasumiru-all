# backend/tests/test_tasks_validator.py
"""backend/pipeline/tasks/validator.py の単体テスト。LLMは使わない。"""

from backend.pipeline.requirements.schema import Requirement, SourceReference
from backend.pipeline.tasks.schema import Task
from backend.pipeline.tasks.validator import (
    apply_review_flags,
    check_duplicate_tasks,
    check_invalid_estimated_hours,
    check_missing_acceptance_criteria,
    check_missing_source_references,
    check_overly_broad_tasks,
    check_overly_granular_tasks,
    check_source_text_matches_document,
    check_tasks_without_requirements,
    validate_tasks,
)


def _task(id="TASK-001", **overrides):
    defaults = dict(
        requirement_ids=["REQ-001"],
        title="ファイルアップロードAPIを実装する",
        description="仕様書ファイルを受け取り保存するAPIエンドポイントを実装する",
        priority="high",
        estimated_hours=8,
        required_skills=["FastAPI"],
        acceptance_criteria=["アップロードでき、保存されることを確認できる"],
        source_reference=SourceReference(document_id="doc_1", source_text="仕様書ドキュメントをアップロードできる"),
        confidence=0.9,
    )
    defaults.update(overrides)
    return Task(id=id, **defaults)


# --- tasks without requirements ---

def test_check_tasks_without_requirements_flags_empty_list():
    task = _task(requirement_ids=[])
    issues = check_tasks_without_requirements([task])
    assert any(i.code == "TASK_WITHOUT_REQUIREMENT" for i in issues)


def test_check_tasks_without_requirements_accepts_present_ids():
    assert check_tasks_without_requirements([_task()]) == []


# --- duplicates ---

def test_check_duplicate_tasks_flags_near_identical_titles():
    a = _task(id="TASK-001", title="ファイルアップロードAPIを実装する")
    b = _task(id="TASK-002", title="ファイルアップロードAPIを実装すること")
    issues = check_duplicate_tasks([a, b])
    assert any(i.code == "DUPLICATE_TASK" for i in issues)


def test_check_duplicate_tasks_ignores_dissimilar_titles():
    a = _task(id="TASK-001", title="ファイルアップロードAPIを実装する")
    b = _task(id="TASK-002", title="Kanban画面のデザインを作成する")
    assert check_duplicate_tasks([a, b]) == []


# --- overly broad ---

def test_check_overly_broad_tasks_flags_system_wide_keyword():
    task = _task(title="システム全体を実装する")
    issues = check_overly_broad_tasks([task])
    assert any(i.code == "OVERLY_BROAD_TASK" for i in issues)


def test_check_overly_broad_tasks_flags_bundled_conjunction():
    task = _task(title="認証APIを実装するとともにテストを実施する")
    issues = check_overly_broad_tasks([task])
    assert any(i.code == "OVERLY_BROAD_TASK" for i in issues)


def test_check_overly_broad_tasks_accepts_focused_task():
    assert check_overly_broad_tasks([_task()]) == []


# --- overly granular ---

def test_check_overly_granular_tasks_flags_trivial_ui_change_not_required():
    task = _task(title="アップロードボタンの色を変更する", description="ボタンの色を変える")
    issues = check_overly_granular_tasks([task])
    assert any(i.code == "OVERLY_GRANULAR_TASK" for i in issues)


def test_check_overly_granular_tasks_allows_trivial_change_when_explicitly_required():
    requirement = Requirement(
        id="REQ-001", type="functional", title="ボタン色指定",
        description="アップロードボタンの色を変えることが明示的に要求されている",
        confidence=0.9,
    )
    task = _task(requirement_ids=["REQ-001"], title="アップロードボタンの色を変更する", description="ボタンの色を変える")
    issues = check_overly_granular_tasks([task], requirements_by_id={"REQ-001": requirement})
    assert issues == []


def test_check_overly_granular_tasks_ignores_normal_task():
    assert check_overly_granular_tasks([_task()]) == []


# --- missing source references ---

def test_check_missing_source_references_flags_none_reference():
    task = _task(source_reference=None)
    issues = check_missing_source_references([task])
    assert any(i.code == "MISSING_SOURCE_REFERENCE" for i in issues)


def test_check_missing_source_references_accepts_present_reference():
    assert check_missing_source_references([_task()]) == []


# --- source text double-check ---

def test_check_source_text_matches_document_flags_hallucinated_excerpt():
    task = _task(source_reference=SourceReference(document_id="doc_1", source_text="本文に存在しない文章"))
    issues = check_source_text_matches_document([task], document_text="本文はこれだけです。")
    assert any(i.code == "SOURCE_NOT_FOUND" for i in issues)


def test_check_source_text_matches_document_accepts_real_excerpt():
    document_text = "利用者は仕様書ドキュメントをアップロードできる。"
    task = _task(source_reference=SourceReference(document_id="doc_1", source_text="仕様書ドキュメントをアップロードできる"))
    issues = check_source_text_matches_document([task], document_text=document_text)
    assert issues == []


# --- missing acceptance criteria ---

def test_check_missing_acceptance_criteria_flags_empty_list():
    task = _task(acceptance_criteria=[])
    issues = check_missing_acceptance_criteria([task])
    assert any(i.code == "MISSING_ACCEPTANCE_CRITERIA" for i in issues)


def test_check_missing_acceptance_criteria_accepts_present_criteria():
    assert check_missing_acceptance_criteria([_task()]) == []


# --- invalid estimated hours ---

def test_check_invalid_estimated_hours_flags_zero_or_negative():
    issues = check_invalid_estimated_hours([_task(estimated_hours=0)])
    assert any(i.code == "INVALID_ESTIMATED_HOURS" for i in issues)


def test_check_invalid_estimated_hours_flags_implausibly_large():
    issues = check_invalid_estimated_hours([_task(estimated_hours=99999)])
    assert any(i.code == "INVALID_ESTIMATED_HOURS" for i in issues)


def test_check_invalid_estimated_hours_does_not_flag_missing_value():
    """未設定(None)は不明の正直な申告であり、無効とはみなさない"""
    issues = check_invalid_estimated_hours([_task(estimated_hours=None)])
    assert issues == []


def test_check_invalid_estimated_hours_accepts_plausible_value():
    assert check_invalid_estimated_hours([_task(estimated_hours=8)]) == []


# --- validate_tasks aggregation + apply_review_flags never mutates other fields ---

def test_validate_tasks_aggregates_all_checks():
    broken = _task(id="TASK-001", requirement_ids=[], source_reference=None, acceptance_criteria=[], estimated_hours=0)
    issues = validate_tasks([broken])
    codes = {i.code for i in issues}
    assert "TASK_WITHOUT_REQUIREMENT" in codes
    assert "MISSING_SOURCE_REFERENCE" in codes
    assert "MISSING_ACCEPTANCE_CRITERIA" in codes
    assert "INVALID_ESTIMATED_HOURS" in codes


def test_validate_tasks_clean_document_has_no_issues():
    issues = validate_tasks([_task()], source_document_text="仕様書ドキュメントをアップロードできる。")
    assert issues == []


def test_apply_review_flags_marks_only_affected_tasks_without_changing_other_fields():
    good = _task(id="TASK-001")
    broken = _task(id="TASK-002", title="Kanban画面のデザインを作成する", estimated_hours=0)
    issues = validate_tasks([good, broken])

    flagged = apply_review_flags([good, broken], issues)
    flagged_by_id = {t.id: t for t in flagged}

    assert flagged_by_id["TASK-001"].needs_review is False
    assert flagged_by_id["TASK-002"].needs_review is True
    assert any("INVALID_ESTIMATED_HOURS" in r for r in flagged_by_id["TASK-002"].review_reasons)
    # 修復されていない: 無効だった値がそのまま残っている
    assert flagged_by_id["TASK-002"].estimated_hours == 0
    assert flagged_by_id["TASK-002"].title == broken.title
