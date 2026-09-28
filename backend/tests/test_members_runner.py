# backend/tests/test_members_runner.py
"""backend/pipeline/members/runner.py の単体テスト。LLMは一切使わない。"""

import json
from datetime import datetime

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


def test_save_member_directory_uses_identifier_to_avoid_filename_collision(tmp_path, monkeypatch):
    """回帰テスト: 同一team_id・同一秒に保存しても、呼び出し側が渡す
    identifier(project_id相当)が異なればファイル名が衝突しないことを確認する
    （修正前は`{team_id}_{秒単位タイムスタンプ}.members.json`のみでファイル名を
    決めており、同じ秒に別プロジェクトが保存すると上書きされていた）。"""
    import backend.pipeline.members.runner as runner_module

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(runner_module, "datetime", _FrozenDatetime)

    directory_a = build_member_directory("team_shared", [_valid_record("M-ALICE")])
    directory_b = build_member_directory("team_shared", [_valid_record("M-BOB")])

    path_a = save_member_directory(directory_a, output_dir=tmp_path, identifier="project-a")
    path_b = save_member_directory(directory_b, output_dir=tmp_path, identifier="project-b")

    assert path_a != path_b
    assert path_a.exists()
    assert path_b.exists()

    reloaded_a = load_member_directory(path_a)
    reloaded_b = load_member_directory(path_b)
    assert [m.id for m in reloaded_a.members] == ["M-ALICE"]
    assert [m.id for m in reloaded_b.members] == ["M-BOB"]


def test_save_member_directory_without_identifier_keeps_legacy_filename_format(tmp_path, monkeypatch):
    """identifierを渡さない既存の呼び出し方でも、従来通りのファイル名形式
    (`{team_id}_{タイムスタンプ}.members.json`)のままであることを確認する
    （後方互換性の回帰テスト）。"""
    import backend.pipeline.members.runner as runner_module

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(runner_module, "datetime", _FrozenDatetime)

    directory = build_member_directory("team_1", [_valid_record()])
    out_path = save_member_directory(directory, output_dir=tmp_path)

    assert out_path.name == "team_1_20260101T120000Z.members.json"


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
