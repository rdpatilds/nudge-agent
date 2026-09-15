# nudge-agent

Reads student status from Redshift, proposes nudges with the rules in `rules.py`, attaches a next
step to each with the resolvers in `next_step.py`, waits for a human decision, and pushes the
approved ones into Canvas through the Canvas MCP server.

## Commands

```
uv run nudge_agent.py scan [--course 1] [--as-of YYYY-MM-DD]
uv run nudge_agent.py queue
uv run nudge_agent.py approve 12 13
uv run nudge_agent.py approve --all
uv run nudge_agent.py reject 14 --note "already covered in advising"
uv run nudge_agent.py push
uv run nudge_agent.py status
```

`scan` runs the rules, resolves the next step for each proposal, and inserts the new
proposals. `queue` lists what is waiting for a decision. Its `next` column is the title of the
linked item. `push` sends every approved row to Canvas, text and link together. `as_of`
defaults to today in America/New_York.

Windows ships no time zone database, which is why `tzdata` is a dependency. Nothing else in
the tool reads the clock.

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

   Expect `12 passed`. The test reads the seed CSVs from the sibling `redshift`
   repository and the module items from `tests\fixtures\content_items.csv`.

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

   Expect 15 inserted, then the queue and a status of proposed 15. If you skipped step 4,
   scan inserts 0 and reports 15 duplicates.

6. Prove reruns are safe.

   ```
   uv run nudge_agent.py scan --as-of 2026-09-15
   ```

   Expect inserted 0, skipped as duplicate 15.

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
