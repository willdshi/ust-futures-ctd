# Model versions: what must happen before V1 and V2 run side by side

*Working note, not a spec: the detail behind roadmap.md's V items. Once each item's content has moved into its owning doc (design.md, data.md, roadmap.md, open-questions.md), delete this file.*

## Context

The light model (design §5.11, plus the §5.9 outputs at β = 1 with ATM-normal probabilities) becomes **V1**. Phase 2 and later work (betas, realised vol, smile and so on) become V2, V3 and later versions, and each version's results must be computable over the same dates so they can be compared.

Decisions taken:
- **V1 is done after roadmap 1c.7** (tentatively). 1c.6 and 1c.7 are still V1 work.
- **V1 is a method, not a code snapshot.** A bug fix in shared code (pricing, envelope, DV01) flows into V1's re-runs. Each result records its code version, and a golden test shows what moved.
- **The report and the daily run stay on V1** until you decide how to publish a comparison. That decision goes in open-questions.md.

## What the code assumes today

- Results are already keyed by a model name, `data/results/light/<contract>/<date>.json` with `"model": "light"` ([report/results.py](src/ctd/report/results.py)). Everything else hardcodes `light`:
  - `light_path`, `write_light`, `read_light` and a single `SCHEMA = 11`;
  - `cli.cmd_run` and `cmd_history` call `light_inputs` → `light.run` → `light_record` ([cli.py:208-370](src/ctd/cli.py#L208-L370));
  - `page.contracts_on` globs `results/light`, `page.write` reads only light results, `check_schema` has one `MIN_SCHEMA`, and the `LIGHT_MODEL_LEDE` and `LIGHT_MODEL_SHIFT_AXIS` text describes β = 1 ([report/page.py:259-450](src/ctd/report/page.py#L259-L450), [report/charts.py:63](src/ctd/report/charts.py#L63));
  - `report/series.py` and `scripts/writeup_figures.py` read `results/light`.
- The shared pure code (`model/envelope`, `model/profile`, `model/horizon`, `risk/`, `vol/atm`) is called with parallel shifts built in. V2's betas change exactly these functions.
- **Naming clash:** design.md already uses "v1" for something else: "Non-goals (v1)" in §1 and "v1 uses a single ATM-based normal width" in §5.5. It also uses "light model" and "full model".
- No test pins the light model's real-data output. Tests use synthetic baskets, and tests can't read `/data/`.

## Prerequisites, in order

### 1. Settle the versioning rule in the docs (no code)
- design.md §4 (Results): results are keyed by **model version** (`v1`, `v2`, …). A version is a method. Each version has its own entry point, inputs and result schema. Shared code changes flow into every version that uses that code. Give the **Why**: comparison across versions over the same dates, and reproducibility through the recorded code version.
- State that v1 = §5.11 plus §5.9 at β = 1 with ATM normal. Rename design.md's existing "v1" uses (§1 non-goals, §5.5) so the word has one meaning. Grep the docs, code comments and docstrings for "v1", "light model" and "full model", and update references as CLAUDE.md requires.
- open-questions.md: add "How to publish V1 against V2" (run both and publish one, publish both, or keep the comparison offline).
- roadmap.md: add a short block of items for steps 2–5, with stable IDs, before Phase 2.

### 2. A version registry instead of hardcoded `light`
- Add a small registry: version → (input builder, `run`, record function, schema). V1's entry wraps the existing `cli.light_inputs`, `model.light.run` and `results.light_record` unchanged.
- [report/results.py](src/ctd/report/results.py): generalise `light_path`, `write_light` and `read_light` to take a version. Each version gets its own schema number. Move the store to `data/results/v1/...`; results are rebuilt from raw, so re-running `ctd history` repopulates it (or move the files once). Update data.md §… (the store layout line, `results/light/...`).
- CLI: add `--model` (default `v1`) to `run`, `history` and `report`. `page.contracts_on`, `page.write`, `check_schema`, `series` and `writeup_figures.py` take the version and default to `v1`.
- The `LIGHT_MODEL_*` report text becomes V1's text, selected by version. The report itself still publishes only V1.

### 3. V2 extends shared code; it doesn't edit V1's behaviour
- **Rule:** the varying piece is an argument with V1's value as the default. Examples: betas default to 1 in `envelope`, `switches` and `profile`; the vol width comes from a function that V1 passes as ATM-√T and later as total-variance. Don't copy modules per version.
- `model/light.py` stays V1's pipeline. V2 gets its own pipeline module, which reuses `at()`-style steps where they're unchanged.
- Inputs are per version. V2 will need par-curve history for betas, but provenance (`files` with sha256 and table) is built the same way. Factor the provenance helper out of `light_inputs` when V2's inputs are written, not before.

### 4. A V1 golden test (the guardrail for "fixes flow in")
- Save a small real extract under `tests/data/` for one date per contract (ZN, TN, ZB, UB; e.g. 2026-10-23). It holds the `LightInputs` fields as JSON/CSV: basket CFs, the basket's prices, futures, SOFR, SR1, the option chain for the one expiry, and the par curve.
- Save the expected key outputs: CTD, probabilities, crossovers, headline DV01, KRDs, horizon, width. Assert them with tight tolerances.
- When a shared-code fix moves V1, the commit updates the golden file, and the diff shows the size of the change. Add it to design §8.

### 5. Daily run built for more than one version (1f.3)
- When `scripts/morning_run.py` is written, it takes the list of versions to run from one place (default `[v1]`). Adding V2 later is a one-line change, and the report stays V1 until the open question is settled.

### 6. Comparison: keep it possible, defer building it
- Every version's results share the keys (contract, asof) and the units of the headline fields (`dv01`, `krd`, `ctd`, probabilities). Comparing two versions is then a join over saved results. The comparison tool or page waits for the open question.

## What doesn't need to happen first
- Git tags per version. Optional: tag the commit that completes V1 (`v1.0`) as a reference point. Versions run side by side from one checkout, so tags aren't the mechanism.
- Any change to the raw or derived stores. Versions differ only in model code and results.

## Critical files
- [src/ctd/report/results.py](src/ctd/report/results.py), [src/ctd/cli.py](src/ctd/cli.py), [src/ctd/report/page.py](src/ctd/report/page.py), [src/ctd/report/series.py](src/ctd/report/series.py), [src/ctd/report/charts.py](src/ctd/report/charts.py), [scripts/writeup_figures.py](scripts/writeup_figures.py)
- [src/ctd/model/light.py](src/ctd/model/light.py) (stays as V1), plus `model/envelope.py`, `model/profile.py` and `vol/atm.py` (given default arguments when V2 needs them)
- Docs: design.md §1, §4, §5.5, §8; data.md (results layout); roadmap.md; open-questions.md
- New: the registry module, `tests/data/v1_golden/…`, `tests/test_v1_golden.py`

## Verification
- `& $py -m pytest`: all pass, including the new golden test.
- Re-run `ctd history --model v1` over the December contracts from 2026-09-01. Compare each new `results/v1` JSON with the old `results/light` JSON, ignoring `run_at`, `code` and `model`. They should match exactly.
- `ctd report` for 2026-10-26 gives the same pages as before.
- Change a shared default deliberately in a scratch branch, and check that the golden test fails with a readable diff.
