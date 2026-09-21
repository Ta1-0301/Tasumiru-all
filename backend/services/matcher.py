# backend/services/matcher.py
"""
TASK-004: スキルマッチングモジュール (Embeddingベース / Voyage AI 版)

【変更点】
  旧: TfidfVectorizer による単語の表層一致でベクトル化
  新: Voyage AI (Anthropic公式推奨の埋め込みプロバイダ) による意味的な埋め込みでベクトル化
      → Claude自体はembedding APIを提供していないため、Anthropicのドキュメントでも
        embedding用途にはVoyage AIの利用が案内されている。
      → 「バックエンドエンジニア」と「サーバーサイド開発者」のように、単語が一致しない
        同義語・言い換えでも高い類似度を出せるようになる（TF-IDFでは0点になっていた）。

アルゴリズム:
  1. タスクの `skill_required` とメンバーのスキルリストをそれぞれ文字列化
  2. 【誰でも可判定】タスクが「誰でもできる仕事」かどうかの事前判定
  3. Voyage AI Embeddings + cosine_similarity で意味的な類似度を計算
  4. タスク自体の負荷（priority等から算出）を決定
  5. 【適任者なし判定】最大類似度が閾値未満の場合は「適任者なし」とする
  6. リアルタイムに変動する稼働負荷 (load_pct) でスコアを補正し、最適なメンバーを割り当て

必要な環境変数:
  VOYAGE_API_KEY   : Voyage AI の APIキー (必須)
  VOYAGE_MODEL      : 使用する埋め込みモデル (省略時 "voyage-3.5")
  MATCH_MIN_SCORE   : 「適任者なし」と判定する類似度の下限 (省略時 0.3)
                      ※ Embeddingは意味が近いだけで完全に無関係でも0にはならないため、
                        TF-IDF時代の閾値 0.0 は使えない。実測して調整すること。
"""

import os
from typing import Any, Dict, List

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# ローカル埋め込みモデル（多言語対応・日本語OK・軽量）
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-small")
MATCH_MIN_SCORE = float(os.getenv("MATCH_MIN_SCORE", "0.5"))

_embedding_model: SentenceTransformer | None = None


def _get_embedding_model() -> SentenceTransformer:
    """埋め込みモデルをシングルトンでロードする（初回のみDL・以降はキャッシュから読込）"""
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


def _ensure_string(data: Any) -> str:
    """入力データがリスト型であればスペース区切りの文字列に変換し、文字列ならそのまま返す"""
    if not data:
        return ""
    if isinstance(data, list):
        return " ".join([str(item) for item in data if item])
    return str(data).strip()


def _is_anyone_task(skill_text: str) -> bool:
    """タスクが「誰でもできる仕事」かどうかを判定するヘルパー"""
    if not skill_text:
        return True
    ignore_keywords = ["なし", "誰でも", "だれでも", "不問", "none", "anyone", "全般"]
    return any(kw in skill_text.lower() for kw in ignore_keywords)


def _get_task_load(task: Dict[str, Any]) -> int:
    """タスクの属性から負荷項目（%）を動的に計算する"""
    if "task_load" in task and task["task_load"] is not None:
        return int(task["task_load"])

    priority = str(task.get("priority", "medium")).lower()
    if priority == "high":
        return 30
    elif priority == "low":
        return 10
    else:
        return 20


def _embed_texts(texts: List[str], input_type: str) -> np.ndarray:
    """テキストのリストをローカルモデル(e5系)で埋め込みベクトル化する

    Args:
        texts: 埋め込み対象のテキストリスト
        input_type: "query"（タスク側）または "document"（メンバー側）
                    e5系モデルは非対称検索用に "query: " / "passage: " という
                    接頭辞を付けることで検索精度が上がる設計になっている。
    """
    model = _get_embedding_model()
    prefix = "query: " if input_type == "query" else "passage: "

    safe_texts = [t if t.strip() else "スキル不問・誰でも対応可能なタスク" for t in texts]
    prefixed_texts = [prefix + t for t in safe_texts]

    embeddings = model.encode(prefixed_texts, normalize_embeddings=True)
    return np.array(embeddings)


def compute_assignments(
    tasks: List[Dict[str, Any]], members: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """各タスクに最適な担当者を割り当てる。タスク固有の負荷をメンバーに累積させる。"""
    if not tasks:
        return []
    if not members:
        for t in tasks:
            t["assignee"] = "未割り当て"
            t["load_pct"] = 0
        return tasks

    # メンバーの初期負荷を追跡・蓄積するための作業用コピーを作成
    local_members = [m.copy() for m in members]
    for m in local_members:
        if "load_pct" not in m or m["load_pct"] is None:
            m["load_pct"] = 0

    # 1. テキスト表現の作成
    member_texts = [_ensure_string(m.get("skills") or m.get("skill")) for m in local_members]
    task_texts = [_ensure_string(t.get("skill_required")) for t in tasks]

    all_texts = member_texts + task_texts
    has_vocabulary = any(text.strip() for text in all_texts)

    # 2. Embedding化 + コサイン類似度計算
    if has_vocabulary:
        # メンバー側は "document"、タスク側は "query" として非対称に埋め込む
        # (Voyageは同じ埋め込み空間内で query/document を区別して最適化する)
        member_vectors = _embed_texts(member_texts, input_type="document")
        task_vectors = _embed_texts(task_texts, input_type="query")
        similarity_matrix = cosine_similarity(task_vectors, member_vectors)
    else:
        similarity_matrix = np.zeros((len(tasks), len(local_members)))

    # 3. スコアの補正と担当者の決定
    processed_tasks = []
    for i, task in enumerate(tasks):
        updated_task = task.copy()
        skill_req = task_texts[i]

        task_load = _get_task_load(task)
        updated_task["task_load"] = task_load

        # --- 誰でもできる仕事（スキル不問）の場合 ---
        if _is_anyone_task(skill_req):
            least_loaded_member = min(local_members, key=lambda m: m["load_pct"])
            updated_task["assignee"] = least_loaded_member["name"]

            new_load = min(100, least_loaded_member["load_pct"] + task_load)
            least_loaded_member["load_pct"] = new_load
            updated_task["load_pct"] = new_load

            updated_task["source_section"] = "§ 自動生成 (誰でも可 -> 負荷平準化アサイン)"
            processed_tasks.append(updated_task)
            continue

        # --- 通常のスキルマッチング（意味的類似度ベース） ---
        best_score = -1.0
        best_member_idx = -1
        max_cos_score = 0.0

        for j, member in enumerate(local_members):
            cos_score = float(similarity_matrix[i][j])
            if cos_score > max_cos_score:
                max_cos_score = cos_score

            load = member["load_pct"]
            corrected_score = cos_score * (1.0 - (load / 100.0))

            if corrected_score > best_score:
                best_score = corrected_score
                best_member_idx = j

        # --- 必要な専門スキルを持っている担当者がいない場合 ---
        # NOTE: Embeddingは意味が近いだけで完全に無関係な文でも0にならないため、
        #       TF-IDF時代の閾値 <= 0.0 ではなく MATCH_MIN_SCORE で判定する
        if max_cos_score < MATCH_MIN_SCORE:
            updated_task["assignee"] = "適任者なし (要要員検討)"
            updated_task["load_pct"] = 0
            updated_task["priority"] = "high"
            updated_task["match_score"] = round(max_cos_score, 3)
            processed_tasks.append(updated_task)
            continue

        # 適合者がいた場合はアサイン
        assigned_member = local_members[best_member_idx]
        updated_task["assignee"] = assigned_member["name"]
        updated_task["match_score"] = round(max_cos_score, 3)

        new_load = min(100, assigned_member["load_pct"] + task_load)
        assigned_member["load_pct"] = new_load
        updated_task["load_pct"] = new_load

        processed_tasks.append(updated_task)

    return processed_tasks
