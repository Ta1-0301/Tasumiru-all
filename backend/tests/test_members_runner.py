# backend/tests/test_members_runner.py
"""backend/pipeline/members/runner.py の単体テスト。LLMは一切使わない。"""

import json

from backend.pipeline.members.runner import (
    build_member_directory,
    load_member_directory,
    save_member_directory,
)


def _valid_record(id="M-001"):
    return {
        "id": id,
        "name": "山田太郎",
        "skills": [{"skill": "Python", "level": 5, "experience_years": 3}],
        "availability": {
            "available_hours_per_week": 40,
            "working_days": ["Monday", "Tuesday"],
            "current_assigned_hours": 10,
        },
        "constraints": [{"type": "scope_restriction", "value": "backend"}],
    }


def test_build_member_directory_parses_valid_records():
    directory = build_member_directory("team_1", [_valid_record()])
    assert directory.team_id == "team_1"
    assert len(directory.members) == 1
    assert directory.members[0].id == "M-001"
    assert directory.issues == []


def test_build_member_directory_reports_load_error_without_dropping_other_records():
    """1件の取り込みに失敗しても他の正常なレコードは読み込みを継続する"""
    malformed = {"id": "M-002"}  # nameとavailabilityが無く、スキーマとして無効
    directory = build_member_directory("team_1", [_valid_record(), malformed])

    assert len(directory.members) == 1
    assert directory.members[0].id == "M-001"
    assert any(i.code == "LOAD_ERROR" for i in directory.issues)


def test_build_member_directory_never_invents_missing_fields():
    """取り込みに失敗したレコードの欠損値を推測で埋めたりしない
    （メンバーのスキルレベルがLLMや推測で作り出されないことの土台）"""
    malformed = {"id": "M-003", "name": "不完全"}  # availability無し
    directory = build_member_directory("team_1", [malformed])
    assert directory.members == []
    assert any(i.code == "LOAD_ERROR" and i.member_id == "M-003" for i in directory.issues)


def test_build_member_directory_runs_validation_on_parsed_members():
    record = _valid_record()
    record["skills"][0]["level"] = 99  # 不正なスキルレベル
    directory = build_member_directory("team_1", [record])
    assert any(i.code == "INVALID_SKILL_LEVEL" for i in directory.issues)


def test_save_and_load_member_directory_round_trip(tmp_path):
    directory = build_member_directory("team_1", [_valid_record()])
    out_path = save_member_directory(directory, output_dir=tmp_path)

    assert out_path.exists()
    loaded_json = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded_json["team_id"] == "team_1"
    assert len(loaded_json["members"]) == 1

    reloaded = load_member_directory(out_path)
    assert reloaded.team_id == "team_1"
    assert reloaded.members[0].id == "M-001"
    assert reloaded.issues == []  # 再検証しても問題なし
