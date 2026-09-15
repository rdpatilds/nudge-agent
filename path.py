"""Order one student's module items into a learning path.

Five slots fill the path in order, each yielding content items with the reason the student is
being sent there. The first slot that can fill a position wins it, an item already placed is
never placed again, and the path stops at `CAP`.

| Slot | Items | Reason | source_rule |
|---|---|---|---|
| 1 | missing assignments, oldest due first | `missing` | A2 |
| 2 | due_soon assignments, soonest first | `due tomorrow`, `due today`, `due in N days` | A1 |
| 3 | the first Quiz, only while a quiz is in progress | `quiz in progress` | A5 |
| 4 | practice items meeting a topic the student needs | `practice: <topic>` | B3 |
| 5 | everything left, in course order | `next in course order` | None |

Slot 4 puts remediation modules ahead of the rest, because a student only sees one at all once
an educator has assigned it, so it is the most deliberate thing in the catalogue for them.

Slot 5 skips assignments the student has already submitted or graded. The seed carries only
rows a rule fires on, so no assignment row has either status today and the slot skips nothing;
the filter is here for a feed that carries the full roster.

`CAP` is 8 because the path is a to-do list on a dashboard, not a syllabus. A student who has
to scroll it has been given a backlog, not a next step.

Gated modules are dropped before any slot runs, so a student is never pointed at a module
Canvas will not show them.
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime

from model import AssignmentStatus, ContentItem, Gates, PathStep, StudentStatus
from next_step import remediation_modules, topic_need

CAP = 8

DONE_STATUSES = {"submitted", "graded"}

Slot = Callable[
    [StudentStatus, list[AssignmentStatus], list[ContentItem], date],
    Iterator[tuple[ContentItem, str]],
]


def visible_items(items: list[ContentItem], gates: Gates, user_id: int) -> list[ContentItem]:
    return [i for i in items if i.module_id not in gates or user_id in gates[i.module_id]]


def _by_due(assignments: list[AssignmentStatus], status: str) -> list[AssignmentStatus]:
    rows = [a for a in assignments if a.status == status]
    return sorted(rows, key=lambda a: a.due_at or datetime.max)


def _due_phrase(due: datetime, as_of: date) -> str:
    days = (due.date() - as_of).days
    if days == 1:
        return "due tomorrow"
    if days == 0:
        return "due today"
    return f"due in {days} days"


def _assignment_items(items: list[ContentItem]) -> dict[int, ContentItem]:
    return {i.content_id: i for i in items if i.item_type == "Assignment"}


def _missing(
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> Iterator[tuple[ContentItem, str]]:
    by_assignment = _assignment_items(items)
    for assignment in _by_due(assignments, "missing"):
        item = by_assignment.get(assignment.assignment_id)
        if item is not None:
            yield item, "missing"


def _due_soon(
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> Iterator[tuple[ContentItem, str]]:
    by_assignment = _assignment_items(items)
    for assignment in _by_due(assignments, "due_soon"):
        item = by_assignment.get(assignment.assignment_id)
        if item is not None:
            yield item, _due_phrase(assignment.due_at, as_of)


def _open_quiz(
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> Iterator[tuple[ContentItem, str]]:
    if student.quizzes_in_progress <= 0:
        return
    item = next((i for i in items if i.item_type == "Quiz"), None)
    if item is not None:
        yield item, "quiz in progress"


def _practice(
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> Iterator[tuple[ContentItem, str]]:
    needed = topic_need(assignments, items)
    remedial = remediation_modules(items)
    matches = []
    for item in items:
        if not item.is_practice:
            continue
        topic = next((t for t in item.topic_list if t in needed), None)
        if topic is not None:
            rank = (item.module_id not in remedial, item.module_position, item.item_position)
            matches.append((rank, item, topic))
    for _, item, topic in sorted(matches, key=lambda m: m[0]):
        yield item, f"practice: {topic}"


def _course_order(
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> Iterator[tuple[ContentItem, str]]:
    done = {a.assignment_id for a in assignments if a.status in DONE_STATUSES}
    for item in items:
        if item.item_type == "Assignment" and item.content_id in done:
            continue
        yield item, "next in course order"


SLOTS: list[tuple[str | None, Slot]] = [
    ("A2", _missing),
    ("A1", _due_soon),
    ("A5", _open_quiz),
    ("B3", _practice),
    (None, _course_order),
]


def build_path(
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    gates: Gates,
    as_of: date,
    cap: int = CAP,
) -> list[PathStep]:
    if student.module_requirement_completed >= student.module_requirement_count:
        return []
    ordered = sorted(
        visible_items(items, gates, student.user_id),
        key=lambda i: (i.module_position, i.item_position),
    )
    steps: list[PathStep] = []
    placed: set[tuple[str, str]] = set()
    for source_rule, slot in SLOTS:
        for item, reason in slot(student, assignments, ordered, as_of):
            key = (item.item_type, item.title)
            if key in placed:
                continue
            placed.add(key)
            steps.append(
                PathStep(
                    position=len(steps) + 1,
                    module_item_id=item.module_item_id,
                    title=item.title,
                    url=item.url,
                    reason=reason,
                    source_rule=source_rule,
                )
            )
            if len(steps) >= cap:
                return steps
    return steps
