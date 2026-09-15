# nudge-agent

Reads student status from Redshift, proposes nudges with the rules in `rules.py`, attaches a next
step to each with the resolvers in `next_step.py`, waits for a human decision, and pushes the
approved ones into Canvas through the Canvas MCP server. It also builds each student an ordered
learning path, the short to-do list the dashboard shows under the nudges.

## Commands

```
uv run nudge_agent.py scan [--course 1] [--as-of YYYY-MM-DD]
uv run nudge_agent.py path [--course 1] [--as-of YYYY-MM-DD]
uv run nudge_agent.py queue
uv run nudge_agent.py approve 12 13
uv run nudge_agent.py approve --all
uv run nudge_agent.py reject 14 --note "already covered in advising"
uv run nudge_agent.py push
uv run nudge_agent.py status
```

`scan` runs the rules, resolves the next step for each proposal, inserts the new proposals, and
then rebuilds every learning path. `path` rebuilds the paths on their own and prints a row per
student. `queue` lists what is waiting for a decision. Its `next` column is the title of the
linked item. `push` sends every approved row to Canvas. `as_of` defaults to today in
America/New_York.

## Learning paths

A path is up to eight module items in the order the student should work them, written to
`nudges.learning_paths`. Each rebuild replaces the whole course in one statement, so the table
always reflects the last run and never needs a cleanup pass. Five slots fill the path in order:
missing assignments oldest first, then work due soon, then an unfinished quiz, then practice
items matching a topic the student is behind on, then the rest of the course in module order.
Each step records the reason the student is being sent there and the rule the slot came from.
A student who has finished every module requirement gets an empty path.

The cap of eight is deliberate. The path is a to-do list on a dashboard, not a syllabus.

## Remediation modules and the module surface

A module named `Remediation: <topic>` is the remedial module for that topic. Rule `R1` proposes
assigning one to a student who is at medium or high risk, or averaging under 60 percent on
quizzes, and whose missing work names that topic. Those proposals carry the surface `module`
rather than `block`, and they queue and approve like any other row.

Pushing a `module` row does not write a dashboard nudge. It calls the MCP tool
`assign_module_to_students`, which adds the student to the module's Canvas override. The tool is
additive and idempotent, so a row whose student is already covered comes back as
`Already assigned` and is marked pushed without a second write.

Canvas module overrides are also what the path builder reads for visibility. A module carrying
any override is visible only to the students its overrides cover, so `canvas_api.module_gates`
fetches the overrides for every module in the course and the builder drops the items a student
cannot see. A module with no overrides is open to everyone. This is why the remediation module
appears in a student's path only after an educator has approved and pushed the `R1` row for
them. `CANVAS_TOKEN` overrides the default dev token.

Canvas caches each student's module visibility for five minutes
(`VisibilityHelpers::CacheSettings.ttl`), and writing an override does not clear that cache.
If the student's Modules page was loaded shortly before the push, the remediation module stays
hidden until the cache expires. The override itself is in place immediately; confirm it with
`list_module_overrides` or `GET /api/v1/courses/1/modules/4/assignment_overrides`, and expect
the Modules page to catch up within five minutes.

Windows ships no time zone database, which is why `tzdata` is a dependency. Nothing else in
the tool reads the clock.

## Practice quizzes and the quiz surface

Rule `R2` fires on exactly the condition `R1` fires on: a student at medium or high risk, or
averaging under 60 percent on quizzes, whose missing work names the topic of a remediation
module. Both rules read that condition from one helper in `rules.py`, so they cannot drift
apart. Where `R1` proposes assigning the module, `R2` proposes building a five-question practice
quiz on that topic inside it. One proposal per remediation module, on the surface `quiz`. It
queues, approves and rejects like any other row, and `queue` prints it in the same table.

Pushing a `quiz` row reads `nudges.question_pool`, takes the first five questions for the topic
in `question_id` order, and calls the MCP tool `create_quiz_from_pool`. Canvas gets a practice
quiz, so it never affects a grade, published on creation so the student can take it the moment
the educator approves. The tool is idempotent by title within the course. A second approved row
for the same topic therefore finds the quiz that already exists, and the push only updates that
row's next step. When the push did create the quiz it also writes one `nudges.content_items` row
for it, which puts the quiz in a student's path on the next `path` run without waiting for a
full reload from Canvas. A later `load_content_items.py` run in the `redshift` repository
produces the same row.

Question selection is deterministic. Same topic, same five questions, every run, so a retry
after a crash builds the quiz the educator approved rather than a different one.

The pool is a stand-in for a real question bank. `nudges.question_pool` holds sixteen seeded SAT
questions across four topics, loaded by `load_question_pool.py` in the sibling `redshift`
repository. That repository's README describes the table and where a real bank would replace it.

## Approval page

```
uv run approve_web.py
```

Open http://127.0.0.1:8765. The page lists the proposed rows with per-row Approve and Reject
buttons, an Approve all button, a Push approved button, and the history of decided rows. The
next step shows as a link in both tables. Use `--port` to bind somewhere else. The page calls
the same functions as the CLI and records `web` as the decider.

## Schedule

```
powershell -File D:\Canvas\nudge-agent\register_schedule.ps1 -DryRun
powershell -File D:\Canvas\nudge-agent\register_schedule.ps1
```

This registers `CanvasNudgeScan` at 09:00 and `CanvasNudgePush` at 09:30 daily, appending
output to `logs\scan.log` and `logs\push.log`. `-DryRun` prints the two `schtasks` lines and
creates nothing.

## Why reruns are safe

Two things carry that weight. Each proposal has a dedupe key of rule, course, user, subject and
date, so a second `scan` on the same day inserts nothing new. Each row moves through the status
state machine in `model.py`, and every status update names the statuses it is allowed to move
from, so a second `approve` or `push` on a row that has already moved updates no rows. `push`
also reads the student's current nudges first and marks a row pushed without writing when its
text is already there, which covers a crash between the Canvas write and the status update.

## Testing end to end

Run these in PowerShell, in order. Each step ends with what to expect.

Every command under `D:\Canvas\test\canvas\cmcp` needs `--no-sync`. Plain `uv run` there
re-syncs the project and tries to replace `.venv\Scripts\canvas-mcp-server.exe`, which fails
with `os error 32` whenever a Claude Code session or the agent has that server running.

1. Confirm Canvas and Redshift are reachable.

   ```
   docker ps --filter name=cplatform
   cd D:\Canvas\redshift
   uv run query.py --sql "SELECT COUNT(*) FROM nudges.student_course_status"
   uv run query.py --sql "SELECT COUNT(*) FROM nudges.assignment_status"
   ```

   Expect the container running, then counts of 10 and 18.

2. Look at the seed data and the user id map.

   ```
   uv run query.py --sql "SELECT user_id, name, days_inactive, assignments_missing, risk_level FROM nudges.student_course_status ORDER BY user_id"
   ```

   Expect ten students, ids 2 to 6 and 8 to 12. There is no user 7.

3. Run the offline golden test.

   ```
   cd D:\Canvas\nudge-agent
   uv run pytest -q
   ```

   Expect `29 passed`. The tests read the seed CSVs from the sibling `redshift`
   repository, the module items from `tests\fixtures\content_items.csv`, and the question
   pool from `tests\fixtures\question_pool.csv`.

4. Optional. Reset the queue to start clean.

   ```
   cd D:\Canvas\redshift
   uv run query.py --sql "TRUNCATE TABLE nudges.recommendations"
   ```

5. Scan and see what the agent proposes.

   ```
   cd D:\Canvas\nudge-agent
   uv run nudge_agent.py scan --as-of 2026-09-15
   uv run nudge_agent.py queue
   uv run nudge_agent.py status
   ```

   Expect 21 inserted, then the queue and a status of proposed 21. Six of those come from the
   remediation rules, for users 5, 6 and 10: three R1 rows on the `module` surface and three R2
   rows on the `quiz` surface. Scan also rebuilds the paths and prints the total step count. If
   you skipped step 4, scan inserts 0 and reports 21 duplicates.

6. Prove reruns are safe.

   ```
   uv run nudge_agent.py scan --as-of 2026-09-15
   ```

   Expect inserted 0, skipped as duplicate 21. The paths are rebuilt either way, because
   `replace_paths` deletes and reinserts the course rather than deduplicating.

   Check the paths on their own:

   ```
   uv run nudge_agent.py path --as-of 2026-09-15
   ```

   Expect a row per student and Ava at 0 steps, because she has finished every module
   requirement. Elena's eighth step is the module 2 Algebra Refresher until an R1 row is pushed
   for her.

7. Check Elena's dashboard before pushing.

   ```
   cd D:\Canvas\test\canvas\cmcp
   uv run --no-sync scripts/check_nudges_mcp.py --user 6 --list
   ```

   Note the count. Log in at http://localhost:3100/login/canvas as `elena.rossi@sat.test`
   with `Password123!` and look at the Nudges block.

8. Approve through the web page.

   ```
   cd D:\Canvas\nudge-agent
   uv run approve_web.py
   ```

   Open http://127.0.0.1:8765, wait a few seconds for the render, approve one of user 6's
   rows and reject another with a note. Or from the CLI, with ids from the queue output:

   ```
   uv run nudge_agent.py approve 5
   uv run nudge_agent.py reject 7 --note "advisor handled"
   ```

9. Push the approved nudges. Click "Push approved" on the page, or:

   ```
   uv run nudge_agent.py push
   uv run nudge_agent.py status
   ```

   Expect pushed 1, failed 0.

10. Verify on Canvas.

    ```
    cd D:\Canvas\test\canvas\cmcp
    uv run --no-sync scripts/check_nudges_mcp.py --user 6 --list
    ```

    Expect the step 7 count plus one, with the new text present once. Refresh Elena's
    dashboard. The admin login is `admin@cplatform.test` with `cplatform-admin`.

11. Prove push cannot double-send.

    ```
    cd D:\Canvas\nudge-agent
    uv run nudge_agent.py push
    ```

    Expect pushed 0 and an unchanged count in step 10.

12. Test the schedule without waiting for 09:00.

    ```
    schtasks /Query /TN CanvasNudgeScan
    schtasks /Run /TN CanvasNudgeScan
    Get-Content D:\Canvas\nudge-agent\logs\scan.log -Tail 20
    schtasks /Run /TN CanvasNudgePush
    Get-Content D:\Canvas\nudge-agent\logs\push.log -Tail 20
    ```

    Expect both tasks Ready and the logs showing the same summaries as steps 5 and 9.

13. Cleanup dry run, then teardown when the POC is done.

    ```
    cd D:\Canvas\redshift
    uv run cleanup.py
    ```

    Expect exactly three ARNs: workgroup, namespace, subnet. To tear down:

    ```
    uv run cleanup.py --yes
    schtasks /Delete /TN CanvasNudgeScan /F
    schtasks /Delete /TN CanvasNudgePush /F
    ```

To clear Elena's dashboard for a fresh demo:

```
cd D:\Canvas\test\canvas\cmcp
uv run --no-sync scripts/check_nudges_mcp.py --user 6 --clear
```
