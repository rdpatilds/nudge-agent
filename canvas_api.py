"""Read-only Canvas HTTP adapter over the standard library.

A module carrying any assignment override is visible only to the students those
overrides name, directly or through a section; a module with no overrides at all
is open to everyone, so it never appears in the gates a course returns.
"""

import json
import os
import urllib.request

from model import Gates
from next_step import CANVAS_URL

API_URL = f"{CANVAS_URL}/api/v1"
DEFAULT_TOKEN = "cplatform-dev-token"


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ.get('CANVAS_TOKEN', DEFAULT_TOKEN)}"}


def _get(path: str) -> list[dict]:
    request = urllib.request.Request(f"{API_URL}{path}", headers=_headers())
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read()) or []


def _section_members(course_id: int) -> dict[int, set[int]]:
    sections = _get(f"/courses/{course_id}/sections?include[]=students")
    return {
        section["id"]: {student["id"] for student in section.get("students") or []}
        for section in sections
    }


def module_gates(course_id: int, module_ids: list[int]) -> Gates:
    gates: Gates = {}
    members: dict[int, set[int]] | None = None
    for module_id in module_ids:
        overrides = _get(f"/courses/{course_id}/modules/{module_id}/assignment_overrides")
        if not overrides:
            continue
        allowed: set[int] = set()
        for override in overrides:
            allowed.update(student["id"] for student in override.get("students") or [])
            section_id = (override.get("course_section") or {}).get("id")
            if section_id is None:
                continue
            if members is None:
                members = _section_members(course_id)
            allowed.update(members.get(section_id) or set())
        gates[module_id] = allowed
    return gates
