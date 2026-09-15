import json
from dataclasses import dataclass, field, fields
from datetime import date, datetime
from enum import StrEnum
from types import NoneType, UnionType
from typing import Any, get_args, get_origin


class Status(StrEnum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    pushed = "pushed"
    push_failed = "push_failed"


TRANSITIONS: dict[Status, set[Status]] = {
    Status.proposed: {Status.approved, Status.rejected},
    Status.approved: {Status.pushed, Status.push_failed},
    Status.push_failed: {Status.pushed, Status.push_failed},
}


def predecessors(new_status: Status) -> list[Status]:
    return [s for s, allowed in TRANSITIONS.items() if new_status in allowed]


@dataclass(frozen=True)
class StudentStatus:
    course_id: int
    user_id: int
    name: str
    days_inactive: int
    assignments_submitted: int
    assignments_late: int
    assignments_missing: int
    assignments_excused: int
    assignments_due_3d_unsubmitted: int
    quizzes_complete: int
    quizzes_in_progress: int
    quizzes_untaken: int
    quiz_avg_percent: float | None
    module_requirement_completed: int
    module_requirement_count: int
    current_score: float | None
    logins_7d: int
    risk_score: float
    risk_level: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0]


@dataclass(frozen=True)
class AssignmentStatus:
    course_id: int
    user_id: int
    assignment_id: int
    title: str
    due_at: datetime | None
    status: str
    submitted_at: datetime | None
    score: float | None
    points_possible: float | None


@dataclass(frozen=True)
class ContentItem:
    course_id: int
    module_id: int
    module_position: int
    module_name: str
    module_item_id: int
    item_position: int
    item_type: str
    content_id: int | None
    title: str
    url: str
    topics: str | None
    difficulty: str
    is_practice: bool
    computed_at: datetime | None

    @property
    def topic_list(self) -> list[str]:
        return [t.strip() for t in (self.topics or "").split(",") if t.strip()]


@dataclass(frozen=True)
class PoolQuestion:
    question_id: int
    topic: str
    difficulty: str
    question_type: str
    question_text: str
    answers: list[dict]
    points: float


@dataclass(frozen=True)
class PathStep:
    position: int
    module_item_id: int | None
    title: str
    url: str
    reason: str
    source_rule: str | None


Gates = dict[int, set[int]]


@dataclass(frozen=True)
class Proposal:
    rule: str
    user_id: int
    course_id: int
    surface: str
    priority: int
    subject: str
    text: str
    reason: dict[str, Any] = field(default_factory=dict)
    next_url: str | None = None
    next_title: str | None = None

    def dedupe_key(self, as_of: date) -> str:
        return f"{self.rule}|{self.course_id}|{self.user_id}|{self.subject}|{as_of.isoformat()}"


@dataclass(frozen=True)
class Recommendation:
    id: int
    rule: str
    course_id: int
    user_id: int
    surface: str
    priority: int
    text: str
    context: str | None
    reason: str | None
    next_url: str | None
    next_title: str | None
    dedupe_key: str
    status: str
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime | None
    pushed_at: datetime | None
    push_error: str | None


def _coerce(kind: Any, value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(kind, UnionType):
        kind = next(arg for arg in get_args(kind) if arg is not NoneType)
    if kind is datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if kind is bool:
        return value if isinstance(value, bool) else str(value).strip().lower() == "true"
    if get_origin(kind) is list:
        return json.loads(value) if isinstance(value, str) else list(value)
    return kind(value)


def from_row[T](cls: type[T], row: dict[str, Any]) -> T:
    return cls(**{f.name: _coerce(f.type, row.get(f.name)) for f in fields(cls)})
