# backend/services/skill_normalization.py
"""
Part 6: Skill Normalization。

スキル名の表記ゆれ（大文字小文字・空白・バージョン番号・よくある略記）を
吸収するための、小さく決定的な正規化層。

**巨大な同義語辞書は作らない。** ここでの正規化は「同じスキルの表記ゆれを
機械的に同一視する」ことだけを目的とし、意味的に異なるスキル同士を
似ていると判定すること（例:「Java」と「JavaScript」を同一視する）はしない
——それはハード制約（`backend.pipeline.assignment.filters`）の判定基盤として
使われるため、誤って別スキルを同一視すると「持っていないスキルを持っている
ことにする」という捏造に等しい結果になる。

ルールは`_EXACT_ALIASES`（既知の表記ゆれの完全一致テーブル）+
汎用的な機械的処理（小文字化・空白正規化・末尾のバージョン数字除去）の
2段構成。`extra_rules`引数で呼び出し側が独自ルールを追加できる
（"configurable/extensible"への対応）。
"""

from __future__ import annotations

import re
from typing import Dict, Optional

# 依頼の例（Part 6）+ 実務でよく見る表記ゆれのみを対象にした最小限のテーブル。
# キーは「_mechanically_normalize()適用後」の文字列。
_EXACT_ALIASES: Dict[str, str] = {
    "fast api": "fastapi",
    "restful api": "rest api",
    "restful apis": "rest api",
    "rest apis": "rest api",
    "node js": "nodejs",
    "node.js": "nodejs",
    "react.js": "react",
    "reactjs": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "next.js": "nextjs",
    "postgres": "postgresql",
    "js": "javascript",
    "ts": "typescript",
}

_VERSION_SUFFIX_RE = re.compile(r"^([a-z][a-z+#]*?)\s*\.?\s*(\d+(?:\.\d+)*)$")
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[_\-/]+")


def _mechanically_normalize(raw: str) -> str:
    """完全一致テーブルを引く前の、機械的な下処理（小文字化・記号/空白の統一）。"""
    text = raw.strip().lower()
    text = _PUNCTUATION_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _strip_version_suffix(text: str) -> str:
    """末尾のバージョン番号を除去する（例: "python3" -> "python", "vue 3" -> "vue"）。

    ただし数字が本質的に名前の一部であるスキルを壊さないよう、除去後の
    文字列が空にならない場合のみ適用する。
    """
    match = _VERSION_SUFFIX_RE.match(text)
    if match and match.group(1):
        return match.group(1)
    return text


def normalize_skill_name(raw: str, extra_rules: Optional[Dict[str, str]] = None) -> str:
    """スキル名を正規化された比較用の文字列に変換する。

    同じスキルの表記ゆれは常に同じ正規化結果になる（決定的）。
    `extra_rules`は`_mechanically_normalize()`適用後の文字列をキーとする
    追加の完全一致テーブルで、呼び出し側固有の表記ゆれを持ち込める。
    """
    if not raw:
        return ""

    text = _mechanically_normalize(raw)

    rules = _EXACT_ALIASES
    if extra_rules:
        rules = {**_EXACT_ALIASES, **extra_rules}

    if text in rules:
        return rules[text]

    text = _strip_version_suffix(text)

    if text in rules:
        return rules[text]

    return text
