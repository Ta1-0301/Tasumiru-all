# backend/evaluation/schemas/rubric.py
"""
9つの評価基準の採点基準（ルーブリック）を明示的に定義する。

採点スケール: 0〜5の6段階。
  0 = unacceptable   （不合格）
  1 = poor           （不十分）
  2 = partially acceptable（部分的に許容できる）
  3 = acceptable     （許容できる）
  4 = good           （良好）
  5 = excellent      （優秀）

各基準について「この点数は具体的にどういう状態を指すか」を明文化する。
これにより、ルールベース・LLM-judge・人手評価のいずれで採点しても同じ基準に
揃えられる（採点者/採点方法が変わってもブレないことがこのフレームワークの目的）。

`backend/evaluation/metrics/rule_based.py` のルールベース関数は、ここに書かれた
バンド定義と1対1で対応するように実装されている（一部のモデルでは構造的に
発生しない点数帯があり、その場合は「未使用」と明記している）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal

GENERIC_BANDS: Dict[int, str] = {
    0: "unacceptable（不合格）",
    1: "poor（不十分）",
    2: "partially acceptable（部分的に許容できる）",
    3: "acceptable（許容できる）",
    4: "good（良好）",
    5: "excellent（優秀）",
}

CriterionLevel = Literal["task", "document"]
CriterionMethod = Literal["rule", "llm", "hybrid(llm+rule)", "human"]


@dataclass(frozen=True)
class CriterionRubric:
    key: str
    name_ja: str
    level: CriterionLevel
    method: CriterionMethod
    bands: Dict[int, str]


RUBRIC: Dict[str, CriterionRubric] = {
    "coverage": CriterionRubric(
        key="coverage",
        name_ja="網羅性 (Coverage)",
        level="document",
        method="hybrid(llm+rule)",
        bands={
            0: "正解タスクを1件もカバーできていない",
            1: "正解タスクの25%未満しかカバーできていない",
            2: "正解タスクの25〜50%をカバーできている",
            3: "正解タスクの50〜75%をカバーできている",
            4: "正解タスクの75〜100%未満をカバーできている",
            5: "正解タスクをすべてカバーできている",
        },
    ),
    "traceability": CriterionRubric(
        key="traceability",
        name_ja="追跡可能性 (Traceability)",
        level="task",
        method="rule",
        bands={
            0: "出典が無いのに申告もされていない、または出典が仕様書本文に実在しない（捏造の疑い）",
            1: "（このスコアラーの構造上到達しない: 0またはneeds_review経由の2に分類される）",
            2: "出典が特定できないことを needs_review として正直に申告している",
            3: "出典は実在するが、粒度が粗い（長いチャンク全体を指しているだけ）",
            4: "出典は実在し、章/条項の見出しは無いが十分に絞られた範囲を指している",
            5: "出典は実在し、章/条項の見出し（section）まで特定できている",
        },
    ),
    "specificity": CriterionRubric(
        key="specificity",
        name_ja="具体性 (Specificity)",
        level="task",
        method="llm",
        bands={
            0: "何をすべきか全く分からない（意味の無いタイトルのみ等）",
            1: "曖昧で、対象や成果物が特定できない",
            2: "大まかな方向性は分かるが、具体的な対象/条件が欠けている",
            3: "対象は分かるが、詳細（範囲・条件）がやや不足している",
            4: "対象・範囲・条件が概ね具体的に書かれている",
            5: "対象・範囲・条件が明確で、誰が読んでも同じ理解に至る",
        },
    ),
    "completeness": CriterionRubric(
        key="completeness",
        name_ja="完結性 (Completeness)",
        level="task",
        method="llm",
        bands={
            0: "着手に必要な情報が無い",
            1: "何をすべきかは分かるが着手できるレベルにない",
            2: "着手できるが多くの前提を推測しないといけない",
            3: "着手はできるが完了条件などが曖昧",
            4: "着手・完了判断に必要な情報がほぼ揃っている",
            5: "他の情報を見なくてもこのタスク単体で着手・完了判断ができる",
        },
    ),
    "granularity": CriterionRubric(
        key="granularity",
        name_ja="適切な粒度 (Appropriate granularity)",
        level="task",
        method="rule",
        bands={
            0: "複数の作業が1つのタスクに束ねられている（広すぎる）",
            1: "タイトルが非常に長く、複数要素を含む可能性が高い",
            2: "タイトルが長め、または広すぎる可能性がある",
            3: "短すぎる/長さの境界にあり、粒度の判定がやや難しい",
            4: "1つの作業として適切な粒度になっている",
            5: "1つの作業として適切な粒度で、完了条件も明示されている",
        },
    ),
    "actionability": CriterionRubric(
        key="actionability",
        name_ja="行動可能性 (Actionability)",
        level="task",
        method="rule",
        bands={
            0: "行動を表す動詞が無く、名詞句だけになっている",
            1: "動詞的な表現の手がかりはあるがタイトルが短すぎて判断できない",
            2: "（このスコアラーの構造上到達しない: 1と3の間の遷移が急なため予約）",
            3: "動詞的な表現の手がかりはあるが、明確な行動動詞ではない",
            4: "明確な行動動詞があり、着手可能な記述になっている",
            5: "明確な行動動詞があり、補足説明(description)も伴って着手可能性が高い",
        },
    ),
    "skill_accuracy": CriterionRubric(
        key="skill_accuracy",
        name_ja="必要スキルの正確性 (Required skill accuracy)",
        level="task",
        method="rule",
        bands={
            0: "推定スキルがタスク内容のカテゴリと明確に矛盾している",
            1: "（このスコアラーの構造上到達しない: 中立は3、正直な不明は2に分類される）",
            2: "スキルが明示的に'unknown'（不明を正直に申告している）",
            3: "タイトル側がどのカテゴリにも該当せず判定不能（中立）",
            4: "推定スキルがタスク内容のカテゴリと一致している",
            5: "推定スキルがタスク内容と一致し、かつ複数の具体的スキルが挙げられている",
        },
    ),
    "effort_plausibility": CriterionRubric(
        key="effort_plausibility",
        name_ja="見積り工数の妥当性 (Estimated effort plausibility)",
        level="task",
        method="rule",
        bands={
            0: "見積り工数が非現実的（0以下または500時間超）",
            1: "優先度がhighな割に見積りが極端に長い（200時間超）",
            2: "見積り工数が未設定（unknown、正直な申告として中立）",
            3: "優先度がhighの割に見積りがやや長い（80〜200時間）",
            4: "見積り工数は現実的な範囲だが平均的（40時間超500時間以下）",
            5: "見積り工数が現実的で優先度とも矛盾しない（0〜40時間）",
        },
    ),
    "non_duplication": CriterionRubric(
        key="non_duplication",
        name_ja="非重複性 (Non-duplication)",
        level="document",
        method="rule",
        bands={
            0: "タイトルがほぼ完全に重複しているタスクが存在する",
            1: "重複の疑いのあるタスクの組が3組以上ある",
            2: "重複の疑いのあるタスクの組が2組ある",
            3: "重複の疑いのあるタスクの組が1組ある",
            4: "（このスコアラーの構造上到達しない: 重複無しは5、1組以上は3以下に分類される）",
            5: "重複と判定されたタスクの組が無い",
        },
    ),
}

TASK_LEVEL_CRITERIA = tuple(k for k, v in RUBRIC.items() if v.level == "task")
DOCUMENT_LEVEL_CRITERIA = tuple(k for k, v in RUBRIC.items() if v.level == "document")


def render_bands(criterion: str) -> str:
    """指定した基準の0-5バンド説明を人間可読なテキストに整形する（プロンプト埋め込み用）"""
    bands = RUBRIC[criterion].bands
    return "\n".join(f"{score}: {desc}" for score, desc in sorted(bands.items()))
