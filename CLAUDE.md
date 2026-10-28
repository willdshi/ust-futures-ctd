# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

End-of-day model of cheapest-to-deliver (CTD) probabilities, futures DV01s and key rate DV01s for CBOT Treasury futures, built from public data plus a small paid Databento feed for CME settlements. The model covers **ZN, TN, ZB and UB**, all four on an equal footing; ZT and ZF are collected but not modelled.

## Docs: where things live

Read the relevant doc before changing the code it covers.

| Doc | Holds | Read before |
|---|---|---|
| [docs/design.md](docs/design.md) | The spec: how the model works, and every settled design choice with its reasons | any change in `bonds/`, `funding/`, `curve/`, `vol/`, `model/`, `risk/` |
| [docs/roadmap.md](docs/roadmap.md) | Phases and status, as checkboxes | starting or finishing a task |
| [docs/open-questions.md](docs/open-questions.md) | Open questions, with options and evidence where worked through | proposing a change in an area it lists |
| [docs/data.md](docs/data.md) | Sources, raw store, derived tables, data quirks, scheduled tasks, and the settled data choices | any change in `data/` or the scheduled tasks |
| [docs/outputs.md](docs/outputs.md) | What is published and how it looks; `[NI]` marks what isn't implemented | any change in `report/` |

[docs/writeup.md](docs/writeup.md) (built to `writeup.pdf`) is the reader-facing write-up: the project's scope, intent and limitations, with results for one date. It isn't a spec and lags the docs above by design. Don't consult or edit it while implementing; where they disagree, the docs above win. It is reconciled at milestones (roadmap.md, W), from the diff of the other docs since the commit recorded in its header.

### Writing docs

- One home per fact (table above). Elsewhere, link to it; don't restate it.
- Update existing text in place. Don't add a new paragraph next to an old one it contradicts.
- A settled choice goes in the section it governs (design.md for the model, data.md for data, outputs.md for publishing): the rule, then **Why** (the deciding evidence, a few sentences) and, where useful, **Rejected** (alternatives and why they lost). If it came from open-questions.md, delete that entry in the same commit.
- An open question goes in open-questions.md.
- Progress goes in roadmap.md, one line per item, ticked in the commit that finishes it.
- No dated status ("now", "so far", "until …") or history of the code or docs: git has it. Exception: in data.md, which source covers which dates is part of the data.
- Run results go in only as evidence: the **Why** behind a rule, a validation result (design §8), a data quirk (data.md), or an example that sizes a published caveat (outputs.md). Give the dates they cover. Example output numbers with no such role stay out.
- When unsure whether to drop something, keep it and move it to its owning doc.
- A published output not yet built is marked `[NI]` in outputs.md.
- When moving or renaming a section, grep the repo (docs, code comments, docstrings) for references to it and update them.

## Environment and commands

The conda env is `ctd` (Python 3.13). `conda` is not on PATH in the agent shells, so call the env's interpreter directly:

```powershell
$py = "$env:USERPROFILE\miniconda3\envs\ctd\python.exe"
& $py -m pytest                                  # all tests (config in pyproject.toml)
& $py -m pytest tests/test_imports.py::test_subpackage_imports -q   # a single test
& $py -m pytest -m "not network and not slow"    # skip tests that download data or take long
& $py -m pip install -e . --no-deps              # editable install (conda manages the deps)
```

- To refresh `environment.yml`, run `conda env export -n ctd --from-history` (conda is at `%USERPROFILE%\miniconda3\Scripts\conda.exe`). Then remove the `prefix:` line and save the file as UTF-8. A PowerShell `>` redirect writes UTF-16.
  - `--from-history` omits pip installs. Keep the `pip:` section by hand; the top-level pip installs are `databento` and `QuantLib`. `conda list -n ctd` also labels scipy and pyarrow `pypi`, wrongly: they are conda-forge packages whose file records conda fails to match.
  - It also prints `channels: defaults` (conda's configuration), but every conda package comes from conda-forge. Keep `conda-forge` and `nodefaults` by hand, and the `libblas=*=*openblas` pin: MKL 2026.1's default threading layer crashes on numpy matrix products in this env.
- Keep dependencies in sync in both `environment.yml` and `pyproject.toml`. Test-only packages (QuantLib) go in the `dev` extras.
- pytest runs with `--strict-markers`, so register any new marker in `pyproject.toml`. Mark tests that touch external sources with `network`.
- No linter or formatter is configured yet.

## Architecture rules

- **Two `data` directories.** `src/ctd/data/` is code (one module per source); `/data/` at the repo root is the gitignored store (raw files, derived tables, results). Keep `.gitignore` anchored as `/data/*`.
- **Purity.** `bonds/`, `funding/`, `model/`, `risk/` and the computational parts of `curve/` and `vol/` are pure functions. Only `data/` and `report/` do I/O; `cli.py` connects them (`ctd fetch`, `derive`, `run`, `history`, `report`).
- **The model reads only the store**, never the network. `ctd run` reads the derived tables by default; `ctd derive` builds them incrementally and must give the same tables as `--full`.
- **Reproducibility.** A run for date D uses data dated on or before D from any stored file (so D's SOFR comes from D+1's file). Re-running D gives the same answer once D+1's files are stored (design §3.3).
- **Raw files are stored exactly as downloaded and never overwritten.** One exception: a provisional same-evening TreasuryDirect price file is replaced once end-of-day prices are published (`SourceSpec.provisional`; data.md §5.1). Never extend it to other sources.
- **Collect broadly, model narrowly.** Don't narrow a fetcher to the products the model reads. Gaps are flagged in the manifest, never filled from another source (design §3.2). CME futures and option settlements come from the daily Databento pull (data.md §5.14); the bookmarklet's CME pages and bulletin are an optional cross-check, and the only source of SR3 and ZQ.
- **Bond math is hand-written (design §5.1).** One street-convention pricing function (`ctd.bonds.pricing`) is used for every price, yield and duration calculation. QuantLib is a test-only dependency, used as an independent check.
  - Coupons and yields are decimals (0.045); prices are per 100 face. The price functions accept a numpy array of yields.
  - Coupon dates are stepped back from maturity (month-end maturities pay month-end). Treasuries are dated on schedule, so there is no odd-first-coupon logic. A bond in its final coupon period raises rather than being priced (street convention's simple-interest period isn't implemented).
- **Dates are passed in, never assumed.** Settlement (T+1), delivery and as-of dates are always arguments.
- **Reference data is data, not code (design §2).** Grades, option products and holidays are records in `src/ctd/reference/data/` (grades with effective-from dates), never constants; verify each against the CBOT rulebook when encoding it. Delivery calendars and option expiries are computed from the CBOT rules on the holiday list (`refdata.delivery_dates`, `refdata.option_expiry`); a date CME sets against a rule goes in `rule_exceptions.toml`, never in code.

## Guardrails

- **Delivery dates come only from `ctd.model.horizon`.** Never compute a horizon or implied delivery date anywhere else (design §5.2).
- **Out of scope, don't build:** a model futures price or fair value, implied or CTD-specific repo, the end-of-month and wildcard options (design §1). Market futures prices are used only for vol conversion, open interest and the report's futures duration.
- **Negative short-tenor KRDs, and effective maturity beyond a bond's maturity, are correct** for low-coupon bonds against the par curve. Don't "fix" them (design §5.9).
- **Implement a model piece from its design section**, and add its test from design §8.

## Tests

- Required tests are listed in design §8; add the matching test with new model code.
- Tests never read the gitignored `/data/` store. When a test needs real files, save a small extract under `tests/data/` (e.g. `tcf_2026-10-21.csv`).
