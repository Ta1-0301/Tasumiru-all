# backend/pipeline/final_output/json_schema.py
"""
依頼の"Create JSON schema validation"に対応する。

`FinalProjectOutput`（Pydantic v2モデル）から標準的なJSON Schema
(draft 2020-12相当)を生成し、任意の辞書（例: 保存済みのJSONファイルを
読み込んだもの）がそのスキーマに合致するかを検証できるようにする。
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import ValidationError

from backend.pipeline.final_output.schema import FinalProjectOutput


def get_json_schema() -> Dict[str, Any]:
    """最終出力の形式的なJSON Schemaを返す（そのままファイルに保存し、
    外部のツール/フロントエンドと共有できる）。"""
    return FinalProjectOutput.model_json_schema()


def validate_output_json(data: Dict[str, Any]) -> List[str]:
    """辞書がFinalProjectOutputのスキーマに合致するかを検証する。

    合致すれば空リスト、合致しなければ人が読めるエラー文字列のリストを返す
    （例外で呼び出し側を止めない。複数の不備を一度に洗い出せるようにする）。
    """
    try:
        FinalProjectOutput.model_validate(data)
        return []
    except ValidationError as e:
        return [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
