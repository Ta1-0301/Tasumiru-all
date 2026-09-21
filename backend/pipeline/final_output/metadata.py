# backend/pipeline/final_output/metadata.py
"""
依頼のREPRODUCIBILITY節（model / model version / prompt versions /
pipeline version / timestamp / document ID）を実装する。

`compute_prompt_versions()`は各フェーズの本番プロンプト文面
（`backend/pipeline/*/extractor.py`等）を読み取り専用でインポートし、
そのハッシュ値を計算するだけ——プロンプト自体は一切変更しない
（Phase 2の`backend/evaluation/runners/model_registry.py::compute_prompt_version`
と同じ手法）。プロンプトが1文字でも変われば値も変わるため、
「どのバージョンのプロンプトで生成したか」を後から確認できる。
"""

from __future__ import annotations

import hashlib
from typing import Dict, Optional, Tuple

from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.requirements.schema import RequirementDocument
from backend.pipeline.tasks.schema import TaskDocument

PIPELINE_VERSION = "1.0.0"


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def compute_prompt_versions() -> Dict[str, str]:
    """LLMを使う各フェーズのプロンプト文面から再現性フィンガープリントを計算する"""
    from backend.pipeline.assignment import reasoning as _assignment_reasoning
    from backend.pipeline.dependencies import proposer as _dependency_proposer
    from backend.pipeline.requirements import extractor as _requirements_extractor
    from backend.pipeline.tasks import decomposer as _task_decomposer

    return {
        "requirements_extraction": _fingerprint(_requirements_extractor._EXTRACTION_PROMPT),
        "task_decomposition": _fingerprint(_task_decomposer._DECOMPOSITION_PROMPT),
        "dependency_proposal": _fingerprint(_dependency_proposer._DEPENDENCY_PROMPT),
        "assignment_reasoning": _fingerprint(_assignment_reasoning._REASONING_PROMPT),
    }


def resolve_model_info(
    requirement_document: Optional[RequirementDocument] = None,
    task_document: Optional[TaskDocument] = None,
    dependency_document: Optional[DependencyDocument] = None,
) -> Tuple[Optional[str], Optional[str], Dict[str, str]]:
    """各フェーズのドキュメントに記録された`model`から、全体を代表する
    `model`/`model_version`を解決する。

    全フェーズで同一モデルが使われていた場合のみ単一の値にまとめる。
    フェーズごとに異なるモデルが使われていた場合や、どのフェーズも
    モデル情報を記録していない場合は、無理に1つへ丸めて捏造せず
    `(None, None, models_by_phase)`を返す（`models_by_phase`に詳細を残す）。
    """
    models_by_phase: Dict[str, str] = {}
    if requirement_document and requirement_document.model:
        models_by_phase["requirements"] = requirement_document.model
    if task_document and task_document.model:
        models_by_phase["tasks"] = task_document.model
    if dependency_document and dependency_document.model:
        models_by_phase["dependencies"] = dependency_document.model

    unique_models = set(models_by_phase.values())
    if len(unique_models) != 1:
        return None, None, models_by_phase

    model = next(iter(unique_models))
    model_version = None
    if requirement_document and requirement_document.model == model:
        model_version = requirement_document.model_version

    return model, model_version, models_by_phase
