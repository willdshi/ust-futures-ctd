# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

End-of-day model of cheapest-to-deliver (CTD) probabilities, futures fair value and key rate DV01s for CBOT Treasury futures (ZB and ZN first), built only from free public data. **[docs/design.md](docs/design.md) is the spec.** Read the relevant section before implementing anything; the phase roadmap is in section 9 and the open decisions are in section 10.

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
- Keep dependencies in sync in both `environment.yml` and `pyproject.toml`.
- pytest runs with `--strict-markers`, so register any new marker in `pyproject.toml`. Mark tests that touch external sources with `network`.
- No linter or formatter is configured yet.

## Architecture rules (from the design)

- **Two different `data` directories.**
  - `src/ctd/data/` is code: one fetcher module per source.
  - `/data/` at the repo root is the gitignored raw snapshot store.
  - Keep `.gitignore` anchored as `/data/*`.
- **Reproducibility.** Store every raw file exactly as downloaded, keyed by as-of date. The model reads only from that store, never from the network directly, and re-running a past date must give the same answer.
- **Purity.**
  - `bonds/`, `model/` and `risk/` (and the computational parts of `curve/` and `vol/`) are pure functions.
  - Only `data/` and `report/` do I/O.
  - `cli.py` connects them: `ctd run --contract ZBZ6 --asof 2026-10-16`.
- **Explicit conventions.** Settlement and delivery dates are always passed in, never assumed. Accrual is actual/actual, compounding is semiannual, and days are business days for delivery calendars.
- **Reference data comes from CME, not code.**
  - Conversion factors come from CME's published tables. Implement the 6% CF formula only as a cross-check.
  - Store delivery calendars per contract month; don't compute them ad hoc.
  - Basket eligibility rules: ZN is 6.5 to 10y and ZB is 15 to under 25y, measured from the first day of the delivery month.

## Model invariants that are easy to get wrong

- **Horizon.** Pick one horizon for the whole basket, not one per bond: last delivery day if carry is positive, first delivery day if negative (§5.1).
- **Grid centring.** Centre everything on forward yields at the horizon, with a per-bond convexity adjustment `c_i` so that `E[P_i(z)]` equals the forward price (§5.5).
- **Slope-adjusted widths.** The slope-adjusted width `S_eff` is used for **probabilities only**, never for futures price or DV01 (§5.7).
- **Implied CTD repo.** It's a fitted calibration parameter that absorbs all residual error. Don't treat it as an observed input (§5.8).
- **Key rate durations.** KRDs are forward KRDs at the horizon, divided by CF and probability-weighted. Also report them per cluster, for jump risk (§5.9).
- **Wildcard option.** It isn't priced and is left in the model-to-market residual.

## Validation targets (§7)

Required unit tests:
- accrued interest
- price/yield round trips
- CF formula vs the CME table
- forward price vs a hand carry calculation
- crossover root-finding on a synthetic two-bond basket with a known answer

Sanity check: on a flat 6% curve, all converted prices should be about 100.
