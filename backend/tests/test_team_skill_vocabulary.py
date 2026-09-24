# backend/tests/test_team_skill_vocabulary.py
"""
STEP 2: Task生成時のチームスキル語彙（team_skill_vocabulary）のテスト。

- 語彙の生成（重複除去・表記ゆれの集約）
- Task生成関数・パイプラインへの受け渡し
- 語彙なし(None)のときにプロンプトが従来と完全に同一であること
- プロンプトが「参考語彙」としての指示になっており、置き換え・追加・担当者決定を
  強制していないこと
- LLM呼び出し回数が増えないこと
"""

import json

import pytest

from backend.pipeline.members.schema import Availability, Member, Skill
from backend.pipeline.requirements.schema import Requirement, RequirementDocument, SourceReference
from backend.pipeline.tasks import decomposer as decomposer_module
from backend.pipeline.tasks.decomposer import (
    _DECOMPOSITION_PROMPT,
    decompose_requirement,
    format_team_skill_vocabulary_context,
)
from backend.pipeline.tasks.runner import run_task_decomposition_pipeline
from backend.pipeline.tasks.skill_vocabulary import build_team_skill_vocabulary
from backend.services.llm import BaseLLMClient

_TASK_JSON = json.dumps({"tasks": [{
    "title": "商品取得APIを実装する", "description": "FastAPIで商品情報を返すAPIを実装する",
    "priority": "high", "estimated_hours": 8, "required_skills": ["FastAPI", "Python"],
    "acceptance_criteria": ["商品一覧が取得できる"], "confidence": 0.9,
}]}, ensure_ascii=False)


class RecordingLLMClient(BaseLLMClient):
    """受け取ったプロンプトを記録し、固定のタスクJSONを返す"""

    def __init__(self):
        self.model = "fake"
        self.prompts = []

    async def complete(self, prompt: str, *, json_mode: bool = False) -> str:
        self.prompts.append(prompt)
        return _TASK_JSON


def _member(mid, *skills):
    return Member(
        id=mid, name=f"member-{mid}",
        skills=[Skill(skill=s, level=3) for s in skills],
        availability=Availability(available_hours_per_week=40, working_days=["Monday"]),
    )


def _requirement(rid="REQ-001", description="FastAPIを利用して商品情報を取得するAPIを実装する"):
    return Requirement(
        id=rid, type="functional", title="商品情報API", description=description,
        priority="high", origin="explicit", confidence=0.9,
        source_reference=SourceReference(document_id="spec", source_text=description),
    )


# --- Test 1: 語彙の生成 ---

def test_vocabulary_deduplicates_across_members():
    members = [_member("A", "Python", "FastAPI"), _member("B", "Python", "React")]
    assert build_team_skill_vocabulary(members) == ["Python", "FastAPI", "React"]


def test_vocabulary_merges_spelling_variants_with_existing_normalization_and_keeps_first_form():
    # 既存のnormalize_skill_name（Assignmentのハード制約と同じ正規化）で同一視されるものだけを集約する
    members = [_member("A", "Python3", "Fast API"), _member("B", "python", "FastAPI", "PostgreSQL")]
    assert build_team_skill_vocabulary(members) == ["Python3", "Fast API", "PostgreSQL"]


def test_vocabulary_does_not_merge_different_skills():
    members = [_member("A", "Java", "JavaScript")]
    assert build_team_skill_vocabulary(members) == ["Java", "JavaScript"]


def test_vocabulary_ignores_blank_names_and_handles_no_members():
    assert build_team_skill_vocabulary([]) == []
    assert build_team_skill_vocabulary([_member("A", "  ", "React")]) == ["React"]


def test_vocabulary_is_capped():
    members = [_member("A", "Go", "Rust", "Kotlin", "Swift", "Ruby")]
    assert build_team_skill_vocabulary(members, max_size=3) == ["Go", "Rust", "Kotlin"]


# --- Test 2: Task生成関数・パイプラインへの受け渡し ---

@pytest.mark.asyncio
async def test_pipeline_passes_vocabulary_to_each_decomposition(monkeypatch):
    import backend.pipeline.tasks.runner as runner_module

    received = []

    async def fake_decompose(requirement, client, **kwargs):
        received.append(kwargs.get("team_skill_vocabulary"))
        return [], None

    monkeypatch.setattr(runner_module, "decompose_requirement", fake_decompose)
    doc = RequirementDocument(document_id="spec", requirements=[_requirement("REQ-001"), _requirement("REQ-002")])
    await run_task_decomposition_pipeline(doc, RecordingLLMClient(), team_skill_vocabulary=["Python", "React"])

    assert received == [["Python", "React"], ["Python", "React"]]


@pytest.mark.asyncio
async def test_pipeline_without_vocabulary_keeps_legacy_two_argument_call(monkeypatch):
    """既存テストと同じ2引数のフェイクでも動く（キーワード引数を渡さない）"""
    import backend.pipeline.tasks.runner as runner_module

    calls = []

    async def legacy_fake(requirement, client):
        calls.append(requirement.id)
        return [], None

    monkeypatch.setattr(runner_module, "decompose_requirement", legacy_fake)
    doc = RequirementDocument(document_id="spec", requirements=[_requirement()])
    await run_task_decomposition_pipeline(doc, RecordingLLMClient())
    await run_task_decomposition_pipeline(doc, RecordingLLMClient(), team_skill_vocabulary=[])

    assert calls == ["REQ-001", "REQ-001"]


@pytest.mark.asyncio
async def test_llm_call_count_is_unchanged_one_call_per_requirement():
    doc = RequirementDocument(document_id="spec", requirements=[_requirement("REQ-001"), _requirement("REQ-002")])

    without = RecordingLLMClient()
    await run_task_decomposition_pipeline(doc, without)
    with_vocab = RecordingLLMClient()
    result = await run_task_decomposition_pipeline(doc, with_vocab, team_skill_vocabulary=["Python", "FastAPI"])

    assert len(without.prompts) == len(with_vocab.prompts) == 2
    assert [t.required_skills for t in result.tasks] == [["FastAPI", "Python"], ["FastAPI", "Python"]]


# --- Test 3: 語彙なし(None)は従来と完全に同一 ---

@pytest.mark.asyncio
async def test_prompt_without_vocabulary_is_identical_to_legacy_prompt():
    requirement = _requirement()
    legacy_prompt = _DECOMPOSITION_PROMPT.format(
        requirement_type=requirement.type,
        requirement_title=requirement.title,
        requirement_description=requirement.description,
        extra_context="",
    )

    for kwargs in ({}, {"team_skill_vocabulary": None}, {"team_skill_vocabulary": []}, {"team_skill_vocabulary": ["  "]}):
        client = RecordingLLMClient()
        candidates, error = await decompose_requirement(requirement, client, **kwargs)
        assert error is None
        assert client.prompts == [legacy_prompt]
        assert candidates[0].required_skills == ["FastAPI", "Python"]


# --- Test 4: 語彙がプロンプトに含まれる ---

@pytest.mark.asyncio
async def test_prompt_contains_team_vocabulary_as_spelling_table():
    client = RecordingLLMClient()
    await decompose_requirement(_requirement(), client, team_skill_vocabulary=["Python", "FastAPI", "PostgreSQL"])

    prompt = client.prompts[0]
    assert "## 表記対応表" in prompt
    assert "\nPython, FastAPI, PostgreSQL\n" in prompt
    # 要求本文・出力形式など既存の部分はそのまま残っている
    assert "FastAPIを利用して商品情報を取得するAPIを実装する" in prompt
    assert '"required_skills": ["スキル名"]' in prompt
    # 決め方（意味・順序・例）が表記対応表より前にあり、どちらも要求の後・出力形式の前にある
    assert (prompt.index("## 要求") < prompt.index("## required_skillsの決め方")
            < prompt.index("## 表記対応表") < prompt.index("出力は必ず以下のJSON形式のみ"))


def test_vocabulary_names_with_braces_do_not_break_prompt_formatting():
    context = format_team_skill_vocabulary_context(["C{++}", "Python"])
    assert "\nC{++}, Python\n" in context


# --- Test 5: 置き換え・追加・担当者決定を強制しない ---

def test_vocabulary_section_defines_required_skills_by_the_work_not_by_the_team():
    section = format_team_skill_vocabulary_context(["Python", "React"])

    # required_skillsの意味: タスクの実行に必要なもの。担当者候補・チームのスキルではない
    assert "そのタスクを実行するために必要な技術・知識・能力" in section
    assert "担当者候補・チームが持っているスキル・担当者を見つけるためのスキルではありません" in section
    assert "仕様書に名前が出てくるだけの技術" in section


def test_vocabulary_section_orders_judgement_before_the_table_and_forbids_substitution():
    section = format_team_skill_vocabulary_context(["Python", "React"])

    steps = ["1. そのタスクで具体的に何をするか", "2. その作業を行うために必要なスキルを、作業内容だけから判断",
             "3. 判断したスキルと同じスキルが", "4. 表記対応表に同じスキルが無ければ", "5. 作業に使わないスキルは追加しない"]
    positions = [section.index(s) for s in steps]
    assert positions == sorted(positions)
    assert "別のスキルに置き換えない" in section
    assert "表記対応表に載っているという理由で追加しない" in section
    assert "スキルを選ぶための一覧ではない" in section
    # 語彙の使用を義務づける強い指示を含まない
    assert "必ず" not in section
    assert "のみを使" not in section


def test_vocabulary_section_examples_do_not_show_answers_outside_the_task_text():
    """例の答え（required_skills）に、例のタスク文に書かれていないスキル名を出さない。
    v3では例の答え「技術文書作成」「要件定義」がそのままLLMの出力に写ったため。"""
    import re

    section = format_team_skill_vocabulary_context(["Python", "React", "Figma"])
    examples = re.findall(r"「([^」]+)」→ \[([^\]]*)\]", section)
    assert len(examples) >= 4
    for task_text, answer in examples:
        skills = re.findall(r'"([^"]+)"', answer)
        assert skills, task_text
        # 答えのスキルは、例のタスク文に書かれた技術か、それを使うのに直接必要な言語など
        written = [sk for sk in skills if sk in task_text]
        assert written, f"例「{task_text}」の答え{skills}がタスク文に一つも書かれていない"
    # 技術を使わない作業・セキュリティの扱いは、具体的なスキル名の答えを示さずに説明している
    assert "技術文書作成" not in section
    assert '["要件定義"]' not in section
    assert '["テスト"' not in section
    assert '["セキュリティ"]' not in section


def test_vocabulary_section_security_rule_is_conditional_on_the_purpose_of_the_work():
    section = format_team_skill_vocabulary_context(["Python"])
    assert "作業の目的がセキュリティにある場合" in section
    assert "目的がセキュリティでない作業には付けない" in section


def test_vocabulary_section_says_most_team_skills_are_unrelated_to_the_task():
    section = format_team_skill_vocabulary_context(["Python", "scikit-learn"])
    assert "チーム全体のスキルなので、ほとんどはこのタスクとは無関係です" in section
    assert section.index("ほとんどはこのタスクとは無関係") < section.index("\nPython, scikit-learn\n")


def test_vocabulary_section_is_not_part_of_the_legacy_template():
    """節はテンプレート本体に埋め込まれておらず、語彙がある時だけ追加される"""
    assert "表記対応表" not in _DECOMPOSITION_PROMPT
    assert decomposer_module.format_team_skill_vocabulary_context(None) == ""


def test_vocabulary_section_discourages_unknown_for_non_technical_work():
    """v4の実測で、技術を使わない作業（テスト・文書・レビュー）のスキルが "unknown" になったため"""
    section = format_team_skill_vocabulary_context(["Python"])
    assert "技術やツールを使わない作業にも必要なスキルはある" in section
    assert "作業内容に書かれている作業の種類や対象分野を、そのままスキル名として書く" in section
    assert '"unknown" にしない' in section
