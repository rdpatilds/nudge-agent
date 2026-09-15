import csv
from datetime import date
from pathlib import Path

import pytest

from model import AssignmentStatus, StudentStatus, from_row
from rules import RULES, run_rules

SEED = Path(__file__).resolve().parents[2] / "redshift" / "seed"
AS_OF = date(2026, 9, 15)

EXPECTED_FIRINGS = {
    "A1": {4, 5, 6, 8, 10, 11},
    "A2": {3, 5, 6, 10},
    "A3": {5},
    "A4": {6},
    "A5": {4, 10},
    "B3": {7},
}


def _load[T](name: str, cls: type[T]) -> list[T]:
    with (SEED / name).open(newline="", encoding="utf-8") as handle:
        return [from_row(cls, row) for row in csv.DictReader(handle)]


@pytest.fixture(scope="module")
def proposals():
    students = _load("student_course_status.csv", StudentStatus)
    assignments_by_user: dict[int, list[AssignmentStatus]] = {}
    for row in _load("assignment_status.csv", AssignmentStatus):
        assignments_by_user.setdefault(row.user_id, []).append(row)
    return run_rules(students, assignments_by_user, AS_OF)


def _text(proposals, rule: str, user_id: int) -> str:
    return next(p.text for p in proposals if p.rule == rule and p.user_id == user_id)


def test_firings_match_the_golden_run(proposals):
    fired: dict[str, set[int]] = {rule.id: set() for rule in RULES}
    for proposal in proposals:
        fired[proposal.rule].add(proposal.user_id)
    assert fired == EXPECTED_FIRINGS


def test_a1_names_the_first_two_items(proposals):
    assert _text(proposals, "A1", 4) == (
        "Word Problems Set is due tomorrow, 20 points. "
        "Practice Test 1 Reflection follows on Thursday."
    )


def test_a1_single_item(proposals):
    assert _text(proposals, "A1", 8) == (
        "Word Problems Set is due tomorrow, 20 points, not started."
    )
