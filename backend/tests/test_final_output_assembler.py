# backend/tests/test_final_output_assembler.py
"""backend/pipeline/final_output/assembler.py の結合テスト（完全な最終出力）。"""

import json

import pytest

from backend.pipeline.assignment.schema import AssignmentResult, FinalAssignment
from backend.pipeline.dependencies.schema import Dependency, DependencyDocument
from backend.pipeline.final_output.assembler import (
    CriticalValidationError,
    assemble_final_output,
    ensure_safe_to_publish,
)
from backend.pipeline.final_output.json_schema import validate_output_json
from backend.pipeline.members.schema import Availability, Member, MemberDirectory, Skill
from backend.pipeline.requirements.schema import Requirement, RequirementDocument, SourceReference
from backend.pipeline.tasks.schema import Task, TaskDocument
from backend.pipeline.validation.schema import MissingRequirement, ValidationReport


def _requirement_document() -> RequirementDocument:
    return RequirementDocument(
        document_id="spec_a",
        requirements=[
            Requirement(
                id="REQ-001", type="functional", title="認証機能",
                description="招待URLで参加できる認証機能を実装する",
                source_reference=SourceReference(document_id="spec_a", source_text="招待URLで参加できる"),
                confidence=0.9,
            ),
        ],
        model="llama3.1:8b", model_version="llama3.1:8b",
    )


def _task_document() -> TaskDocument:
    return TaskDocument(
        document_id="spec_a",
        tasks=[
            Task(
                id="TASK-001", requirement_ids=["REQ-001"], title="認証APIを実装する",
                description="招待URL方式の認証APIを実装する", required_skills=["Python"],
                estimated_hours=8, acceptance_criteria=["ログインできること"], confidence=0.9,
            ),
        ],
        model="llama3.1:8b",
    )


def _dependency_document() -> DependencyDocument:
    return DependencyDocument(document_id="spec_a", dependencies=[], model="llama3.1:8b")


def _member_directory() -> MemberDirectory:
    return MemberDirectory(
        team_id="team_1",
        members=[Member(
            id="M-001", name="山田太郎", skills=[Skill(skill="Python", level=5)],
            availability=Availability(available_hours_per_week=40, current_assigned_hours=8),
        )],
    )


def _assignments():
    return [FinalAssignment(
        task_id="TASK-001", assigned_member_id="M-001", decided_by="ai",
        ai_recommendation=AssignmentResult(task_id="TASK-001", recommended_member_id="M-001", score=91.0, status="recommended"),
    )]


def _clean_validation_report() -> ValidationReport:
    return ValidationReport(valid=True)


# --- no new information is generated ---

def test_assembled_output_contains_exactly_the_input_data_unchanged():
    req_doc = _requirement_document()
    task_doc = _task_document()
    dep_doc = _dependency_document()
    member_dir = _member_directory()
    assignments = _assignments()
    report = _clean_validation_report()

    output = assemble_final_output(req_doc, task_doc, dep_doc, member_dir, assignments, report)

    assert output.requirements == req_doc.requirements
    assert output.tasks == task_doc.tasks
    assert output.dependencies == dep_doc.dependencies
    assert output.members == member_dir.members
    assert output.assignments == assignments
    assert output.validation.report is report


def test_project_name_defaults_to_none_when_not_supplied():
    """名前が渡されなければ、存在しない情報を作り出さずNoneのままにする"""
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), _clean_validation_report(),
    )
    assert output.project.name is None
    assert output.project.document_id == "spec_a"


def test_project_name_is_used_verbatim_when_supplied():
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), _clean_validation_report(),
        project_name="タスみる導入プロジェクト",
    )
    assert output.project.name == "タスみる導入プロジェクト"


# --- metadata / reproducibility ---

def test_metadata_records_pipeline_version_and_timestamp():
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), _clean_validation_report(),
    )
    assert output.metadata.pipeline_version
    assert output.metadata.generated_at
    assert output.metadata.document_id == "spec_a"


def test_metadata_resolves_consistent_model_across_phases():
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), _clean_validation_report(),
    )
    assert output.metadata.model == "llama3.1:8b"
    assert output.metadata.model_version == "llama3.1:8b"


def test_metadata_prompt_versions_cover_all_llm_phases():
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), _clean_validation_report(),
    )
    assert set(output.metadata.prompt_versions) == {
        "requirements_extraction", "task_decomposition", "dependency_proposal", "assignment_reasoning",
    }


# --- valid / warning / error status is honestly reflected ---

def test_clean_plan_has_valid_status():
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), _clean_validation_report(),
    )
    assert output.validation.status == "valid"
    ensure_safe_to_publish(output)  # 例外が出ないこと


def test_critical_validation_error_is_reflected_and_still_assembled():
    """重大なエラーがあっても、組み立て自体は拒否しない（隠さず報告する）"""
    broken_report = ValidationReport(
        valid=False,
        missing_requirements=[MissingRequirement(requirement_id="REQ-999", message="対応するタスクが無い")],
    )
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), broken_report,
    )

    assert output.validation.status == "error"
    assert output.validation.report is broken_report  # 元のエラーが握り潰されていない


def test_ensure_safe_to_publish_raises_on_critical_errors():
    broken_report = ValidationReport(
        valid=False,
        missing_requirements=[MissingRequirement(requirement_id="REQ-999", message="対応するタスクが無い")],
    )
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), broken_report,
    )
    with pytest.raises(CriticalValidationError):
        ensure_safe_to_publish(output)


def test_untraceable_task_forces_error_status_even_with_clean_phase8_report():
    task_doc = TaskDocument(
        document_id="spec_a",
        tasks=[Task(id="TASK-001", requirement_ids=[], title="孤立タスク", description="d", confidence=0.9)],
    )
    output = assemble_final_output(
        _requirement_document(), task_doc, _dependency_document(),
        _member_directory(), [], _clean_validation_report(),
    )
    assert output.validation.status == "error"
    assert len(output.validation.traceability_errors) == 1


# --- the assembled output round-trips through the JSON schema ---

def test_assembled_output_conforms_to_its_own_json_schema():
    output = assemble_final_output(
        _requirement_document(), _task_document(), _dependency_document(),
        _member_directory(), _assignments(), _clean_validation_report(),
    )
    dumped = json.loads(json.dumps(output.model_dump(mode="json"), ensure_ascii=False))
    assert validate_output_json(dumped) == []
