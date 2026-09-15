import csv
from datetime import date
from pathlib import Path

import pytest

from model import AssignmentStatus, ContentItem, StudentStatus, from_row

SEED = Path(__file__).resolve().parents[2] / "redshift" / "seed"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load[T](base: Path, name: str, cls: type[T]) -> list[T]:
    with (base / name).open(newline="", encoding="utf-8") as handle:
        return [from_row(cls, row) for row in csv.DictReader(handle)]


@pytest.fixture(scope="session")
def as_of() -> date:
    return date(2026, 9, 15)


@pytest.fixture(scope="session")
def students() -> list[StudentStatus]:
    return load(SEED, "student_course_status.csv", StudentStatus)


@pytest.fixture(scope="session")
def assignments_by_user() -> dict[int, list[AssignmentStatus]]:
    by_user: dict[int, list[AssignmentStatus]] = {}
    for row in load(SEED, "assignment_status.csv", AssignmentStatus):
        by_user.setdefault(row.user_id, []).append(row)
    return by_user


@pytest.fixture(scope="session")
def items() -> list[ContentItem]:
    return load(FIXTURES, "content_items.csv", ContentItem)
