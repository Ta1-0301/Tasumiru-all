# backend/tests/test_evaluation_metrics.py
"""ルールベース評価指標（backend/evaluation/metrics/rule_based.py）の単体テスト。LLMは使わない。

Phase 2で0-2スケールから0-5スケールに拡張したため、各バンド境界を
`backend/evaluation/schemas/rubric.py`のRUBRICと対応させてテストする。
"""

from backend.evaluation.metrics.rule_based import (
    UNKNOWN_SKILL_SENTINEL,
    score_actionability,
    score_coverage_band,
    score_effort_plausibility,
    score_granularity,
    score_non_duplication,
    score_skill_accuracy,
    score_traceability,
)

SPEC_TEXT = "認証APIのエンドポイントは9月1日までに完成させ、デモ環境をチームリーダーに提出すること。"


# --- traceability ---

def test_traceability_missing_excerpt_but_flagged_scores_partial():
    score, issues = score_traceability(None, True, SPEC_TEXT)
    assert score == 2
    assert issues


def test_traceability_missing_excerpt_and_not_flagged_scores_zero():
    score, issues = score_traceability(None, False, SPEC_TEXT)
    assert score == 0
    assert issues


def test_traceability_hallucinated_reference_scores_zero():
    score, issues = score_traceability("来年の夏までに海外展開を完了させること", False, SPEC_TEXT)
    assert score == 0
    assert issues


def test_traceability_real_excerpt_without_heading_scores_four():
    score, issues = score_traceability("9月1日までに完成させ", False, SPEC_TEXT, heading=None)
    assert score == 4
    assert issues == []


def test_traceability_real_excerpt_with_heading_scores_five():
    score, issues = score_traceability("9月1日までに完成させ", False, SPEC_TEXT, heading="第2条(納期)")
    assert score == 5
    assert issues == []


def test_traceability_long_coarse_excerpt_without_heading_scores_three():
    long_excerpt = SPEC_TEXT * 3  # 120文字を超える粗い引用
    score, issues = score_traceability(long_excerpt, False, long_excerpt, heading=None)
    assert score == 3
    assert issues


# --- actionability ---

def test_actionability_no_verb_scores_zero():
    score, issues = score_actionability("認証API")
    assert score == 0
    assert issues


def test_actionability_short_title_scores_one():
    score, issues = score_actionability("する")
    assert score == 1
    assert issues


def test_actionability_verb_without_description_scores_four():
    score, issues = score_actionability("認証APIのエンドポイントを実装する")
    assert score == 4


def test_actionability_verb_with_description_scores_five():
    score, issues = score_actionability(
        "認証APIのエンドポイントを実装する", description="招待URL方式で参加できるようにする"
    )
    assert score == 5


def test_actionability_suru_ending_without_known_verb_scores_three():
    score, issues = score_actionability("エンドポイントを整備すること")
    assert score == 3


# --- granularity ---

def test_granularity_bundled_tasks_scores_zero():
    score, issues = score_granularity("認証APIを実装するとともにテストを実施する")
    assert score == 0
    assert issues


def test_granularity_very_long_title_scores_one():
    score, issues = score_granularity("あ" * 81)
    assert score == 1


def test_granularity_long_title_scores_two():
    score, issues = score_granularity("あ" * 61)
    assert score == 2


def test_granularity_too_short_title_scores_three():
    score, issues = score_granularity("あああ")
    assert score == 3


def test_granularity_normal_task_scores_four():
    score, issues = score_granularity("認証APIのエンドポイントを実装する")
    assert score == 4


def test_granularity_with_acceptance_criteria_scores_five():
    score, issues = score_granularity(
        "認証APIのエンドポイントを実装する", acceptance_criteria=["招待URLで参加できる"]
    )
    assert score == 5


# --- skill accuracy ---

def test_skill_accuracy_matching_single_category_scores_four():
    score, issues = score_skill_accuracy("認証APIのエンドポイントを実装する", ["Python"])
    assert score == 4


def test_skill_accuracy_matching_multiple_skills_scores_five():
    score, issues = score_skill_accuracy("認証APIのエンドポイントを実装する", ["Python", "FastAPI"])
    assert score == 5


def test_skill_accuracy_unknown_sentinel_scores_partial_not_zero():
    score, issues = score_skill_accuracy("Kanban画面のデザインを作成する", UNKNOWN_SKILL_SENTINEL)
    assert score == 2
    assert issues


def test_skill_accuracy_unclassifiable_title_is_neutral():
    score, issues = score_skill_accuracy("アイデアを検討する", ["Python"])
    assert score == 3


def test_skill_accuracy_confident_but_mismatched_scores_zero():
    score, issues = score_skill_accuracy("Kanban画面のデザインを作成する", ["Python", "pytest"])
    assert score == 0
    assert issues


# --- effort plausibility ---

def test_effort_plausibility_missing_estimate_is_neutral_not_penalized():
    score, issues = score_effort_plausibility(None, "high")
    assert score == 2
    assert issues


def test_effort_plausibility_sane_low_estimate_scores_five():
    score, issues = score_effort_plausibility(8, "high")
    assert score == 5


def test_effort_plausibility_moderate_estimate_scores_four():
    score, issues = score_effort_plausibility(45, "medium")
    assert score == 4


def test_effort_plausibility_implausible_estimate_scores_zero():
    score, issues = score_effort_plausibility(99999, "medium")
    assert score == 0
    assert issues


def test_effort_plausibility_high_priority_with_long_estimate_is_partial():
    score, issues = score_effort_plausibility(100, "high")
    assert score == 3
    assert issues


def test_effort_plausibility_high_priority_with_extreme_estimate_scores_one():
    score, issues = score_effort_plausibility(250, "high")
    assert score == 1
    assert issues


# --- non duplication ---

def test_non_duplication_no_overlap_scores_five():
    tasks = [{"title": "認証APIを実装する"}, {"title": "Kanban画面を実装する"}]
    score, issues = score_non_duplication(tasks)
    assert score == 5
    assert issues == []


def test_non_duplication_one_near_duplicate_pair_scores_three():
    tasks = [
        {"title": "認証APIのエンドポイントを実装する"},
        {"title": "認証APIのバリデーションを実装する"},
        {"title": "Kanban画面を実装する"},
    ]
    score, issues = score_non_duplication(tasks)
    assert score == 3
    assert issues


def test_non_duplication_exact_duplicate_scores_zero():
    tasks = [{"title": "認証APIを実装する"}, {"title": "認証APIを実装する"}]
    score, issues = score_non_duplication(tasks)
    assert score == 0
    assert issues


# --- coverage banding ---

def test_coverage_band_full_coverage_scores_five():
    score, issues = score_coverage_band(5, 5)
    assert score == 5
    assert issues == []


def test_coverage_band_zero_coverage_scores_zero():
    score, issues = score_coverage_band(0, 5)
    assert score == 0
    assert issues


def test_coverage_band_partial_coverage_scores_three():
    score, issues = score_coverage_band(3, 5)
    assert score == 3


def test_coverage_band_empty_ground_truth_is_flagged():
    score, issues = score_coverage_band(0, 0)
    assert issues
