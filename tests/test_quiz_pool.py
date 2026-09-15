import pytest

from canvas_mcp import parse_quiz_result
from model import Proposal
from quiz_pool import quiz_title, select_questions, to_tool_questions
from rules import run_rules

CREATED = (
    "quiz_id=12 url=http://localhost:3100/courses/1/quizzes/12 questions=5 "
    "published=true module_item_id=21 created=true"
)

EXISTING = (
    "quiz_id=12 url=http://localhost:3100/courses/1/quizzes/12 questions=5 "
    "published=true module_item_id=none created=false"
)


@pytest.fixture(scope="module")
def proposals(students, assignments_by_user, items, as_of) -> list[Proposal]:
    return run_rules(students, assignments_by_user, items, as_of)


def test_r2_fires_for_the_students_a_remedial_topic_reaches(proposals):
    assert {p.user_id for p in proposals if p.rule == "R2"} == {5, 6, 10}


def test_r2_names_the_count_the_topic_and_the_module(proposals):
    elena = next(p for p in proposals if p.rule == "R2" and p.user_id == 6)
    assert elena.text == (
        "Create a 5-question Heart of Algebra practice quiz for Elena Rossi "
        "in Remediation: Heart of Algebra"
    )
    assert elena.surface == "quiz"
    assert elena.subject == "quiz:4:Heart of Algebra"
    assert elena.reason == {
        "topic": "Heart of Algebra",
        "count": 5,
        "module_id": 4,
        "module_name": "Remediation: Heart of Algebra",
    }


def test_selection_takes_the_lowest_question_ids_for_the_topic(pool):
    assert [q.question_id for q in select_questions(pool, "Heart of Algebra", 5)] == [
        1,
        2,
        3,
        4,
        5,
    ]


def test_a_thin_topic_yields_what_it_has(pool):
    assert [q.question_id for q in select_questions(pool, "Reading", 5)] == [10, 11, 12, 13]


def test_the_title_is_the_same_for_every_run_of_a_topic():
    assert quiz_title("Heart of Algebra") == "Heart of Algebra practice quiz (SAT-101)"


def test_tool_questions_carry_the_stem_and_one_correct_answer(pool):
    question = next(q for q in pool if q.question_id == 1)
    (payload,) = to_tool_questions([question])
    assert payload["text"] == "If 3x + 7 = 22, what is the value of x?"
    assert payload["type"] == "multiple_choice_question"
    assert payload["points"] == 1
    assert len(payload["answers"]) == 4
    assert [a["text"] for a in payload["answers"] if a["correct"]] == ["5"]


def test_parse_quiz_result_reads_a_created_quiz():
    assert parse_quiz_result(CREATED) == {
        "quiz_id": 12,
        "url": "http://localhost:3100/courses/1/quizzes/12",
        "questions": 5,
        "published": True,
        "module_item_id": 21,
        "created": True,
    }


def test_parse_quiz_result_reads_a_quiz_that_was_already_there():
    result = parse_quiz_result(EXISTING)
    assert (result["module_item_id"], result["created"]) == (None, False)


def test_parse_quiz_result_rejects_anything_else():
    with pytest.raises(RuntimeError):
        parse_quiz_result("Error: no questions for topic Reading")
