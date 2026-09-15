"""Pick the one link a nudge points at.

| Rule | Next step |
|---|---|
| A1 | the Assignment item whose content_id is the first id in reason["assignment_ids"]; rules.py sorted those by due date, so it is the soonest |
| A2 | the same lookup on the first id; rules.py sorted missing rows by due date, so it is the oldest |
| A3 | the earliest incomplete item by (module_position, item_position), else the course home page |
| A4 | no link, an advisor draft is never pushed |
| A5 | the first Quiz item by (module_position, item_position). The seed carries a count of in-progress quizzes and no quiz id, so this is an approximation |
| B3 | the first practice item whose topics meet the student's weakest topic, else the first practice item |

A rule whose lookup finds nothing leaves both fields None.
"""

from collections.abc import Callable
from dataclasses import replace

from model import AssignmentStatus, ContentItem, Proposal, StudentStatus

CANVAS_URL = "http://localhost:3100"

INCOMPLETE_STATUSES = {"missing", "due_soon", "unsubmitted"}

Resolve = Callable[
    [Proposal, StudentStatus, list[AssignmentStatus], list[ContentItem], int], Proposal
]


def _link(proposal: Proposal, item: ContentItem) -> Proposal:
    return replace(proposal, next_url=item.url, next_title=item.title)


def _with_basis(proposal: Proposal, basis: str) -> Proposal:
    return replace(proposal, reason={**proposal.reason, "next_step_basis": basis})


def _assignment_item(items: list[ContentItem], assignment_id: int) -> ContentItem | None:
    return next(
        (i for i in items if i.item_type == "Assignment" and i.content_id == assignment_id), None
    )


def _weakest_topics(
    assignments: list[AssignmentStatus], items: list[ContentItem]
) -> list[str] | None:
    scored = [a for a in assignments if a.score is not None and (a.points_possible or 0) > 0]
    if not scored:
        return None
    weakest = min(scored, key=lambda a: a.score / a.points_possible)
    item = _assignment_item(items, weakest.assignment_id)
    return item.topic_list if item is not None else []


def _first_named_assignment(
    proposal: Proposal,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    course_id: int,
) -> Proposal:
    assignment_ids = proposal.reason.get("assignment_ids") or []
    if not assignment_ids:
        return proposal
    item = _assignment_item(items, assignment_ids[0])
    return _link(proposal, item) if item is not None else proposal


def _earliest_incomplete(
    proposal: Proposal,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    course_id: int,
) -> Proposal:
    pending = {a.assignment_id for a in assignments if a.status in INCOMPLETE_STATUSES}
    item = next(
        (i for i in items if i.item_type == "Assignment" and i.content_id in pending), None
    )
    if item is not None:
        return _link(proposal, item)
    return replace(
        proposal, next_url=f"{CANVAS_URL}/courses/{course_id}", next_title="Course home"
    )


def _first_quiz(
    proposal: Proposal,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    course_id: int,
) -> Proposal:
    item = next((i for i in items if i.item_type == "Quiz"), None)
    return _link(proposal, item) if item is not None else proposal


def _weakest_practice(
    proposal: Proposal,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    course_id: int,
) -> Proposal:
    practice = [i for i in items if i.is_practice]
    if not practice:
        return proposal
    weakest = _weakest_topics(assignments, items)
    if weakest is None:
        return _with_basis(_link(proposal, practice[0]), "first_practice")
    for item in practice:
        topics = item.topic_list
        match = next((t for t in weakest if t in topics), None)
        if match is not None:
            return _with_basis(_link(proposal, item), f"weakest_topic:{match}")
    return proposal


RESOLVERS: dict[str, Resolve] = {
    "A1": _first_named_assignment,
    "A2": _first_named_assignment,
    "A3": _earliest_incomplete,
    "A5": _first_quiz,
    "B3": _weakest_practice,
}


def resolve(
    proposal: Proposal,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    course_id: int,
) -> Proposal:
    resolver = RESOLVERS.get(proposal.rule)
    if resolver is None:
        return proposal
    ordered = sorted(items, key=lambda i: (i.module_position, i.item_position))
    return resolver(proposal, student, assignments, ordered, course_id)
