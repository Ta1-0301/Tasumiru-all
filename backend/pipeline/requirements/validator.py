# backend/pipeline/requirements/validator.py
"""
Stage: Requirement Validation。

決定的（ルールベース）に完結させ、LLMを使わない。同じ入力に対して常に同じ
結果になる（再現性がある）。検出対象は依頼の5項目:
  - duplicate requirements
  - missing source references
  - contradictory requirements
  - empty descriptions
  - invalid IDs
"""

from __future__ import annotations

import difflib
import re
from typing import List, Optional

from backend.pipeline.requirements.schema import Requirement, ValidationIssue

_ID_PATTERN = re.compile(r"^REQ-\d{3,}$")

DUPLICATE_SIMILARITY_THRESHOLD = 0.85
CONTRADICTION_TITLE_SIMILARITY_THRESHOLD = 0.5

# 対になる語のペア。同じ話題（タイトルが似ている）に対して両方が出現したら
# 「矛盾の疑い」として検出する。
_NEGATION_PAIRS = [
    ("must not", "must"),
    ("shall not", "shall"),
    ("should not", "should"),
    ("禁止", "許可"),
    ("禁止", "必須"),
    ("不要", "必須"),
    ("無効", "有効"),
    ("してはならない", "しなければならない"),
]


def check_invalid_ids(requirements: List[Requirement]) -> List[ValidationIssue]:
    """IDの形式(REQ-XXX)が正しいか、IDが重複していないかを確認する"""
    issues: List[ValidationIssue] = []
    seen: set[str] = set()

    for r in requirements:
        if not _ID_PATTERN.match(r.id):
            issues.append(ValidationIssue(
                code="INVALID_ID",
                message=f"IDの形式が不正です（REQ-XXX形式が期待される）: {r.id}",
                requirement_ids=[r.id],
            ))
        if r.id in seen:
            issues.append(ValidationIssue(
                code="DUPLICATE_ID",
                message=f"IDが重複しています: {r.id}",
                requirement_ids=[r.id],
            ))
        seen.add(r.id)

    return issues


def check_empty_descriptions(requirements: List[Requirement]) -> List[ValidationIssue]:
    """description/titleが空でないかを確認する"""
    issues: List[ValidationIssue] = []
    for r in requirements:
        if not r.description or not r.description.strip():
            issues.append(ValidationIssue(
                code="EMPTY_DESCRIPTION", message="descriptionが空です", requirement_ids=[r.id],
            ))
        if not r.title or not r.title.strip():
            issues.append(ValidationIssue(
                code="EMPTY_TITLE", message="titleが空です", requirement_ids=[r.id],
            ))
    return issues


def check_missing_source_references(requirements: List[Requirement]) -> List[ValidationIssue]:
    """source_reference（特にsource_text）が設定されているかを確認する"""
    issues: List[ValidationIssue] = []
    for r in requirements:
        ref = r.source_reference
        if ref is None or not ref.source_text or not ref.source_text.strip():
            issues.append(ValidationIssue(
                code="MISSING_SOURCE_REFERENCE",
                message="出典(source_reference.source_text)が設定されていません",
                requirement_ids=[r.id],
            ))
    return issues


def check_source_text_matches_document(
    requirements: List[Requirement], document_text: str
) -> List[ValidationIssue]:
    """出典が仕様書本文に実在するかを再確認する（防御的な二重チェック）。

    抽出ステージのsource_referenceは常にDocumentChunkから機械的に転記されるため
    通常は必ず一致するはずだが、将来的な変更でその保証が崩れた場合に検出できる
    ようにするための最終防衛線。
    """
    issues: List[ValidationIssue] = []
    for r in requirements:
        ref = r.source_reference
        if ref and ref.source_text and ref.source_text not in document_text:
            issues.append(ValidationIssue(
                code="SOURCE_NOT_FOUND",
                message="出典が仕様書本文に見つかりません（捏造の疑い）",
                requirement_ids=[r.id],
            ))
    return issues


def check_duplicates(
    requirements: List[Requirement], threshold: float = DUPLICATE_SIMILARITY_THRESHOLD
) -> List[ValidationIssue]:
    """同じ種別内でdescriptionの類似度が高いものを重複の疑いとして検出する"""
    issues: List[ValidationIssue] = []
    for i in range(len(requirements)):
        for j in range(i + 1, len(requirements)):
            a, b = requirements[i], requirements[j]
            if a.type != b.type:
                continue
            ratio = difflib.SequenceMatcher(None, a.description, b.description).ratio()
            if ratio >= threshold:
                issues.append(ValidationIssue(
                    code="DUPLICATE_REQUIREMENT",
                    message=f"重複の疑いがあります（description類似度{ratio:.2f}）",
                    requirement_ids=[a.id, b.id],
                ))
    return issues


def check_contradictions(requirements: List[Requirement]) -> List[ValidationIssue]:
    """同じ話題（タイトルが似ている）の要求に、対になる語（禁止/許可等）が
    両方出現している場合を「矛盾の疑い」として検出する簡易ヒューリスティック。

    NOTE: 意味理解を伴わない字面ベースの検出であり、真の論理的矛盾の検出を
          保証するものではない（言い回しが異なる場合は検出できない）。
          この限界は`backend/pipeline/requirements/`のREADME/報告書に明記する。
    """
    issues: List[ValidationIssue] = []
    for i in range(len(requirements)):
        for j in range(i + 1, len(requirements)):
            a, b = requirements[i], requirements[j]
            if a.type != b.type:
                continue

            title_ratio = difflib.SequenceMatcher(None, a.title, b.title).ratio()
            if title_ratio < CONTRADICTION_TITLE_SIMILARITY_THRESHOLD:
                continue

            text_a = f"{a.title} {a.description}"
            text_b = f"{b.title} {b.description}"
            for negative, positive in _NEGATION_PAIRS:
                a_has_neg, a_has_pos = negative in text_a, positive in text_a
                b_has_neg, b_has_pos = negative in text_b, positive in text_b
                if (a_has_neg and b_has_pos and not b_has_neg) or (b_has_neg and a_has_pos and not a_has_neg):
                    issues.append(ValidationIssue(
                        code="CONTRADICTION_SUSPECTED",
                        message=f"矛盾の疑いがあります（'{positive}' と '{negative}' が同じ話題に対して出現）",
                        requirement_ids=[a.id, b.id],
                    ))
    return issues


def validate_requirements(
    requirements: List[Requirement], document_text: Optional[str] = None
) -> List[ValidationIssue]:
    """5種類の検証をすべて実行し、検出された問題点を1つのリストにまとめる"""
    issues: List[ValidationIssue] = []
    issues += check_invalid_ids(requirements)
    issues += check_empty_descriptions(requirements)
    issues += check_missing_source_references(requirements)
    issues += check_duplicates(requirements)
    issues += check_contradictions(requirements)
    if document_text is not None:
        issues += check_source_text_matches_document(requirements, document_text)
    return issues
