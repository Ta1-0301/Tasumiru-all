# backend/tests/test_skill_normalization.py
"""backend/services/skill_normalization.py の単体テスト（Part 6、決定的）。"""

from backend.services.skill_normalization import normalize_skill_name


def test_case_and_whitespace_are_normalized():
    assert normalize_skill_name("Python") == normalize_skill_name("python")
    assert normalize_skill_name("  Python  ") == normalize_skill_name("Python")


def test_version_suffix_is_stripped():
    assert normalize_skill_name("Python3") == normalize_skill_name("Python")


def test_fast_api_normalizes_like_fastapi():
    assert normalize_skill_name("Fast API") == normalize_skill_name("FastAPI")


def test_restful_api_normalizes_like_rest_api():
    assert normalize_skill_name("RESTful API") == normalize_skill_name("REST API")


def test_distinct_skills_stay_distinct():
    assert normalize_skill_name("Python") != normalize_skill_name("Go")
    assert normalize_skill_name("Java") != normalize_skill_name("JavaScript")


def test_empty_string_returns_empty():
    assert normalize_skill_name("") == ""


def test_extra_rules_are_applied_and_do_not_affect_defaults():
    assert normalize_skill_name("MyFramework", extra_rules={"myframework": "my-framework"}) == "my-framework"
    assert normalize_skill_name("Fast API", extra_rules={"myframework": "my-framework"}) == "fastapi"


def test_result_is_deterministic():
    results = {normalize_skill_name("Node.js") for _ in range(5)}
    assert len(results) == 1
