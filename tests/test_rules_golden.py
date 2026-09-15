import pytest

import next_step
from model import Proposal
from rules import RULES, run_rules

COURSE = 1
ITEMS = "http://localhost:3100/courses/1/modules/items"

EXPECTED_FIRINGS = {
    "A1": {4, 5, 6, 8, 10, 11},
    "A2": {3, 5, 6, 10},
    "A3": {5},
    "A4": {6},
    "A5": {4, 10},
    "B3": {7},
    "R1": {5, 6, 10},
    "R2": {5, 6, 10},
}

LINKLESS_RULES = {"A4", "R1", "R2"}


@pytest.fixture(scope="module")
def proposals(students, assignments_by_user, items, as_of) -> list[Proposal]:
    return run_rules(students, assignments_by_user, items, as_of)


@pytest.fixture(scope="module")
def resolved(students, assignments_by_user, items, proposals) -> list[Proposal]:
    by_user = {s.user_id: s for s in students}
    return [
        next_step.resolve(
            p, by_user[p.user_id], assignments_by_user.get(p.user_id, []), items, COURSE
        )
        for p in proposals
    ]


def _one(proposals: list[Proposal], rule: str, user_id: int) -> Proposal:
    return next(p for p in proposals if p.rule == rule and p.user_id == user_id)


def _text(proposals, rule: str, user_id: int) -> str:
    return _one(proposals, rule, user_id).text


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


NEXT_STEPS = [
    ("A1", 4, f"{ITEMS}/4", "Word Problems Set"),
    ("A2", 5, f"{ITEMS}/2", "Grammar Rules Drill 1"),
    ("A2", 3, f"{ITEMS}/3", "Linear Equations Set"),
    ("A3", 5, f"{ITEMS}/2", "Grammar Rules Drill 1"),
    ("A5", 4, f"{ITEMS}/8", "Reading Checkpoint Quiz"),
    ("B3", 7, f"{ITEMS}/9", "Reading Practice Set"),
]


@pytest.mark.parametrize("rule,user_id,url,title", NEXT_STEPS)
def test_next_step_links(
    resolved: list[Proposal], rule: str, user_id: int, url: str, title: str
) -> None:
    proposal = _one(resolved, rule, user_id)
    assert (proposal.next_url, proposal.next_title) == (url, title)


def test_a4_is_never_linked(resolved: list[Proposal]) -> None:
    assert _one(resolved, "A4", 6).next_url is None


def test_r1_carries_no_link(resolved: list[Proposal]) -> None:
    assert _one(resolved, "R1", 6).next_url is None


def test_b3_falls_back_to_the_first_practice_item(resolved: list[Proposal]) -> None:
    assert _one(resolved, "B3", 7).reason["next_step_basis"] == "first_practice"


def test_every_linking_proposal_has_a_link(resolved: list[Proposal]) -> None:
    assert [
        p.rule for p in resolved if p.rule not in LINKLESS_RULES and p.next_url is None
    ] == []
