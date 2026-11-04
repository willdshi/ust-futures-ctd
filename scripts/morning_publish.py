"""Commit the day's report pages to the ``gh-pages`` worktree and push them (roadmap 1f.7).

    python scripts/morning_publish.py [--asof 2026-10-28] [--pages DIR] [--remote-branch gh-pages] [--no-notify]

Run as the last step of ``scripts/morning.py``, after ``morning_run.py``, which writes the pages into the
worktree (``$CTD_OUTPUT_DIR``, ``prod_env.ps1``). Kept apart so publishing can be switched off. Nothing
happens, with exit 0, on a day ``morning_run.py`` skips. Otherwise:

1. the code checkout is on ``main`` with nothing uncommitted, and the worktree is on ``gh-pages``;
2. ``git fetch`` and a fast-forward to ``origin/gh-pages``, in case of a push from elsewhere;
3. ``git add -A``; if nothing changed there is nothing to commit, which is not an error (a re-run);
4. commit "upload D", then push. Never forced. ``GCM_INTERACTIVE=never`` and ``GIT_TERMINAL_PROMPT=0`` make
   an expired credential fail at once and alert, instead of waiting for a sign-in nobody sees until the
   task's time limit.

Anything unpushed (a push that failed earlier) goes out with the next run. A failure raises a desktop alert
and exits 1. ``--remote-branch`` pushes to another branch, to try the step without publishing.
"""

import argparse
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from morning_run import choose_asof  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PAGES_BRANCH = "gh-pages"
NO_PROMPT = {"GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0"}


class PublishError(Exception):
    pass


def git(cwd: Path, *args: str, timeout: int = 300, check: bool = True) -> str:
    """Run ``git`` in ``cwd`` without any prompt; stdout, or PublishError with git's message on failure."""
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, **NO_PROMPT})
    except subprocess.TimeoutExpired:
        raise PublishError(f"git {' '.join(args)} timed out after {timeout} s") from None
    if check and p.returncode:
        raise PublishError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip() if check else str(p.returncode)


def check_trees(code: Path, pages: Path) -> None:
    if (branch := git(code, "branch", "--show-current")) != "main":
        raise PublishError(f"the code checkout {code} is on '{branch}', not main")
    if dirty := git(code, "status", "--porcelain"):
        raise PublishError(f"the code checkout {code} has uncommitted changes:\n{dirty[:300]}")
    if (branch := git(pages, "branch", "--show-current")) != PAGES_BRANCH:
        raise PublishError(f"the pages worktree {pages} is on '{branch}', not {PAGES_BRANCH}")


def publish(pages: Path, asof: date, remote_branch: str = PAGES_BRANCH) -> str:
    """Fast-forward, commit what changed and push; what it did, as a line for the log."""
    git(pages, "fetch", "origin")
    remote = f"origin/{remote_branch}"
    if git(pages, "rev-parse", "--verify", "--quiet", remote, check=False) == "0":
        git(pages, "merge", "--ff-only", remote)
    git(pages, "add", "-A")
    committed = git(pages, "diff", "--cached", "--quiet", check=False) == "1"
    if committed:
        git(pages, "commit", "-m", f"upload {asof.isoformat()}")
    has_remote = git(pages, "rev-parse", "--verify", "--quiet", remote, check=False) == "0"
    ahead = int(git(pages, "rev-list", "--count", f"{remote}..HEAD")) if has_remote else 1
    if not ahead:
        return f"{asof}: nothing to commit or push"
    git(pages, "push", "origin", f"HEAD:{remote_branch}")
    return f"{asof}: {'committed and ' if committed else ''}pushed {ahead} commit(s) to {remote_branch}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--asof", type=date.fromisoformat)
    ap.add_argument("--pages", type=Path, help="the gh-pages worktree (default: $CTD_OUTPUT_DIR)")
    ap.add_argument("--remote-branch", default=PAGES_BRANCH)
    ap.add_argument("--no-notify", action="store_true", help="no desktop alert on failure")
    args = ap.parse_args()
    asof, why = choose_asof(date.today(), args.asof)
    if asof is None:
        print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {why}: nothing to publish")
        return 0
    from ctd import cli
    from ctd.data import alert

    pages = args.pages or cli.output_dir()
    try:
        check_trees(REPO, pages)
        print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} {publish(pages, asof, args.remote_branch)}")
    except PublishError as e:
        print(f"{datetime.now():%Y-%m-%dT%H:%M:%S} publish {asof} failed: {e}")
        if not args.no_notify:
            alert.notify(f"ctd publish failed for {asof}", f"{str(e)[:200]}\nSee data\\morning.log")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
