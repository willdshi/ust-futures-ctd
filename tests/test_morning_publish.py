"""The morning run's choice of date and the publish step (roadmap 1f.3, 1f.7): D is the previous business
day, and publishing is a no-op when nothing changed, retries an unpushed commit, and never forces."""

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from morning_publish import PublishError, check_trees, git, publish  # noqa: E402
from morning_run import choose_asof  # noqa: E402

D = date(2026, 10, 28)


def test_asof_is_the_previous_business_day():
    assert choose_asof(date(2026, 11, 2)) == (date(2026, 10, 30), "")  # Monday: Friday
    assert choose_asof(date(2026, 11, 27)) == (date(2026, 11, 25), "")  # day after Thanksgiving: Wednesday
    assert choose_asof(date(2026, 11, 3), date(2026, 10, 28)) == (date(2026, 10, 28), "")  # --asof wins


def test_asof_skips_a_day_the_bond_market_was_closed():
    # Veterans Day 2026-11-11 (Wed): CME open, no TreasuryDirect prices. 11-12's D is Tuesday 11-10, not 11-11.
    assert choose_asof(date(2026, 11, 12)) == (date(2026, 11, 10), "")
    assert choose_asof(date(2026, 11, 13)) == (date(2026, 11, 12), "")
    # Columbus Day 2026-10-12 (Mon): Tuesday's D is the Friday before.
    assert choose_asof(date(2026, 10, 13)) == (date(2026, 10, 9), "")


def test_nothing_to_run_on_a_weekend_or_a_bond_market_holiday():
    asof, why = choose_asof(date(2026, 11, 1))  # Sunday
    assert asof is None and "isn't a cme business day" in why
    asof, why = choose_asof(date(2026, 11, 11))  # Veterans Day: final prices for D can't be out yet
    assert asof is None and "bond-market" in why
    asof, why = choose_asof(date(2026, 11, 12), date(2026, 11, 11))  # --asof on a holiday: no prices
    assert asof is None and "bond-market" in why


@pytest.fixture
def pages(tmp_path, monkeypatch):
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "t")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@example.com")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "gh-pages", str(origin)], check=True, capture_output=True)
    work = tmp_path / "pages"
    subprocess.run(["git", "clone", str(origin), str(work)], check=True, capture_output=True)
    git(work, "checkout", "-B", "gh-pages")
    (work / ".nojekyll").write_text("")
    git(work, "add", "-A")
    git(work, "commit", "-m", "start")
    git(work, "push", "origin", "gh-pages")
    return work, origin


def subjects(repo: Path) -> list[str]:
    return git(repo, "log", "--format=%s", "gh-pages").splitlines()


def test_publish_commits_pushes_and_a_rerun_has_nothing_to_do(pages):
    work, origin = pages
    (work / "2026-10-28.html").write_text("page")
    assert "committed and pushed 1 commit(s)" in publish(work, D)
    assert subjects(origin) == ["upload 2026-10-28", "start"]
    assert "nothing to commit or push" in publish(work, D)
    assert subjects(origin) == ["upload 2026-10-28", "start"]


def test_publish_pushes_an_earlier_commit_that_never_went_out(pages):
    work, origin = pages
    (work / "a.html").write_text("a")
    git(work, "add", "-A")
    git(work, "commit", "-m", "upload 2026-10-27")  # its push failed
    (work / "b.html").write_text("b")
    assert "pushed 2 commit(s)" in publish(work, D)
    assert subjects(origin) == ["upload 2026-10-28", "upload 2026-10-27", "start"]


def test_publish_fast_forwards_to_a_push_from_elsewhere(pages, tmp_path):
    work, origin = pages
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    (other / "manual.html").write_text("m")
    git(other, "add", "-A")
    git(other, "commit", "-m", "upload by hand")
    git(other, "push", "origin", "gh-pages")
    (work / "2026-10-28.html").write_text("page")
    publish(work, D)
    assert subjects(origin) == ["upload 2026-10-28", "upload by hand", "start"]


def test_publish_refuses_a_diverged_branch_instead_of_forcing(pages, tmp_path):
    work, origin = pages
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
    (other / "x.html").write_text("x")
    git(other, "add", "-A")
    git(other, "commit", "-m", "elsewhere")
    git(other, "push", "origin", "gh-pages")
    (work / "y.html").write_text("y")
    git(work, "add", "-A")
    git(work, "commit", "-m", "local only")
    with pytest.raises(PublishError):
        publish(work, D)
    assert subjects(origin) == ["elsewhere", "start"]


def test_trees_must_be_on_the_right_branches(pages, tmp_path):
    work, _ = pages
    code = tmp_path / "code"
    subprocess.run(["git", "init", "-b", "main", str(code)], check=True, capture_output=True)
    (code / "f").write_text("1")
    git(code, "add", "-A")
    git(code, "commit", "-m", "c")
    check_trees(code, work)
    (code / "f").write_text("2")
    with pytest.raises(PublishError, match="uncommitted"):
        check_trees(code, work)
    git(code, "checkout", "-q", "--", "f")
    git(code, "checkout", "-q", "-b", "dev")
    with pytest.raises(PublishError, match="not main"):
        check_trees(code, work)
    git(code, "checkout", "-q", "main")
    git(work, "checkout", "-q", "-b", "scratch")
    with pytest.raises(PublishError, match="not gh-pages"):
        check_trees(code, work)
