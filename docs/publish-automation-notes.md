# Working note: automating the daily run, report and gh-pages publish

Temporary. Delete this note once the work is done and its settled rules are in data.md, outputs.md and roadmap.md.

## Summary

It is feasible: most of the pieces already exist, and the roadmap already lists this work as 1f.3, 1f.4 and 1f.7 (1f.1, the contract selection, is built). The main things to settle first:

1. **Contract roll on 2026-11-13.** Contract selection is built (1f.1): `refdata.contracts_on(asof)`, which `ctd history` and `ctd report` default to. What's left is to check the March data is stored by 11-13 (concern 1) and to size the overlap week's pages.
2. **Git shouldn't touch the working checkout.** Do the gh-pages commit and push from a separate git worktree that only the task uses, so a 09:15 branch switch can't collide with editing.
3. **The task runs whatever code is checked out.** If `main` is left half-edited or on another branch overnight, the morning job uses that code and publishes its output. Either run from a clean `main` worktree (1f.6) or have the publish step refuse when the tree isn't clean on `main`.
4. **Push credentials with nobody at the keyboard.** Git Credential Manager is the credential helper. If its token expires, it opens a sign-in window and the task hangs for up to 2 hours. Set `GCM_INTERACTIVE=never` and `GIT_TERMINAL_PROMPT=0` so the push fails fast and raises an alert.
5. **Publish only a complete day.** Skip publishing if the derive skipped the date or any contract failed. When there's nothing new to commit, the step should finish cleanly instead of failing.

## Context

The `ctd-morning` task (09:15 on weekdays, `scripts/morning.py`) runs fetch, SOFR and derive. The model run, `ctd report` and the gh-pages upload are done by hand: commits like "upload 2026-10-28" on `gh-pages`, with `index.html` a copy of the latest summary. The plan is to switch the automation on once a morning job runs clean (1e.5).

**Verdict: feasible, and most of the pieces exist.** `ctd history`, `ctd run` and `ctd report` already return non-zero on failure (`src/ctd/cli.py`). `morning.py` is a plain step list, `morning_check.py` already re-runs a failed task, and `gh-pages` is a plain static branch (`.nojekyll`, about 1.7 MB a day). The work is mostly glue. The risks are in the concerns below, roughly in order of importance.

## Concerns to settle first

1. **The roll on 2026-11-13.** From 11-13 to 11-19 each product runs two contracts (eight in all), and from 11-20 only March. The automation must call `ctd history` and `ctd report` without `--contract` (or `refdata.contracts_on(D)`), never a hard-coded list. Left to check:
   - the March contracts' inputs are stored for 11-13: the daily pull's front two futures and the DEC/MAR options are expected, and the TCF basket is listed three contract months ahead (design §7); confirm on the first morning;
   - the five overlap days' pages are about twice the size (eight contracts, about 3.4 MB a day against 1.7 MB), a small cost on `gh-pages`;
   - `ctd report` now errors if any of the day's contracts has no saved result, which is the "complete day" gate (concern 5) for free; the new March series has one point on 11-13, so its chart 3 starts on 11-16.
2. **Keep git off the dev checkout.** The `gh-pages` branch has a `.gitignore` for `/data/` and `/output/`, which suggests the manual upload switches branches in the main working tree. A 09:15 task that runs `git checkout` there could collide with editing. Do the publish in a **dedicated worktree** (`git worktree add ..\ctd-pages gh-pages`) that only the task touches.
3. **The task runs whatever code is checked out.** If `main` is left mid-edit or on a feature branch overnight, the morning run uses that code and then publishes its output. Options: run from a clean `main` worktree (that is 1f.6), or have the publish step refuse when `git status` on the code tree isn't clean or isn't on `main`.
4. **Push authentication with nobody at the keyboard.** The credential helper is Git Credential Manager. Its cached token normally works from the task, which runs as the logged-on user, including when the screen is locked. But if the token expires, GCM opens a sign-in window and the task hangs until its 2-hour limit. Set `GCM_INTERACTIVE=never` and `GIT_TERMINAL_PROMPT=0` for the push so it fails fast and raises an alert. Or use an SSH key that only this repo uses.
5. **Publish only a complete day.** Gate publishing on: derive actually derived D (not skipped), every contract for D ran, and the report built. A partial run should alert and publish nothing. The morning check's 10:30 re-run then retries it naturally.
6. **Make re-runs and races harmless.** A re-run of the same date has to work: when nothing has changed, skip the commit rather than letting `git commit` fail. Before committing, `git fetch` and fast-forward `gh-pages`, in case of a manual push from somewhere else. Never force-push.
7. **Bad numbers go out unseen.** Today each page is looked at before upload. Consider a hold: publish nothing, and alert instead, if `ctd run` printed warnings (for example SOFR falling back to D−1) or a DV01 moved more than some threshold from the day before. The publish can then be released by hand.

## Implementation (once 1e.5 passes)

1. **1f.1** (done) `refdata.contracts_on(asof)`; `ctd history` and `ctd report` default to it.
2. **1f.3** `scripts/morning_run.py [--asof D]`:
   - D is the previous `cme` business day, the same as `morning_derive.py`. Exit 0 and do nothing on a non-business day.
   - Run `ctd history --from D --to D` (no `--contract`: the run window picks the contracts), then `ctd report --asof D --out <pages worktree>`. Writing straight into the worktree makes `archive.html` list every published date.
   - Copy `D.html` to `index.html`.
   - Alert through `ctd.data.alert.notify` and exit non-zero on any failure.
3. **1f.7** `scripts/morning_publish.py`, kept separate so it can be switched off:
   - In the pages worktree, check the code tree is clean and on `main` (concern 3).
   - `git fetch`, then `git merge --ff-only origin/gh-pages`.
   - `git add -A`; if nothing is staged, exit 0.
   - Commit "upload D" and push with no prompts allowed (concern 4).
   - Alert on failure.
   - Optional: a `--hold` flag, or the warning check from concern 7.
4. **1f.4** Add `("run", ...)` and `("publish", ...)` to the `steps` in `scripts/morning.py`. Unlike the existing steps, each runs only if the step before it exited 0. Both are recorded in `morning_status.json`'s `failed` list, so the 10:30 morning check re-runs the task.
5. Docs:
   - data.md §4: the new step rows and the worktree location.
   - outputs.md: the publishing rule and gate.
   - roadmap.md: tick 1f.3, 1f.4 and 1f.7.
   - The docstrings of `morning.py` and `register_morning_tasks.ps1`.

## Verification

- Unit tests:
  - `morning_run`'s choice of D on a Monday and the day after a holiday;
  - the publish step's "nothing to commit" path, run against a temporary git repo.
- Roll dry run: `ctd history --from 2026-11-12 --to 2026-11-20 --no-save` lists the right contracts per day (tested in `tests/test_window.py`); on 11-13 to 11-19 the March runs need that day's stored data.
- Dry run: `morning_run.py --asof 2026-10-28` into a scratch pages worktree. Diff the result against the `9d61c15` commit on `origin/gh-pages`: it should be identical, apart from anything the code has changed since.
- Run `morning.py` by hand once with the publish step pushing to a test branch. Then run it for real from the scheduled task with the screen locked, to check that pushing without a prompt works.
