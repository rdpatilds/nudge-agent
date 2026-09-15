import argparse
import asyncio
import sys
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

import next_step
import redshift
from canvas_mcp import NudgeSession
from model import Proposal, Recommendation, Status
from rules import RULES, run_rules

TZ = "America/New_York"
DEFAULT_COURSE = 1
PUSH_CONTEXT = "SAT-101"


def today() -> date:
    return datetime.now(ZoneInfo(TZ)).date()


def scan(course_id: int, as_of: date) -> tuple[list[Proposal], int]:
    students = redshift.load_students(course_id)
    assignments = redshift.load_assignments(course_id)
    proposals = run_rules(students, assignments, as_of)
    items = redshift.load_content_items(course_id)
    by_user = {s.user_id: s for s in students}
    proposals = [
        next_step.resolve(p, by_user[p.user_id], assignments.get(p.user_id, []), items, course_id)
        for p in proposals
    ]
    seen = redshift.existing_dedupe_keys([p.dedupe_key(as_of) for p in proposals])
    fresh = [p for p in proposals if p.dedupe_key(as_of) not in seen]
    redshift.insert_proposals(fresh, as_of, PUSH_CONTEXT)
    return fresh, len(proposals) - len(fresh)


def proposed_rows() -> list[Recommendation]:
    return redshift.list_recommendations(Status.proposed)


def history_rows() -> list[Recommendation]:
    keep = (Status.approved, Status.pushed, Status.push_failed, Status.rejected)
    return [r for r in redshift.list_recommendations() if r.status in keep]


def status_counts() -> dict[str, int]:
    return Counter(r.status for r in redshift.list_recommendations())


def approve(ids: list[int], decided_by: str) -> list[int]:
    return [i for i in ids if redshift.set_status(i, Status.approved, decided_by=decided_by)]


def approve_all(decided_by: str) -> list[int]:
    return approve([r.id for r in proposed_rows()], decided_by)


def reject(rec_id: int, note: str, decided_by: str) -> bool:
    return redshift.set_status(rec_id, Status.rejected, decided_by=decided_by, note=note)


def push_approved() -> dict[str, int]:
    pending = [
        r
        for r in redshift.list_recommendations()
        if r.status in (Status.approved, Status.push_failed)
    ]
    return asyncio.run(_push(pending))


async def _push(pending: list[Recommendation]) -> dict[str, int]:
    tally = {"pushed": 0, "already_present": 0, "failed": 0, "skipped_advisor": 0}
    rows = []
    for row in pending:
        if row.surface == "advisor":
            tally["skipped_advisor"] += 1
        else:
            rows.append(row)
    if not rows:
        return tally

    async with NudgeSession() as session:
        for row in rows:
            try:
                if row.text in await session.list_text(row.user_id):
                    redshift.set_status(row.id, Status.pushed)
                    tally["already_present"] += 1
                    continue
                await session.push(row.user_id, row.text, PUSH_CONTEXT, row.next_url or "")
                redshift.set_status(row.id, Status.pushed)
                tally["pushed"] += 1
            except Exception as exc:
                redshift.set_status(row.id, Status.push_failed, push_error=str(exc)[:512])
                tally["failed"] += 1
    return tally


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip())
    return "\n".join(lines)


def cmd_scan(args: argparse.Namespace) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else today()
    fresh, duplicates = scan(args.course, as_of)
    by_rule: dict[str, list[int]] = {rule.id: [] for rule in RULES}
    for p in fresh:
        by_rule.setdefault(p.rule, []).append(p.user_id)
    print(f"as_of {as_of.isoformat()} course {args.course}")
    for rule_id, user_ids in by_rule.items():
        print(f"{rule_id}: {len(user_ids)}  users {sorted(user_ids)}")
    print(f"inserted {len(fresh)}, skipped as duplicate {duplicates}")
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    rows = proposed_rows()
    if not rows:
        print("no proposed recommendations")
        return 0
    print(
        _table(
            ["id", "rule", "user_id", "surface", "text", "next"],
            [
                [str(r.id), r.rule, str(r.user_id), r.surface, r.text, r.next_title or ""]
                for r in rows
            ],
        )
    )
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    done = approve_all("cli") if args.all else approve(args.ids, "cli")
    print(f"approved {len(done)}: {done}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    ok = reject(args.id, args.note, "cli")
    print(f"rejected {args.id}" if ok else f"{args.id} is not in a rejectable state")
    return 0 if ok else 1


def cmd_push(args: argparse.Namespace) -> int:
    tally = push_approved()
    print(
        f"pushed {tally['pushed']}, already present {tally['already_present']}, "
        f"failed {tally['failed']}, skipped advisor {tally['skipped_advisor']}"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    counts = status_counts()
    for state in Status:
        print(f"{state.value}: {counts.get(state.value, 0)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nudge_agent", description="Propose, approve and push Canvas nudges.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="run the rules and insert new proposals")
    scan_parser.add_argument("--course", type=int, default=DEFAULT_COURSE)
    scan_parser.add_argument("--as-of", dest="as_of", metavar="YYYY-MM-DD")
    scan_parser.set_defaults(func=cmd_scan)

    queue_parser = sub.add_parser("queue", help="show the proposed recommendations")
    queue_parser.set_defaults(func=cmd_queue)

    approve_parser = sub.add_parser("approve", help="approve recommendations by id")
    approve_parser.add_argument("ids", nargs="*", type=int)
    approve_parser.add_argument("--all", action="store_true")
    approve_parser.set_defaults(func=cmd_approve)

    reject_parser = sub.add_parser("reject", help="reject one recommendation")
    reject_parser.add_argument("id", type=int)
    reject_parser.add_argument("--note", required=True)
    reject_parser.set_defaults(func=cmd_reject)

    push_parser = sub.add_parser("push", help="push approved recommendations to Canvas")
    push_parser.set_defaults(func=cmd_push)

    status_parser = sub.add_parser("status", help="count recommendations per status")
    status_parser.set_defaults(func=cmd_status)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "approve" and not args.all and not args.ids:
        parser.error("approve needs ids or --all")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
