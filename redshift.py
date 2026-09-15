import json
import time
from dataclasses import fields
from datetime import date, datetime
from typing import Any

import boto3

from model import (
    AssignmentStatus,
    ContentItem,
    Proposal,
    Recommendation,
    Status,
    StudentStatus,
    from_row,
    predecessors,
)

WORKGROUP = "canvas"
DATABASE = "dev"
REGION = "us-east-1"
SCHEMA = "nudges"

_client_cache: Any = None


def _client() -> Any:
    global _client_cache
    if _client_cache is None:
        _client_cache = boto3.client("redshift-data", region_name=REGION)
    return _client_cache


def quote(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime, date)):
        value = value.isoformat()
    return "'" + str(value).replace("'", "''") + "'"


def _columns(cls: type) -> str:
    return ", ".join(f.name for f in fields(cls))


def _cell(cell: dict) -> Any:
    if cell.get("isNull"):
        return None
    for key in ("longValue", "doubleValue", "stringValue", "booleanValue"):
        if key in cell:
            return cell[key]
    return None


def _execute(sql: str, parameters: list[dict] | None = None) -> dict:
    kwargs: dict[str, Any] = {"WorkgroupName": WORKGROUP, "Database": DATABASE, "Sql": sql}
    if parameters:
        kwargs["Parameters"] = [{"name": p["name"], "value": str(p["value"])} for p in parameters]
    statement_id = _client().execute_statement(**kwargs)["Id"]
    while True:
        described = _client().describe_statement(Id=statement_id)
        state = described["Status"]
        if state == "FINISHED":
            return described
        if state in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Redshift statement {state}: {described.get('Error', '')}")
        time.sleep(1)


def run(sql: str, parameters: list[dict] | None = None) -> list[dict]:
    described = _execute(sql, parameters)
    if not described.get("HasResultSet"):
        return []
    rows: list[dict] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Id": described["Id"]}
        if token:
            kwargs["NextToken"] = token
        page = _client().get_statement_result(**kwargs)
        names = [column["name"] for column in page["ColumnMetadata"]]
        for record in page["Records"]:
            rows.append({name: _cell(cell) for name, cell in zip(names, record)})
        token = page.get("NextToken")
        if not token:
            return rows


def load_students(course_id: int) -> list[StudentStatus]:
    sql = f"SELECT {_columns(StudentStatus)} FROM {SCHEMA}.student_course_status WHERE course_id = :course_id"
    rows = run(sql, [{"name": "course_id", "value": course_id}])
    return [from_row(StudentStatus, row) for row in rows]


def load_assignments(course_id: int) -> dict[int, list[AssignmentStatus]]:
    sql = f"SELECT {_columns(AssignmentStatus)} FROM {SCHEMA}.assignment_status WHERE course_id = :course_id"
    by_user: dict[int, list[AssignmentStatus]] = {}
    for row in run(sql, [{"name": "course_id", "value": course_id}]):
        assignment = from_row(AssignmentStatus, row)
        by_user.setdefault(assignment.user_id, []).append(assignment)
    return by_user


def load_content_items(course_id: int) -> list[ContentItem]:
    sql = (
        f"SELECT {_columns(ContentItem)} FROM {SCHEMA}.content_items WHERE course_id = :course_id"
        " ORDER BY module_position, item_position"
    )
    rows = run(sql, [{"name": "course_id", "value": course_id}])
    return [from_row(ContentItem, row) for row in rows]


def existing_dedupe_keys(keys: list[str]) -> set[str]:
    if not keys:
        return set()
    values = ", ".join(quote(key) for key in keys)
    sql = f"SELECT dedupe_key FROM {SCHEMA}.recommendations WHERE dedupe_key IN ({values})"
    return {row["dedupe_key"] for row in run(sql)}


def insert_proposals(proposals: list[Proposal], as_of: date, context: str = "SAT-101") -> int:
    if not proposals:
        return 0
    rows = []
    for p in proposals:
        reason = f"JSON_PARSE({quote(json.dumps(p.reason))})"
        rows.append(
            "("
            + ", ".join(
                [
                    quote(p.rule),
                    quote(p.course_id),
                    quote(p.user_id),
                    quote(p.surface),
                    quote(p.priority),
                    quote(p.text),
                    quote(context),
                    reason,
                    quote(p.next_url),
                    quote(p.next_title),
                    quote(p.dedupe_key(as_of)),
                ]
            )
            + ")"
        )
    sql = (
        f"INSERT INTO {SCHEMA}.recommendations "
        "(rule, course_id, user_id, surface, priority, text, context, reason, "
        "next_url, next_title, dedupe_key) VALUES "
        + ", ".join(rows)
    )
    _execute(sql)
    return len(proposals)


def list_recommendations(status: str | None = None) -> list[Recommendation]:
    sql = f"SELECT {_columns(Recommendation)} FROM {SCHEMA}.recommendations"
    if status is not None:
        sql += " WHERE status = " + quote(status)
    sql += " ORDER BY created_at, id"
    return [from_row(Recommendation, row) for row in run(sql)]


def set_status(
    id: int,
    new_status: Status,
    decided_by: str | None = None,
    note: str | None = None,
    push_error: str | None = None,
) -> bool:
    legal = predecessors(new_status)
    if not legal:
        return False

    assignments = ["status = " + quote(new_status)]
    if decided_by is not None:
        assignments.append("decided_by = " + quote(decided_by))
    if note is not None:
        assignments.append("decision_note = " + quote(note))
    if decided_by is not None or note is not None:
        assignments.append("decided_at = GETDATE()")
    if new_status == Status.pushed:
        assignments.append("pushed_at = GETDATE()")
    if push_error is not None:
        assignments.append("push_error = " + quote(push_error))
    elif new_status == Status.pushed:
        assignments.append("push_error = NULL")

    allowed = ", ".join(quote(s) for s in legal)
    sql = (
        f"UPDATE {SCHEMA}.recommendations SET "
        + ", ".join(assignments)
        + f" WHERE id = {quote(id)} AND status IN ({allowed})"
    )
    described = _execute(sql)
    updated = described.get("ResultRows", -1)
    if updated is not None and updated >= 0:
        return updated > 0
    check = run(f"SELECT status FROM {SCHEMA}.recommendations WHERE id = {quote(id)}")
    return bool(check) and check[0]["status"] == str(new_status)
