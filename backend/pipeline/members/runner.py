# backend/pipeline/members/runner.py
"""
Phase 6のオーケストレーター。

**このモジュールはLLMを一切呼び出さない。** メンバーのスキルレベルは、
以下のいずれかの経路で取り込まれた値だけを使う:

  - user input        : `Member`を直接構築する（本人がフォーム等で入力した想定）
  - team manager input : 同上（マネージャーが入力した想定）
  - imported data      : `build_member_directory()`にdictのリストを渡す
                          （CSV/JSON等の外部データ取り込みを想定）
  - confirmed historical data : `load_member_directory()`で以前保存した
                          members.jsonを読み込む

取り込みに失敗したレコード（Pydanticスキーマにすら合わない不正な形式）は
LOAD_ERRORとして報告し、**その場で値を作り出して埋め合わせたりしない**
（そのレコードをスキップするだけで、他の正常なレコードの読み込みは継続する）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from pydantic import ValidationError

from backend.pipeline.members.schema import Member, MemberDirectory, ValidationIssue
from backend.pipeline.members.validator import validate_members

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _parse_members(raw_records: List[Dict[str, Any]]) -> Tuple[List[Member], List[ValidationIssue]]:
    members: List[Member] = []
    issues: List[ValidationIssue] = []

    for i, record in enumerate(raw_records):
        try:
            members.append(Member.model_validate(record))
        except ValidationError as e:
            issues.append(ValidationIssue(
                code="LOAD_ERROR",
                message=f"レコード{i}の読み込みに失敗しました: {e}",
                member_id=record.get("id") if isinstance(record, dict) else None,
            ))

    return members, issues


def build_member_directory(
    team_id: str, raw_records: List[Dict[str, Any]]
) -> MemberDirectory:
    """人手入力/マネージャー入力/外部データ取り込みの、生のレコード一覧
    (dictのリスト) からMemberDirectoryを構築し、検証する。
    """
    members, load_issues = _parse_members(raw_records)
    issues = load_issues + validate_members(members)

    return MemberDirectory(
        team_id=team_id,
        members=members,
        issues=issues,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def save_member_directory(
    doc: MemberDirectory,
    output_dir: Path = OUTPUT_DIR,
    *,
    identifier: str | None = None,
) -> Path:
    """members.json を保存する（確定済みデータとして永続化する）

    `identifier`: 呼び出し元が持つ一意なキー（例: project_id）。
    従来はファイル名が `{team_id}_{秒単位タイムスタンプ}.members.json` のみで
    組み立てられており、同一team内の複数の呼び出し元が同じ秒に保存すると
    ファイル名が衝突し、一方のmembers.jsonがもう一方に上書きされる不具合が
    あった。呼び出し元が`identifier`を渡した場合はファイル名に含めることで
    この衝突を避ける（省略時は従来通りのファイル名になる — 後方互換）。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    team_part = doc.team_id or "team"
    if identifier:
        out_path = output_dir / f"{team_part}_{identifier}_{timestamp}.members.json"
    else:
        out_path = output_dir / f"{team_part}_{timestamp}.members.json"
    out_path.write_text(
        json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def load_member_directory(path: Path) -> MemberDirectory:
    """以前保存されたmembers.json（confirmed historical data）を読み込み、再検証する"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_records = data.get("members", [])
    return build_member_directory(data.get("team_id") or "team", raw_records)
