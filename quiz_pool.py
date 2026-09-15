"""Choose the questions and the name for one generated practice quiz.

Selection is deterministic. A topic's pool is ordered by question_id and the first `count`
questions win, so the same approved row pushed twice, or a rerun after a crash between the
Canvas call and the Redshift write, asks for the same quiz body rather than a different one.

The title is what makes the tool idempotent within a course. `create_quiz_from_pool` matches
on title, so a second call for the same topic finds the quiz already there and reports it back
as existing instead of making a duplicate.

A topic holding fewer than `count` questions yields what it has. A short quiz is not an error.
"""

from model import PoolQuestion


def select_questions(pool: list[PoolQuestion], topic: str, count: int) -> list[PoolQuestion]:
    """pool filtered to `topic`, ordered by question_id, first `count`."""
    matches = [q for q in pool if q.topic == topic]
    return sorted(matches, key=lambda q: q.question_id)[:count]


def quiz_title(topic: str, course_code: str = "SAT-101") -> str:
    return f"{topic} practice quiz ({course_code})"


def to_tool_questions(questions: list[PoolQuestion]) -> list[dict]:
    return [
        {
            "text": q.question_text,
            "type": q.question_type,
            "answers": [{"text": a["text"], "correct": a["correct"]} for a in q.answers],
            "points": q.points,
        }
        for q in questions
    ]
