# backend/evaluation/datasets/specs.py
"""
少数の手動ラベル付き評価データセット。

各仕様書に対して、人間（担当者）が「これは拾われているべき」と判断した
正解タスク一覧（ground truth）を付与している。正解タスクの `source_excerpt` は
必ず仕様書の本文からの実在の抜粋（コピペ）であり、`EvaluationSpec`の
`model_validator`で「本文に実在するか」を機械的に検証する
（＝正解データ自体が捏造でないことの構造的な保証）。

このデータセットは意図的に小さい（2件）。目的は大規模な精度測定ではなく、
「今の生成品質にどんな穴があるか」を具体的に可視化すること。
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, model_validator


class GroundTruthTask(BaseModel):
    id: str
    description: str
    source_excerpt: str
    expected_skill_keywords: List[str]
    has_deadline: bool
    is_blocking: bool  # 優先度がhighであるべきと考えられるか


class EvaluationSpec(BaseModel):
    id: str
    title: str
    text: str
    ground_truth_tasks: List[GroundTruthTask]

    @model_validator(mode="after")
    def _validate_excerpts_are_real(self) -> "EvaluationSpec":
        """正解データのsource_excerptが本文に実在しない場合はデータセット自体のバグとして弾く"""
        for task in self.ground_truth_tasks:
            if task.source_excerpt not in self.text:
                raise ValueError(
                    f"ground truth task '{task.id}' の source_excerpt が "
                    f"仕様書本文に見つかりません: {task.source_excerpt!r}"
                )
        return self


SPEC_A = EvaluationSpec(
    id="spec_a_simple",
    title="シンプルな仕様書（短文・2タスク相当）",
    text=(
        "タスみるの認証APIを実装してください。"
        "ユーザー登録機能は不要で、招待URLで参加できるようにすること。"
        "実装が完了したら、READMEに使い方を記載すること。"
    ),
    ground_truth_tasks=[
        GroundTruthTask(
            id="a1",
            description="招待URL方式の認証APIを実装する",
            source_excerpt="招待URLで参加できるようにすること",
            expected_skill_keywords=["API", "バックエンド", "Python", "FastAPI"],
            has_deadline=False,
            is_blocking=True,
        ),
        GroundTruthTask(
            id="a2",
            description="認証APIの使い方をREADMEに記載する",
            source_excerpt="READMEに使い方を記載すること",
            expected_skill_keywords=["ドキュメント", "技術文書"],
            has_deadline=False,
            is_blocking=False,
        ),
    ],
)


SPEC_B = EvaluationSpec(
    id="spec_b_multi_pattern",
    title="実践的な仕様書（明示指示・締切・条件付き・禁止事項の混在）",
    text=(
        "本プロジェクトでは、チーム管理システム「タスみる」のバックエンドAPIを実装する。\n\n"
        "第1条(認証機能): ユーザー登録機能は不要とし、招待URL方式による認証を実装すること。"
        "実装担当者はFastAPIとSQLAlchemyの知識を有すること。\n\n"
        "第2条(納期): 認証APIのエンドポイントは9月1日までに完成させ、"
        "動作確認済みのデモ環境をチームリーダーに提出すること。\n\n"
        "第3条(条件付き要件): チームの管理者が削除される場合は、事前に別の管理者を"
        "指定しておくこと。管理者が1人も存在しない状態を作ってはならない。\n\n"
        "第4条(禁止事項): 生のセッショントークンをデータベースに平文で保存することを禁止する。\n\n"
        "第5条(結合テスト): フロントエンド担当者との結合テストを10月3日までに実施し、"
        "その結果をテスト報告書としてまとめること。"
    ),
    ground_truth_tasks=[
        GroundTruthTask(
            id="b1",
            description="招待URL方式による認証機能を実装する",
            source_excerpt="招待URL方式による認証を実装すること",
            expected_skill_keywords=["FastAPI", "SQLAlchemy", "バックエンド", "API"],
            has_deadline=False,
            is_blocking=True,
        ),
        GroundTruthTask(
            id="b2",
            description="認証APIを9月1日までに完成させ、動作確認済みのデモ環境をチームリーダーに提出する",
            source_excerpt="認証APIのエンドポイントは9月1日までに完成させ、動作確認済みのデモ環境をチームリーダーに提出すること",
            expected_skill_keywords=["API", "デモ", "提出"],
            has_deadline=True,
            is_blocking=True,
        ),
        GroundTruthTask(
            id="b3",
            description="管理者削除時に後任管理者の指定を必須とするルール・バリデーションを実装する",
            source_excerpt="チームの管理者が削除される場合は、事前に別の管理者を指定しておくこと",
            expected_skill_keywords=["バックエンド", "バリデーション"],
            has_deadline=False,
            is_blocking=False,
        ),
        GroundTruthTask(
            id="b4",
            description="セッショントークンがデータベースに平文で保存されていないことを検証する",
            source_excerpt="生のセッショントークンをデータベースに平文で保存することを禁止する",
            expected_skill_keywords=["セキュリティ", "レビュー"],
            has_deadline=False,
            is_blocking=True,
        ),
        GroundTruthTask(
            id="b5",
            description="フロントエンド担当者と10月3日までに結合テストを実施し、テスト報告書を作成する",
            source_excerpt="フロントエンド担当者との結合テストを10月3日までに実施し、その結果をテスト報告書としてまとめること",
            expected_skill_keywords=["テスト", "QA", "フロントエンド"],
            has_deadline=True,
            is_blocking=True,
        ),
    ],
)


EVALUATION_DATASET: List[EvaluationSpec] = [SPEC_A, SPEC_B]
