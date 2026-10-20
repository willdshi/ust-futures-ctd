# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

End-of-day model of cheapest-to-deliver (CTD) probabilities, futures fair value and key rate DV01s for CBOT Treasury futures, built only from free public data. The model focuses on **ZN, ZB and UB** (ZN and ZB first, then UB), but data collection covers six Treasury contracts: ZT, ZF, ZN, TN, ZB and UB. **[docs/design.md](docs/design.md) is the spec.** Read the relevant section before implementing anything; the phase roadmap is in section 10 and the open decisions are in section 11.

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
- **Collect broadly, model narrowly (§3.2).** Data that can't be backfilled for free gets lost on any day it isn't pulled.
  - Collect it every business day for all products in §3.2, whether the model uses them yet or not:
    - CME futures settlements for all six contracts, and their option settlements as the Daily Bulletin's Section 42 PDF (browser bookmarklet; cmegroup.com blocks scripts)
    - CME conversion factor tables (TCF, from CME's public FTP server)
    - SOFR and fed funds futures
    - the full TreasuryDirect price file
  - Never narrow a fetcher to the products the model currently reads.
  - Fetches are idempotent and never overwrite a stored file.
  - Each date gets a manifest, and gaps are flagged, never filled from another source.
- **Purity.**
  - `bonds/`, `funding/`, `model/` and `risk/` (and the computational parts of `curve/` and `vol/`) are pure functions.
  - Only `data/` and `report/` do I/O.
  - `cli.py` connects them:
    - `ctd fetch --asof 2026-10-16`
    - `ctd run --contract ZBZ6 --asof 2026-10-16`
    - `ctd history --contract ZB --from 2022-01-01 --to 2026-10-16`
- **Bond math is hand-written (§5.1).** One street-convention pricing function is used for every price, yield and duration calculation. QuantLib is a test-only dependency, used as an independent check.
- **Explicit conventions.** Settlement (T+1) and delivery dates are always passed in, never assumed. Accrual is actual/actual, compounding is semiannual, and days are business days for delivery calendars.
- **Reference data is data, not code (§2).**
  - Contract grades, delivery calendars and option products live in `reference/` as records with effective-from dates, never as constants. Verify each against the current CBOT rulebook when encoding it.
  - Conversion factors come from the 6% CF formula (maturity rounded down to the quarter for ZN, ZB and UB) in both live and historical mode. CME's published tables (TCF, collected daily from its FTP server, §3.2) are validation data, and the formula is tested against them.
  - Baskets are rebuilt from the eligibility rules and Treasury security terms, and checked against the TCF files.
  - Store delivery calendars per contract month; don't compute them ad hoc.
  - Basket eligibility, measured from the first day of the delivery month:
    - ZN is 6.5 to 10y (original maturity ≤ 10y)
    - ZB is 15 to under 25y
    - UB is 25y and over
  - A bond moves from UB's basket to ZB's when it drops below 25y, so baskets are dated per contract.

## Model invariants that are easy to get wrong

- **Horizon.** Pick one horizon for the whole basket, not one per bond: last delivery day if carry is positive, first delivery day if negative (§5.2).
- **Exact cash flows.** Coupons between today and the horizon must be in the forward price, and accrued must be at the correct settlement and delivery dates (§5.1).
- **Grid centring.** Centre everything on forward yields at the horizon, with a per-bond convexity adjustment `c_i` so that `E[P_i(z)]` equals the forward price (§5.6).
- **Slope-adjusted widths.** The slope-adjusted width `S_eff` is used for **probabilities only**, never for futures price or DV01 (§5.7).
- **Vol mapping.** Convert each option expiry's price vol with the CTD duration of *that expiry's* underlying contract, then interpolate total variance to the horizon (§5.5). If UB options are too thin, map vol from ZB through betas, then fall back to realised vol (§3.1).
- **Implied CTD repo.** It's a fitted calibration parameter that absorbs all residual error. Don't treat it as an observed input (§5.8).
- **Key rate durations.** KRDs are forward KRDs at the horizon, divided by CF and probability-weighted. Also report them per cluster, for jump risk (§5.9).
- **Wildcard option.** It isn't priced and is left in the model-to-market residual.

## Validation targets (§8)

Required unit tests:
- accrued interest
- price/yield round trips to 1e-10 with the single pricing function
- CF formula vs the CME table for ZN, ZB and UB
- delivery calendars, and option expiry dates vs CME's published calendar
- a bond crossing the 25-year ZB/UB boundary between contract months
- forward price vs a hand carry calculation, including a coupon between today and delivery
- settlement on a coupon date; end-of-month maturities
- crossover root-finding on a synthetic two-bond basket with a known answer
- term repo compounding

Sanity check: on a flat 6% curve, all converted prices should be about 100.
