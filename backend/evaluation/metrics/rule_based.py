# backend/evaluation/metrics/rule_based.py
"""
決定的（ルールベース）に計算できる評価指標。LLMを一切使わないため、
同じ入力に対して常に同じスコアが出る（再現性がある・捏造の余地がない）。

採点スケールは0-5（`backend/evaluation/schemas/rubric.py`のRUBRICを参照）。
各関数のコメントに書かれた点数は、RUBRIC[<criterion>].bands の説明と1対1で
対応するように実装している。

対象: traceability / actionability / granularity / skill_accuracy /
      effort_plausibility（タスク単位）、non_duplication / coverageの採点バンド
      （文書単位）
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

ACTION_VERBS = [
    "実装する", "作成する", "提出する", "確認する", "検証する", "実施する",
    "テストする", "レビューする", "設計する", "登録する", "修正する", "記載する",
    "整理する", "準備する", "調整する", "指定する", "アサインする", "デプロイする",
    "共有する", "報告する",
]

UNKNOWN_SKILL_SENTINEL = ["unknown"]

SKILL_CATEGORY_KEYWORDS = {
    "backend": {
        "title": ["API", "実装", "バックエンド", "サーバー", "DB", "データベース", "エンドポイント", "バリデーション"],
        "skill": ["python", "fastapi", "sqlalchemy", "バックエンド", "api", "サーバー"],
    },
    "frontend": {
        "title": ["画面", "UI", "デザイン", "フロントエンド", "表示"],
        "skill": ["figma", "デザイン", "react", "vite", "typescript", "css", "html", "フロントエンド"],
    },
    "test": {
        "title": ["テスト", "検証", "結合テスト", "QA", "確認"],
        "skill": ["テスト", "qa", "pytest", "品質"],
    },
    "docs": {
        "title": ["README", "ドキュメント", "報告書", "記載", "まとめる"],
        "skill": ["ドキュメント", "技術文書", "ライティング"],
    },
    "security": {
        "title": ["セキュリティ", "トークン", "平文", "暗号"],
        "skill": ["セキュリティ", "レビュー"],
    },
}


def score_traceability(
    source_excerpt: Optional[str],
    needs_review: bool,
    spec_text: str,
    heading: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """出典(source_reference.excerpt)が実在し、どれだけ絞り込まれた粒度で
    特定できているかを採点する（RUBRIC["traceability"]）。
    """
    issues: List[str] = []

    if not source_excerpt:
        if needs_review:
            issues.append("出典が特定できず、正直にneeds_reviewとして申告している")
            return 2, issues
        issues.append("出典が無いのにneeds_reviewが立っていない（見落としの疑い）")
        return 0, issues

    if source_excerpt not in spec_text:
        issues.append("source_referenceのexcerptが仕様書本文に実在しない（出典の捏造の疑い）")
        return 0, issues

    if heading:
        return 5, issues

    if len(source_excerpt) <= 120:
        return 4, issues

    issues.append("出典チャンクが長く、粒度が粗い（章/条項の見出しも特定できていない）")
    return 3, issues


def score_actionability(title: str, description: Optional[str] = None) -> Tuple[int, List[str]]:
    """明確な行動動詞を持ち、着手可能な記述になっているか（RUBRIC["actionability"]）"""
    issues: List[str] = []
    verb_hits = [v for v in ACTION_VERBS if v in title]
    ends_with_suru = bool(re.search(r"(する|すること)$", title))

    if not verb_hits and not ends_with_suru:
        issues.append("行動を表す動詞が見当たらない（名詞句だけになっている可能性）")
        return 0, issues

    if len(title) < 6:
        issues.append("タイトルが短すぎて何をすべきか分からない")
        return 1, issues

    score = 4 if verb_hits else 3
    if description and len(description.strip()) >= 10:
        score = 5

    return score, issues


def score_granularity(
    title: str, acceptance_criteria: Optional[List[str]] = None
) -> Tuple[int, List[str]]:
    """粒度が適切か（複数タスクの束ねすぎ・広すぎ/狭すぎ）（RUBRIC["granularity"]）"""
    issues: List[str] = []

    verb_count = sum(title.count(v) for v in ACTION_VERBS)
    conjunction_hits = any(c in title for c in ["、また", "および", "かつ", "、そして", "とともに"])

    if verb_count >= 2 or conjunction_hits:
        issues.append("複数の作業が1つのタスクに束ねられている可能性（粒度が広すぎる）")
        return 0, issues

    length = len(title)
    if length > 80:
        issues.append("タイトルが非常に長く、複数の要素を含んでいる可能性")
        return 1, issues
    if length > 60:
        issues.append("タイトルが長く、複数の要素を含んでいる可能性")
        return 2, issues
    if length < 4:
        issues.append("タイトルが短すぎて粒度を判定しづらい")
        return 3, issues

    score = 4
    if acceptance_criteria:
        score = 5
    return score, issues


def score_skill_accuracy(title: str, required_skills: Optional[List[str]]) -> Tuple[int, List[str]]:
    """必要スキルの推定がタスク内容と整合しているか（RUBRIC["skill_accuracy"]）"""
    issues: List[str] = []
    required_skills = required_skills or []
    skill_lower = " ".join(required_skills).lower()
    title_lower = title or ""

    if required_skills == UNKNOWN_SKILL_SENTINEL:
        issues.append("required_skillsが明示的に'unknown'（正直な申告として中立点）")
        return 2, issues

    matched_categories = []
    for category, kw in SKILL_CATEGORY_KEYWORDS.items():
        title_match = any(k.lower() in title_lower.lower() for k in kw["title"])
        skill_match = any(k.lower() in skill_lower for k in kw["skill"])
        if title_match and skill_match:
            matched_categories.append(category)

    if matched_categories:
        return (5 if len(required_skills) >= 2 else 4), issues

    any_title_category = any(
        any(k.lower() in title_lower.lower() for k in kw["title"])
        for kw in SKILL_CATEGORY_KEYWORDS.values()
    )
    if not any_title_category:
        # タイトル側がどのカテゴリにも該当せず判定不能（ペナルティなしの中立点）
        return 3, issues

    issues.append("必要スキルの推定がタスク内容のカテゴリと一致しない")
    return 0, issues


def score_effort_plausibility(estimated_hours: Optional[float], priority: str) -> Tuple[int, List[str]]:
    """見積り工数(estimated_hours)が現実的か、priorityと著しく矛盾しないか（RUBRIC["effort_plausibility"]）"""
    issues: List[str] = []

    if estimated_hours is None:
        issues.append("estimated_hoursが未設定（unknown、正直な申告として中立点）")
        return 2, issues

    if estimated_hours <= 0 or estimated_hours > 500:
        issues.append(f"estimated_hoursの値が非現実的 ({estimated_hours})")
        return 0, issues

    if (priority or "").lower() == "high" and estimated_hours > 80:
        if estimated_hours > 200:
            issues.append("priorityがhighの割に見積り時間が極端に長い")
            return 1, issues
        issues.append("priorityがhighの割に見積り時間がやや長い")
        return 3, issues

    if estimated_hours <= 40:
        return 5, issues
    return 4, issues


def score_non_duplication(
    tasks: List[Dict[str, Any]],
    near_threshold: float = 0.6,
    exact_threshold: float = 0.92,
) -> Tuple[int, List[str]]:
    """生成されたタスク一覧内での重複を検出する（文書単位、RUBRIC["non_duplication"]）"""
    issues: List[str] = []
    near_dup_pairs = 0
    has_exact_dup = False

    titles = [str(t.get("title", "")) for t in tasks]
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            ratio = difflib.SequenceMatcher(None, titles[i], titles[j]).ratio()
            if ratio >= near_threshold:
                near_dup_pairs += 1
                issues.append(f"重複の疑い: 「{titles[i]}」と「{titles[j]}」(類似度{ratio:.2f})")
            if ratio >= exact_threshold:
                has_exact_dup = True

    if has_exact_dup:
        return 0, issues
    if near_dup_pairs == 0:
        return 5, issues
    if near_dup_pairs == 1:
        return 3, issues
    if near_dup_pairs == 2:
        return 2, issues
    return 1, issues


def score_coverage_band(covered_count: int, total_count: int) -> Tuple[int, List[str]]:
    """正解タスクのカバー率を0-5のバンドに機械的にマッピングする（RUBRIC["coverage"]）。

    「どのタスクが意味的にカバーされているか」の判定はLLM-judgeが行うが、
    それを何点にするかは決定的な閾値でここで計算する（採点自体の再現性を保つため）。
    """
    if total_count <= 0:
        return 5, ["正解タスクが0件のためcoverageは判定不能（データセットの不備の可能性）"]

    ratio = covered_count / total_count
    if ratio >= 1.0:
        return 5, []
    if ratio >= 0.75:
        return 4, []
    if ratio >= 0.5:
        return 3, []
    if ratio >= 0.25:
        return 2, []
    if ratio > 0:
        return 1, []
    return 0, ["正解タスクを1件もカバーできていない"]
