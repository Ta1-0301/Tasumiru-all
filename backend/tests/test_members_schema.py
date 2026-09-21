# backend/tests/test_members_schema.py
"""backend/pipeline/members/schema.py の単体テスト。"""

from backend.pipeline.members.schema import Availability, Member, Skill


def _member(**overrides) -> Member:
    defaults = dict(
        id="M-001",
        name="山田太郎",
        skills=[Skill(skill="Python", level=5, experience_years=3)],
        availability=Availability(available_hours_per_week=40, working_days=["Monday"], current_assigned_hours=10),
        constraints=[],
    )
    defaults.update(overrides)
    return Member(**defaults)


def test_member_accepts_valid_data():
    member = _member()
    assert member.id == "M-001"
    assert member.skills[0].level == 5


def test_availability_remaining_capacity_is_computed():
    availability = Availability(available_hours_per_week=40, current_assigned_hours=10)
    assert availability.remaining_capacity == 30


def test_availability_remaining_capacity_can_go_negative_without_being_clamped():
    """remaining_capacityは生の計算値を返す。0へのクランプ等の黒黙な修復はしない。
    「決して負のキャパシティを許容しない」という要件はvalidator側で保証する。"""
    availability = Availability(available_hours_per_week=10, current_assigned_hours=20)
    assert availability.remaining_capacity == -10


def test_member_defaults_have_no_skills_or_constraints():
    member = Member(
        id="M-002", name="佐藤花子",
        availability=Availability(available_hours_per_week=20),
    )
    assert member.skills == []
    assert member.constraints == []
    assert member.experience_years is None


def test_skill_experience_years_is_optional():
    skill = Skill(skill="React", level=3)
    assert skill.experience_years is None
