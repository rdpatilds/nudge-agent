import pytest

from model import Gates, PathStep
from path import build_path
from rules import run_rules

TODAY: Gates = {4: set()}
ASSIGNED_TO_ELENA: Gates = {4: {6}}

ELENA_TITLES = [
    "Reading Diagnostic",
    "Grammar Rules Drill 1",
    "Linear Equations Set",
    "Word Problems Set",
    "Practice Test 1 Reflection",
    "Reading Practice Set",
    "Grammar Practice Set",
    "Algebra Refresher",
]

ELENA_REASONS = [
    "missing",
    "missing",
    "missing",
    "due tomorrow",
    "due in 2 days",
    "practice: Reading",
    "practice: Writing and Language",
    "practice: Heart of Algebra",
]


@pytest.fixture
def path_for(students, assignments_by_user, items, as_of):
    def build(user_id: int, gates: Gates) -> list[PathStep]:
        student = next(s for s in students if s.user_id == user_id)
        return build_path(student, assignments_by_user.get(user_id, []), items, gates, as_of)

    return build


def test_elena_without_the_remediation_module(path_for):
    steps = path_for(6, TODAY)
    assert [s.title for s in steps] == ELENA_TITLES
    assert [s.reason for s in steps] == ELENA_REASONS


def test_elena_last_practice_step_is_the_ungated_algebra_page(path_for):
    assert path_for(6, TODAY)[7].module_item_id == 11


def test_remediation_items_lead_the_practice_slot_once_assigned(path_for):
    steps = path_for(6, ASSIGNED_TO_ELENA)
    assert [(s.position, s.title, s.module_item_id) for s in steps[5:8]] == [
        (6, "Algebra Refresher", 13),
        (7, "Linear Equations Practice", 14),
        (8, "Reading Practice Set", 9),
    ]


def test_a_finished_student_gets_no_path(path_for):
    assert path_for(2, TODAY) == []


def test_gabriel_leads_with_the_only_thing_due(path_for):
    steps = path_for(8, TODAY)
    assert (steps[0].title, steps[0].reason) == ("Word Problems Set", "due tomorrow")
    assert len(steps) == 8
    assert [s for s in steps if s.reason.startswith("practice")] == []


def test_r1_fires_for_the_students_a_remedial_topic_reaches(
    students, assignments_by_user, items, as_of
):
    proposals = run_rules(students, assignments_by_user, items, as_of)
    assert {p.user_id for p in proposals if p.rule == "R1"} == {5, 6, 10}


def test_r1_names_the_module_and_the_missing_item_behind_it(
    students, assignments_by_user, items, as_of
):
    proposals = run_rules(students, assignments_by_user, items, as_of)
    elena = next(p for p in proposals if p.rule == "R1" and p.user_id == 6)
    assert elena.text == "Assign 'Remediation: Heart of Algebra' to Elena Rossi"
    assert elena.surface == "module"
    assert elena.subject == "module:4"
    assert elena.reason == {
        "module_id": 4,
        "module_name": "Remediation: Heart of Algebra",
        "topic": "Heart of Algebra",
        "basis": "missing:Linear Equations Set",
    }
