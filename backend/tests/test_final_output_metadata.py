# backend/tests/test_final_output_metadata.py
"""backend/pipeline/final_output/metadata.py の単体テスト。"""

from backend.pipeline.dependencies.schema import DependencyDocument
from backend.pipeline.final_output.metadata import compute_prompt_versions, resolve_model_info
from backend.pipeline.requirements.schema import RequirementDocument
from backend.pipeline.tasks.schema import TaskDocument


def test_compute_prompt_versions_is_deterministic():
    assert compute_prompt_versions() == compute_prompt_versions()


def test_compute_prompt_versions_covers_all_llm_phases():
    versions = compute_prompt_versions()
    assert set(versions) == {
        "requirements_extraction", "task_decomposition", "dependency_proposal", "assignment_reasoning",
    }
    for fingerprint in versions.values():
        assert len(fingerprint) == 12
        int(fingerprint, 16)  # 16進数として解釈できる


def test_resolve_model_info_with_consistent_model_across_phases():
    req_doc = RequirementDocument(document_id="doc_1", requirements=[], model="llama3.1:8b", model_version="llama3.1:8b")
    task_doc = TaskDocument(document_id="doc_1", tasks=[], model="llama3.1:8b")
    dep_doc = DependencyDocument(document_id="doc_1", dependencies=[], model="llama3.1:8b")

    model, model_version, models_by_phase = resolve_model_info(req_doc, task_doc, dep_doc)

    assert model == "llama3.1:8b"
    assert model_version == "llama3.1:8b"
    assert models_by_phase == {"requirements": "llama3.1:8b", "tasks": "llama3.1:8b", "dependencies": "llama3.1:8b"}


def test_resolve_model_info_with_inconsistent_models_does_not_fabricate_a_single_answer():
    req_doc = RequirementDocument(document_id="doc_1", requirements=[], model="llama3.1:8b")
    task_doc = TaskDocument(document_id="doc_1", tasks=[], model="claude-sonnet-5")

    model, model_version, models_by_phase = resolve_model_info(req_doc, task_doc, None)

    assert model is None
    assert model_version is None
    assert models_by_phase == {"requirements": "llama3.1:8b", "tasks": "claude-sonnet-5"}


def test_resolve_model_info_with_no_model_recorded_anywhere():
    req_doc = RequirementDocument(document_id="doc_1", requirements=[])
    model, model_version, models_by_phase = resolve_model_info(req_doc, None, None)
    assert model is None
    assert model_version is None
    assert models_by_phase == {}


def test_resolve_model_info_with_no_documents_at_all():
    model, model_version, models_by_phase = resolve_model_info()
    assert (model, model_version, models_by_phase) == (None, None, {})
