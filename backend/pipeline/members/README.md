# backend/pipeline/members/

Phase 6: タスクアサインのための、構造化されたメンバー情報。

**このパッケージにLLMは一切使われていない**（コード中に`BaseLLMClient`への
依存が無いことで確認できる）。メンバーのスキルレベルは常に人間が入力した
値・外部データ・過去の確定済みデータのいずれかから来る。

```
user input / manager input / imported data / historical data
    ↓
Member Validation   (validator.py — 決定的)
    ↓
members.json         (runner.py が output/ に保存)
```

**タスクアサイン（割り当てロジック）はこのフェーズでは実装しない。**

## モジュール構成

| ファイル | 役割 |
|---|---|
| `schema.py` | `Member`/`Skill`/`Availability`/`Constraint`/`MemberDirectory`。数値・文字列フィールドはあえて緩く型付けし、`validator.py`が意味のある検証結果を返せるようにしている |
| `validator.py` | Member Validation。無効なスキルレベル・負の時間・キャパシティ超過・スキル重複・不正な制約を検出する決定的な処理 |
| `runner.py` | 生データ(dict)からの取り込み・検証・`members.json`への保存。**LLM呼び出しは一切含まない** |

## スキルレベル

| 値 | 意味 |
|---|---|
| 1 | Beginner |
| 2 | Basic |
| 3 | Intermediate |
| 4 | Advanced |
| 5 | Expert |

## 制約(Constraint)の構造

自由記述の文字列ではなく、`type`ごとに構造化されたフィールドを持つ:

| type | 使うフィールド | 例 |
|---|---|---|
| `scope_restriction` | `value` | `{"type": "scope_restriction", "value": "frontend"}` |
| `day_unavailable` | `value`（曜日名） | `{"type": "day_unavailable", "value": "Monday"}` |
| `max_hours_per_week` | `max_hours` | `{"type": "max_hours_per_week", "max_hours": 8}` |
| `requires_review` | `value`（説明） | `{"type": "requires_review", "value": "senior member"}` |

## 「決して負のキャパシティを許容しない」について

`Availability.remaining_capacity`は`available_hours_per_week - current_assigned_hours`
の生の計算値を返す（負になり得る）。この値を黒黒に0へクランプするのではなく、
`validator.check_workload_above_capacity`が負のキャパシティを常に明示的な
検証エラーとして検出することで、この要件を満たす。

## 使い方

```python
from backend.pipeline.members.runner import build_member_directory, save_member_directory

records = [
    {
        "id": "M-001", "name": "山田太郎",
        "skills": [{"skill": "Python", "level": 5, "experience_years": 3}],
        "availability": {"available_hours_per_week": 40, "working_days": ["Monday", "Tuesday"], "current_assigned_hours": 10},
        "constraints": [{"type": "scope_restriction", "value": "backend"}],
    },
]
directory = build_member_directory("team_1", records)
save_member_directory(directory)
```

## 既知の限界

- `check_duplicate_skills`は大文字小文字の違いを無視して同一スキル名を検出するが、
  表記のゆれ（例: "JS" と "JavaScript"）までは検出しない。
