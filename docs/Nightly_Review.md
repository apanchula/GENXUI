# ROLE: Supervisory Agent - Nightly Review & Revision Loop

> **Invocation:** This procedure runs automatically as the Review Step of the nightly scheduled task defined in `Supervisor.md` Part D, immediately before that same session generates the next `TASK.md` and hands off to worker execution. It is not a separate manual step.

Please run `git status` and `git diff` on `feature/v2-refresh` to review the changes completed during the 11 PM - 2 AM session. Cross-reference the diff against the active `TASK.md`'s metadata header (`base_commit`) to confirm the agent worked from the expected codebase state.

## TASKS:
1. **Assess Progress:** Compare the committed code against the Definition of Done for the active ticket. Where criteria were written to be machine-checkable, verify them directly (run the check) rather than inspecting code by eye.
2. **Check Scope Boundaries:** Confirm the diff only touches files from the ticket's "Key Files to Modify/Create" allow-list, and that any "Do-Not-Touch" files received only minimal, additive changes. Flag any out-of-scope changes even if the Definition of Done otherwise passed.
3. **Read Blockers / Notes:** Check `TASK.md`'s Blockers/Notes section, split by category:
   - **Blocked** items → these are retry candidates; the ticket can be carried forward as-is.
   - **Plan Issue** items → these mean the ticket's Acceptance Criteria themselves are wrong or unsatisfiable. Do not just re-queue the same `TASK.md` — the underlying Part A ticket in `Supervisor.md` needs revision first.
4. **Verify Commit Hygiene:** Confirm commits are prefixed with the ticket ID per the Commit Convention. Note any commits that aren't, as a signal the agent may have drifted from the active ticket.
5. **Apply the Supervisor.md Part C Rule** to decide the outcome:
   - Fully met → tell Supervisor to archive `TASK.md` and generate the next ticket's `TASK.md`.
   - Partially met, Blocked only → tell Supervisor to carry the same ticket forward (new `TASK.md`, night count incremented).
   - Partially met, Plan Issue present → do not regenerate `TASK.md` yet; flag the specific conflicting Acceptance Criteria for Part A revision and surface it to the user.
6. **Log Unfinished Items / Bugs:** For anything not covered above (e.g. a bug found in already-archived work), create a patch ticket (e.g. `GENXUI-1B`) in Supervisor.md Part A rather than folding it into the current ticket's scope.
