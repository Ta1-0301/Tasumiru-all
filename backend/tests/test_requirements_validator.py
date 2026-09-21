# backend/tests/test_requirements_validator.py
"""backend/pipeline/requirements/validator.py の単体テスト。LLMは使わない。"""

from backend.pipeline.requirements.schema import Requirement, SourceReference
from backend.pipeline.requirements.validator import (
    check_contradictions,
    check_duplicates,
    check_empty_descriptions,
    check_invalid_ids,
    check_missing_source_references,
    check_source_text_matches_document,
    validate_requirements,
)


def _req(id="REQ-001", **overrides):
    defaults = dict(
        type="functional",
        title="認証APIを実装する",
        description="招待URL方式の認証APIを実装する",
        priority="high",
        origin="explicit",
        source_reference=SourceReference(document_id="doc_1", source_text="招待URL方式の認証APIを実装する"),
        confidence=0.9,
    )
    defaults.update(overrides)
    return Requirement(id=id, **defaults)


# --- invalid IDs ---

def test_check_invalid_ids_flags_bad_format():
    req = Requirement.model_construct(
        id="bad-id", type="functional", title="t", description="d",
        priority="unknown", origin="explicit", source_reference=None, confidence=0.5,
    )
    issues = check_invalid_ids([req])
    assert any(i.code == "INVALID_ID" for i in issues)


def test_check_invalid_ids_flags_duplicate_ids():
    a = _req(id="REQ-001")
    b = _req(id="REQ-001")
    issues = check_invalid_ids([a, b])
    assert any(i.code == "DUPLICATE_ID" for i in issues)


def test_check_invalid_ids_accepts_well_formed_unique_ids():
    issues = check_invalid_ids([_req(id="REQ-001"), _req(id="REQ-002")])
    assert issues == []


# --- empty descriptions ---

def test_check_empty_descriptions_flags_blank_description():
    req = _req(description="   ")
    issues = check_empty_descriptions([req])
    assert any(i.code == "EMPTY_DESCRIPTION" for i in issues)


def test_check_empty_descriptions_flags_blank_title():
    req = _req(title="")
    issues = check_empty_descriptions([req])
    assert any(i.code == "EMPTY_TITLE" for i in issues)


def test_check_empty_descriptions_accepts_filled_fields():
    assert check_empty_descriptions([_req()]) == []


# --- missing source references ---

def test_check_missing_source_references_flags_none_reference():
    req = _req(source_reference=None)
    issues = check_missing_source_references([req])
    assert any(i.code == "MISSING_SOURCE_REFERENCE" for i in issues)


def test_check_missing_source_references_flags_empty_source_text():
    req = _req(source_reference=SourceReference(document_id="doc_1", source_text=""))
    issues = check_missing_source_references([req])
    assert any(i.code == "MISSING_SOURCE_REFERENCE" for i in issues)


def test_check_missing_source_references_accepts_present_source_text():
    assert check_missing_source_references([_req()]) == []


# --- source text must be real (defensive double-check) ---

def test_check_source_text_matches_document_flags_hallucinated_excerpt():
    req = _req(source_reference=SourceReference(document_id="doc_1", source_text="これは本文に存在しない文章"))
    issues = check_source_text_matches_document([req], document_text="本文はこれだけです。")
    assert any(i.code == "SOURCE_NOT_FOUND" for i in issues)


def test_check_source_text_matches_document_accepts_real_excerpt():
    document_text = "招待URL方式の認証APIを実装する。"
    req = _req(source_reference=SourceReference(document_id="doc_1", source_text="招待URL方式の認証APIを実装する"))
    issues = check_source_text_matches_document([req], document_text=document_text)
    assert issues == []


# --- duplicates ---

def test_check_duplicates_flags_near_identical_descriptions_same_type():
    a = _req(id="REQ-001", description="招待URL方式の認証APIを実装する")
    b = _req(id="REQ-002", description="招待URL方式の認証APIを実装すること")
    issues = check_duplicates([a, b])
    assert any(i.code == "DUPLICATE_REQUIREMENT" for i in issues)


def test_check_duplicates_ignores_different_types():
    a = _req(id="REQ-001", type="functional", description="招待URL方式の認証APIを実装する")
    b = _req(id="REQ-002", type="constraint", description="招待URL方式の認証APIを実装する")
    assert check_duplicates([a, b]) == []


def test_check_duplicates_ignores_dissimilar_descriptions():
    a = _req(id="REQ-001", description="招待URL方式の認証APIを実装する")
    b = _req(id="REQ-002", description="Kanban画面のデザインを作成する")
    assert check_duplicates([a, b]) == []


# --- contradictions (heuristic) ---

def test_check_contradictions_flags_opposing_modal_words_on_similar_topic():
    a = _req(
        id="REQ-001", type="business_rule",
        title="セッショントークンの保存ルール",
        description="生のセッショントークンをデータベースに平文で保存することは禁止する",
    )
    b = _req(
        id="REQ-002", type="business_rule",
        title="セッショントークンの保存ルール",
        description="生のセッショントークンをデータベースに平文で保存することは必須とする",
    )
    issues = check_contradictions([a, b])
    assert any(i.code == "CONTRADICTION_SUSPECTED" for i in issues)


def test_check_contradictions_ignores_unrelated_topics():
    a = _req(
        id="REQ-001", type="business_rule", title="トークン保存ルール",
        description="トークンの平文保存は禁止する",
    )
    b = _req(
        id="REQ-002", type="business_rule", title="デプロイ手順",
        description="デプロイは必須の承認プロセスを経ること",
    )
    assert check_contradictions([a, b]) == []


def test_check_contradictions_ignores_different_types():
    a = _req(id="REQ-001", type="constraint", title="トークン保存", description="平文保存は禁止する")
    b = _req(id="REQ-002", type="functional", title="トークン保存", description="平文保存は必須とする")
    assert check_contradictions([a, b]) == []


# --- validate_requirements: full aggregation ---

def test_validate_requirements_aggregates_all_checks():
    good = _req(id="REQ-001")
    bad_id = Requirement.model_construct(
        id="oops", type="functional", title="t", description="d",
        priority="unknown", origin="explicit", source_reference=None, confidence=0.5,
    )
    issues = validate_requirements([good, bad_id])
    codes = {i.code for i in issues}
    assert "INVALID_ID" in codes
    assert "MISSING_SOURCE_REFERENCE" in codes


def test_validate_requirements_clean_document_has_no_issues():
    good = _req(id="REQ-001")
    issues = validate_requirements([good], document_text="招待URL方式の認証APIを実装する。")
    assert issues == []
