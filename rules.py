from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from model import AssignmentStatus, ContentItem, Proposal, StudentStatus
from next_step import REMEDIATION_PREFIX, remediation_modules, topic_need

Evaluate = Callable[
    ["Rule", StudentStatus, list[AssignmentStatus], list[ContentItem], date], list[Proposal]
]


@dataclass(frozen=True)
class Rule:
    id: str
    tier: str
    surface: str
    priority: int
    evaluate: Evaluate


COUNT_WORDS = {
    3: "Three",
    4: "Four",
    5: "Five",
    6: "Six",
    7: "Seven",
    8: "Eight",
    9: "Nine",
    10: "Ten",
}

LOW_QUIZ_PERCENT = 60

QUIZ_QUESTIONS = 5

REMEDIATION_RISK = {"medium", "high"}


def _propose(
    rule: Rule,
    student: StudentStatus,
    subject: str,
    text: str,
    reason: dict[str, Any],
) -> Proposal:
    return Proposal(
        rule=rule.id,
        user_id=student.user_id,
        course_id=student.course_id,
        surface=rule.surface,
        priority=rule.priority,
        subject=subject,
        text=text,
        reason=reason,
    )


def _with_status(assignments: list[AssignmentStatus], status: str) -> list[AssignmentStatus]:
    rows = [a for a in assignments if a.status == status]
    return sorted(rows, key=lambda a: a.due_at or datetime.max)


def _when(due: datetime, as_of: date) -> str:
    days = (due.date() - as_of).days
    if days == 1:
        return "tomorrow"
    if days == 0:
        return "today"
    return due.strftime("%A")


def _long_date(day: date) -> str:
    return f"{day.day} {day.strftime('%B')}"


def _a1_due_in_three_days(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    rows = _with_status(assignments, "due_soon")
    if not rows:
        return []
    first = rows[0]
    if len(rows) == 1:
        text = (
            f"{first.title} is due {_when(first.due_at, as_of)}, "
            f"{first.points_possible:g} points, not started."
        )
    else:
        second = rows[1]
        text = (
            f"{first.title} is due {_when(first.due_at, as_of)}, "
            f"{first.points_possible:g} points. "
            f"{second.title} follows on {_when(second.due_at, as_of)}."
        )
    return [
        _propose(
            rule,
            student,
            subject="+".join(str(a.assignment_id) for a in rows),
            text=text,
            reason={
                "assignment_ids": [a.assignment_id for a in rows],
                "titles": [a.title for a in rows],
            },
        )
    ]


def _a2_missing_work(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    rows = _with_status(assignments, "missing")
    if not rows:
        return []
    titles = [a.title for a in rows]
    count = len(rows)
    if count == 1:
        text = (
            f"{titles[0]} is past due and still counts. "
            "Late work loses 10 percent a day, a missing item scores zero."
        )
    elif count == 2:
        text = (
            f"Two items are past due: {titles[0]} and {titles[1]}. "
            "The oldest is the quickest win."
        )
    else:
        text = (
            f"{COUNT_WORDS.get(count, str(count))} items are past due, starting with {titles[0]}. "
            "Any one of them moves your score off zero."
        )
    return [
        _propose(
            rule,
            student,
            subject="+".join(str(a.assignment_id) for a in rows),
            text=text,
            reason={"assignment_ids": [a.assignment_id for a in rows], "titles": titles},
        )
    ]


def _a3_seven_days_quiet(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    if not 7 <= student.days_inactive <= 13:
        return []
    last_active = as_of - timedelta(days=student.days_inactive)
    missing = student.assignments_missing
    upcoming = _with_status(assignments, "due_soon")
    text = f"Hi {student.first_name}, you haven't opened SAT-101 since {_long_date(last_active)}."
    if missing > 0:
        text += f" {missing} {'item is' if missing == 1 else 'items are'} past due."
    if upcoming:
        text += f" {upcoming[0].title} is due {_when(upcoming[0].due_at, as_of)}."
    return [
        _propose(
            rule,
            student,
            subject="inactive",
            text=text,
            reason={
                "days_inactive": student.days_inactive,
                "assignments_missing": missing,
                "next_due_title": upcoming[0].title if upcoming else None,
            },
        )
    ]


def _a4_fourteen_days_quiet(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    if student.days_inactive < 14:
        return []
    last_active = as_of - timedelta(days=student.days_inactive)
    text = (
        f"Advisor draft for {student.name}: no activity since {_long_date(last_active)}, "
        f"{student.assignments_missing} missing, module requirements "
        f"{student.module_requirement_completed} of {student.module_requirement_count}, "
        f"risk {student.risk_level}. Review before any outreach."
    )
    return [
        _propose(
            rule,
            student,
            subject="inactive",
            text=text,
            reason={
                "days_inactive": student.days_inactive,
                "assignments_missing": student.assignments_missing,
                "module_requirement_completed": student.module_requirement_completed,
                "module_requirement_count": student.module_requirement_count,
                "risk_level": student.risk_level,
            },
        )
    ]


def _a5_quiz_in_progress(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    if student.quizzes_in_progress <= 0:
        return []
    return [
        _propose(
            rule,
            student,
            subject="quiz",
            text=(
                "A quiz you started is still open. Finish it and the attempt is scored; "
                "it unlocks the next module item."
            ),
            reason={"quizzes_in_progress": student.quizzes_in_progress},
        )
    ]


def _b3_targeted_practice(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    avg = student.quiz_avg_percent
    if avg is None or avg >= LOW_QUIZ_PERCENT:
        return []
    return [
        _propose(
            rule,
            student,
            subject="quiz_avg",
            text=(
                f"Your quiz average is {avg:g} percent. A short refresher quiz has been added "
                "for you, about 10 minutes, and it does not count toward your grade."
            ),
            reason={"quiz_avg_percent": avg},
        )
    ]


def _remediation_targets(
    student: StudentStatus, assignments: list[AssignmentStatus], items: list[ContentItem]
) -> list[tuple[int, str, str]]:
    avg = student.quiz_avg_percent
    struggling = student.risk_level in REMEDIATION_RISK or (
        avg is not None and avg < LOW_QUIZ_PERCENT
    )
    if not struggling:
        return []
    needed = topic_need(assignments, items)
    names = {i.module_id: i.module_name for i in items}
    return [
        (module_id, topic, names.get(module_id, f"{REMEDIATION_PREFIX}{topic}"))
        for module_id, topic in remediation_modules(items).items()
        if topic in needed
    ]


def _r1_remediation_module(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    topics_by_assignment = {
        i.content_id: i.topic_list for i in items if i.item_type == "Assignment"
    }
    proposals = []
    for module_id, topic, module_name in _remediation_targets(student, assignments, items):
        basis = next(
            (
                f"missing:{a.title}"
                for a in assignments
                if a.status == "missing"
                and topic in topics_by_assignment.get(a.assignment_id, [])
            ),
            "weakest_topic",
        )
        proposals.append(
            _propose(
                rule,
                student,
                subject=f"module:{module_id}",
                text=f"Assign '{module_name}' to {student.name}",
                reason={
                    "module_id": module_id,
                    "module_name": module_name,
                    "topic": topic,
                    "basis": basis,
                },
            )
        )
    return proposals


def _r2_practice_quiz(
    rule: Rule,
    student: StudentStatus,
    assignments: list[AssignmentStatus],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    return [
        _propose(
            rule,
            student,
            subject=f"quiz:{module_id}:{topic}",
            text=(
                f"Create a {QUIZ_QUESTIONS}-question {topic} practice quiz "
                f"for {student.name} in {module_name}"
            ),
            reason={
                "topic": topic,
                "count": QUIZ_QUESTIONS,
                "module_id": module_id,
                "module_name": module_name,
            },
        )
        for module_id, topic, module_name in _remediation_targets(student, assignments, items)
    ]


RULES: list[Rule] = [
    Rule("A1", "A", "block", 4, _a1_due_in_three_days),
    Rule("A2", "A", "block", 2, _a2_missing_work),
    Rule("A3", "A", "inbox", 1, _a3_seven_days_quiet),
    Rule("A4", "A", "advisor", 1, _a4_fourteen_days_quiet),
    Rule("A5", "A", "block", 3, _a5_quiz_in_progress),
    Rule("B3", "B", "block", 3, _b3_targeted_practice),
    Rule("R1", "R", "module", 2, _r1_remediation_module),
    Rule("R2", "R", "quiz", 3, _r2_practice_quiz),
]


def run_rules(
    students: list[StudentStatus],
    assignments_by_user: dict[int, list[AssignmentStatus]],
    items: list[ContentItem],
    as_of: date,
) -> list[Proposal]:
    proposals = []
    for student in students:
        assignments = assignments_by_user.get(student.user_id, [])
        for rule in RULES:
            proposals.extend(rule.evaluate(rule, student, assignments, items, as_of))
    return proposals
