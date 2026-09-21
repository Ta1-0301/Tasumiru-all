# backend/services/skill_matching.py
"""
Part 5/7: TF-IDF Skill Vectorization + Cosine Similarity。

タスクの必要スキル一覧と、メンバーのスキル一覧を「スキル名の集合」として
比較し、`sklearn.feature_extraction.text.TfidfVectorizer` +
`sklearn.metrics.pairwise.cosine_similarity`で決定的な類似度を計算する。

これはPhase 7(`backend.pipeline.assignment.scoring`)の既存の
`score_skill_match`（スキルの"レベル"を見る、厳密な完全一致ベースの判定）を
置き換えるものではない。既存の判定は「要求レベルを満たしているか」という
ハード制約に近い意味を持ち、そのまま維持する。ここで追加するのは、
スキル名の表記ゆれ・部分一致（例: タスクが["Python","FastAPI","REST API"]を
要求し、メンバーが["Python","FastAPI","SQL"]を持つ場合の全体的な近さ）を
捉える、補完的なシグナルである。

sklearn固有のオブジェクト（Vectorizer/疎行列等）は一切この層の外に出さない
——呼び出し側が受け取るのは`float`（0.0-1.0）とプレーンなpydanticモデルのみ。
"""

from __future__ import annotations

from typing import List, Sequence

from pydantic import BaseModel
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.pipeline.members.schema import Member
from backend.services.skill_normalization import normalize_skill_name


class MemberSkillSimilarity(BaseModel):
    """1人のメンバーについての、タスクとのスキル類似度"""

    member_id: str
    skill_similarity: float


def _to_document(skill_names: Sequence[str]) -> str:
    """スキル名一覧を、TF-IDFに入力する1つの「文書」（正規化済みスキル名の
    空白区切り文字列）に変換する。
    """
    return " ".join(normalize_skill_name(s) for s in skill_names if s and s.strip())


def _cosine_from_documents(documents: List[str]) -> List[List[float]]:
    """複数の文書間のペアワイズcosine類似度行列を返す。

    `TfidfVectorizer`は入力文書集合だけからIDFを学習する（外部コーパス無し）
    ため、同じ入力に対して常に同じ結果になる（決定的・再現可能）。
    """
    vectorizer = TfidfVectorizer()
    matrix = vectorizer.fit_transform(documents)
    return cosine_similarity(matrix).tolist()


def skill_similarity(task_skills: Sequence[str], member_skills: Sequence[str]) -> float:
    """1件のタスクの必要スキル一覧と、1人のメンバーのスキル一覧のTF-IDF
    cosine類似度を計算する（0.0-1.0）。

    - タスクが必要スキルを指定していない場合: 制約が無いので1.0
      （`scoring.score_skill_match`が要求スキル無しの場合に1.0を返すのと
      同じ扱いに揃える。無い情報を"類似していない"と決めつけない）。
    - タスクは必要スキルを指定しているが、メンバーがスキルを1つも
      持っていない場合: 比較対象が無いので0.0（似ているとは言えない）。
    """
    task_doc = _to_document(task_skills)
    if not task_doc:
        return 1.0

    member_doc = _to_document(member_skills)
    if not member_doc:
        return 0.0

    similarities = _cosine_from_documents([task_doc, member_doc])
    return round(float(similarities[0][1]), 4)


def match_task_to_members(
    required_skills: Sequence[str], members: List[Member]
) -> List[MemberSkillSimilarity]:
    """1件のタスクの必要スキルを、複数メンバーのスキルと一括比較する。

    全メンバーとタスクを同じ文書集合（同じIDF）でベクトル化してから比較する
    ため、メンバー間のスコアが互いに比較可能になる
    （`skill_similarity()`をメンバーごとに個別に呼ぶ場合、ペアごとに
    異なるIDFで計算されるため、メンバー間の相対比較には本関数を使う）。

    結果は`skill_similarity`の降順（同点はmember_id昇順）で返す。
    """
    task_doc = _to_document(required_skills)

    if not task_doc:
        return sorted(
            (MemberSkillSimilarity(member_id=m.id, skill_similarity=1.0) for m in members),
            key=lambda r: r.member_id,
        )

    documents = [task_doc] + [_to_document([s.skill for s in m.skills]) for m in members]
    similarities = _cosine_from_documents(documents)
    task_row = similarities[0]

    results = [
        MemberSkillSimilarity(member_id=m.id, skill_similarity=round(float(task_row[i + 1]), 4))
        for i, m in enumerate(members)
    ]
    return sorted(results, key=lambda r: (-r.skill_similarity, r.member_id))
