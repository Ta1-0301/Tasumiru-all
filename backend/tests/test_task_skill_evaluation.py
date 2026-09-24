# backend/tests/test_task_skill_evaluation.py
"""
Task内容とrequired_skillsの整合性チェック（skill_evaluation.py）のテスト。
LLMは使わない。実測で見つかった不整合（テスト報告書→Figma等）を検出でき、
自然な組み合わせ（React実装→React等）は検出しないことを確認する。
"""

import json

import pytest

from backend.pipeline.requirements.schema import Requirement, RequirementDocument
from backend.pipeline.tasks.runner import run_task_decomposition_pipeline
from backend.pipeline.tasks.schema import Task
from backend.pipeline.tasks.skill_evaluation import (
    SECURITY_SKILL_MISSING,
    SKILL_TASK_MISMATCH,
    check_task_skill_consistency,
    evaluate_task_skills,
    find_unrelated_skills,
    lacks_security_skill,
)
from backend.services.llm import BaseLLMClient


def _task(title, skills, description="", tid="TASK-001"):
    return Task(id=tid, title=title, description=description or title, required_skills=skills, confidence=0.5)


# --- 明らかな不整合を検出する ---

@pytest.mark.parametrize("title, skills, expected", [
    ("テスト報告書を作成する", ["Figma", "Tailwind CSS", "React"], ["Figma", "Tailwind CSS", "React"]),
    ("要件定義書を作成する", ["Figma"], ["Figma"]),
    ("結合テスト計画を作成する", ["Figma", "Tailwind CSS", "React"], ["Figma", "Tailwind CSS"]),
    ("セッショントークン保護に関するドキュメントを作成する", ["Python", "FastAPI"], ["Python", "FastAPI"]),
    ("ユーザー認証APIを実装する", ["Figma"], ["Figma"]),
])
def test_detects_obviously_unrelated_skills(title, skills, expected):
    assert find_unrelated_skills(_task(title, skills)) == expected


# --- 自然な組み合わせは検出しない ---

@pytest.mark.parametrize("title, skills", [
    ("Reactコンポーネントを実装する", ["React"]),
    ("FastAPIで認証APIを実装する", ["FastAPI", "Python"]),
    ("FastAPIアプリケーションのドキュメントを生成する", ["Python", "FastAPI"]),  # 同系統が文面に明記
    ("PostgreSQLのDBスキーマを設計する", ["PostgreSQL"]),
    ("認証トークンの有効期限を設計する", ["認証", "セキュリティ"]),
    ("テスト結果を報告書にまとめる", ["テスト", "技術文書作成"]),
    ("ログイン画面のUIデザインを作成する", ["Figma"]),
    ("APIの結合テストを実施する", ["Python", "FastAPI"]),
    ("デモ環境を構築する", ["Docker"]),
    ("何かをする", ["Figma"]),  # 作業の種類が判定できないものは判定しない（保守的）
    ("テスト報告書を作成する", ["unknown"]),
])
def test_does_not_flag_natural_skills(title, skills):
    assert find_unrelated_skills(_task(title, skills)) == []


def test_skill_written_in_the_task_text_is_always_accepted():
    # 文書作成のタスクでも、文面にReactと書かれていれば妥当
    assert find_unrelated_skills(_task("React導入手順書を作成する", ["React"])) == []


def test_english_short_keywords_do_not_match_inside_other_words():
    # "guide"の中の"ui"を画面系の作業と誤認しない
    assert find_unrelated_skills(_task("セットアップguideの資料を作成する", ["Figma"])) == ["Figma"]


# --- セキュリティ系の作業でセキュリティ系スキルが無い ---

def test_security_work_without_security_skill_is_reported():
    assert lacks_security_skill(_task("セッショントークン暗号化処理を実装する", ["Python", "PostgreSQL"]))
    assert not lacks_security_skill(_task("セッショントークン暗号化処理を実装する", ["セキュリティ", "Python"]))
    assert not lacks_security_skill(_task("商品一覧APIを実装する", ["Python"]))


# --- ValidationIssue化と集計 ---

def test_consistency_check_returns_issues_without_modifying_tasks():
    tasks = [
        _task("テスト報告書を作成する", ["Figma"], tid="TASK-001"),
        _task("Reactコンポーネントを実装する", ["React"], tid="TASK-002"),
        _task("パスワードをハッシュ化して保存する", ["Python"], tid="TASK-003"),
    ]
    before = [t.model_copy(deep=True) for t in tasks]
    issues = check_task_skill_consistency(tasks)

    assert [(i.code, i.task_ids) for i in issues] == [
        (SKILL_TASK_MISMATCH, ["TASK-001"]),
        (SECURITY_SKILL_MISSING, ["TASK-003"]),
    ]
    assert tasks == before  # required_skillsは書き換えない


def test_evaluate_task_skills_summary():
    tasks = [
        _task("テスト報告書を作成する", ["Figma", "React"], tid="TASK-001"),
        _task("Reactコンポーネントを実装する", ["React"], tid="TASK-002"),
        _task("要件を確認する", ["unknown"], tid="TASK-003"),
        _task("セッショントークンを暗号化する", ["Python"], tid="TASK-004"),
    ]
    e = evaluate_task_skills(tasks)
    assert (e.total_tasks, e.tasks_with_skills, e.mismatched_tasks, e.mismatch_rate) == (4, 3, 1, 25.0)
    assert [m.skill for m in e.mismatches] == ["Figma", "React"]
    assert e.security_skill_missing_tasks == ["TASK-004"]
    assert evaluate_task_skills([]).mismatch_rate == 0.0


# --- パイプラインへの組み込み: needs_reviewの印を付けるだけ ---

class _FixedTasksLLM(BaseLLMClient):
    model = "fake"

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        return json.dumps({"tasks": [
            {"title": "テスト報告書を作成する", "description": "結合テストの結果を報告書にまとめる",
             "priority": "medium", "estimated_hours": 4, "required_skills": ["Figma", "React"],
             "acceptance_criteria": ["報告書が提出されている"], "confidence": 0.8},
            {"title": "Reactコンポーネントを実装する", "description": "ログイン画面をReactで実装する",
             "priority": "high", "estimated_hours": 8, "required_skills": ["React"],
             "acceptance_criteria": ["ログインできる"], "confidence": 0.9},
        ]}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_pipeline_marks_mismatched_tasks_for_review_but_keeps_their_skills():
    doc = RequirementDocument(document_id="spec", requirements=[Requirement(
        id="REQ-001", type="functional", title="結合テスト", description="結合テストを実施し報告書にまとめる",
        priority="high", origin="explicit", confidence=0.9,
    )])
    result = await run_task_decomposition_pipeline(doc, _FixedTasksLLM())

    report, react = result.tasks
    assert report.required_skills == ["Figma", "React"]  # 書き換えていない
    assert report.needs_review and any(r.startswith(SKILL_TASK_MISMATCH) for r in report.review_reasons)
    assert react.required_skills == ["React"]
    assert not any(r.startswith(SKILL_TASK_MISMATCH) for r in react.review_reasons)
    assert any(i.code == SKILL_TASK_MISMATCH and i.task_ids == [report.id] for i in result.issues)


def test_role_phrases_are_not_treated_as_the_kind_of_work():
    # 「フロントエンド担当者と」は人の話であり、UI系の作業ではない（実測で見つかった検出漏れ）
    task = _task("結合テスト計画の作成", ["Figma", "Tailwind CSS", "React"],
                 description="フロントエンド担当者との結合テストの計画を作成する")
    assert find_unrelated_skills(task) == ["Figma", "Tailwind CSS"]
    # 作業そのものがフロントエンドなら従来どおり自然
    assert find_unrelated_skills(_task("フロントエンドの画面を実装する", ["React"])) == []


# --- STEP 3（最終安定化）で追加したケース ---

@pytest.mark.parametrize("title, skills, expected", [
    ("結合テストを実施する", ["Figma"], ["Figma"]),                      # テスト + Figma
    ("運用マニュアルを作成する", ["React"], ["React"]),                   # 文書 + React
    ("管理者の削除ロジックを検証する", ["scikit-learn"], ["scikit-learn"]),  # 実測で残った混入
])
def test_detects_mismatches_reported_in_step3(title, skills, expected):
    assert find_unrelated_skills(_task(title, skills)) == expected


@pytest.mark.parametrize("title, skills", [
    ("Reactでログイン画面を実装する", ["React", "TypeScript", "HTML/CSS"]),
    ("FastAPIで認証APIを実装する", ["FastAPI", "Python"]),
    ("PostgreSQLのテーブルを設計する", ["PostgreSQL"]),
    ("管理画面のUIをFigmaで設計する", ["Figma"]),
    ("SQLAlchemyを使用した簡単なモックデータの作成", ["SQLAlchemy", "Python"]),  # 実測で誤検出していた
    ("セッショントークンの保存方法を分析する", ["セキュリティ"]),
])
def test_accepts_natural_skills_reported_in_step3(title, skills):
    assert find_unrelated_skills(_task(title, skills)) == []


@pytest.mark.parametrize("title, description, skills, expected", [
    # 目的がセキュリティで、セキュリティ系スキルが無い → 検出
    ("暗号化ロジックを実装する", "", ["Python", "PostgreSQL"], True),
    ("セッショントークンの保存方法を分析する", "トークンを平文で保存しない方式を検討する", ["Python"], True),
    # セキュリティ系スキル（日本語・英語・具体的な方式）があれば検出しない
    ("暗号化ロジックを実装する", "", ["Python", "セキュリティ"], False),
    ("パスワードをハッシュ化して保存する", "", ["Python", "bcrypt"], False),
    ("Encrypt session tokens", "暗号化する", ["Python", "Cryptography"], False),
    # 目的がセキュリティでない作業は対象外（全Taskにセキュリティを要求しない）
    ("PostgreSQLにユーザー情報を保存する", "", ["PostgreSQL"], False),
    ("セッション一覧画面を実装する", "ログイン中のセッションを一覧表示する", ["React"], False),
    # スキル未特定は別の問題として扱う
    ("暗号化ロジックを実装する", "", ["unknown"], False),
])
def test_security_skill_missing_requires_security_purpose(title, description, skills, expected):
    assert lacks_security_skill(_task(title, skills, description=description)) is expected


def test_evaluation_never_rewrites_required_skills():
    tasks = [
        _task("テスト報告書を作成する", ["Figma", "React"], tid="TASK-001"),
        _task("暗号化ロジックを実装する", ["Python", "PostgreSQL"], tid="TASK-002"),
    ]
    snapshot = [list(t.required_skills) for t in tasks]
    check_task_skill_consistency(tasks)
    evaluate_task_skills(tasks)
    assert [t.required_skills for t in tasks] == snapshot
