# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

End-of-day model of cheapest-to-deliver (CTD) probabilities, futures DV01s and key rate DV01s for CBOT Treasury futures, built only from free public data. The model covers **ZN and ZB first** (the contracts prone to switching), then **UB and TN** as stable-duration comparisons. Data collection covers six Treasury contracts: ZT, ZF, ZN, TN, ZB and UB. **[docs/design.md](docs/design.md) is the spec.** Read the relevant section before implementing anything; the phase roadmap is in section 10 and the open decisions are in section 11. What gets published (charts, tiers, conventions) is in [docs/outputs.md](docs/outputs.md); collected data is described in [docs/data.md](docs/data.md) and settled choices in [docs/decisions.md](docs/decisions.md).

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
  - `--from-history` omits pip installs. Keep the `pip:` section by hand; `conda list -n ctd` marks them with channel `pypi` (top-level ones now: `databento`, `QuantLib`).
- Keep dependencies in sync in both `environment.yml` and `pyproject.toml`. Test-only packages (QuantLib) go in the `dev` extras.
- pytest runs with `--strict-markers`, so register any new marker in `pyproject.toml`. Mark tests that touch external sources with `network`.
- No linter or formatter is configured yet.
- Tests never read the gitignored `/data/` store. When a test needs real files, save a small extract under `tests/data/` (e.g. `tcf_2026-10-21.csv`).

## Current state

Phase 1b (the light model, design §5.11) is in progress. Status is tracked as checkboxes in the phase 1b plan in design §10; tick items there in the commit that finishes them, not here.

## Architecture rules (from the design)

- **Two different `data` directories.**
  - `src/ctd/data/` is code: one fetcher module per source.
  - `/data/` at the repo root is the gitignored raw snapshot store.
  - Keep `.gitignore` anchored as `/data/*`.
- **Reproducibility.** Store every raw file exactly as downloaded, keyed by as-of date. TreasuryDirect prices and CME settlements under an as-of date are that day's close (checked by hand for TreasuryDirect; data.md §5.1), but rates published the next morning (SOFR) aren't in that day's files yet. The model reads only from that store, never from the network directly, and re-running a past date must give the same answer.
- **Collect broadly, model narrowly (§3.2).** Data that can't be backfilled for free gets lost on any day it isn't pulled.
  - Collect it every business day for all products in §3.2, whether the model uses them yet or not:
    - CME futures settlements for all six contracts, and their option settlements as the Daily Bulletin's Section 42 PDF (browser bookmarklet; cmegroup.com blocks scripts)
    - CME conversion factor tables (TCF, from CME's public FTP server)
    - SOFR and fed funds futures
    - Yahoo Finance daily bars for the six Treasury futures (cross-check on CME settlements)
    - the full TreasuryDirect price file
  - Never narrow a fetcher to the products the model currently reads.
  - Fetches are idempotent and never overwrite a stored file.
    - **One exception:** a same-evening TreasuryDirect price file (no end-of-day prices yet) is provisional and replaced by the completed file on a later run (`SourceSpec.provisional`, `RawStore.replace`; data.md §5.1). Only sources that can be pulled again for any past date may use it. Never extend it to CME data.
  - Each date gets a manifest, and gaps are flagged (the scheduled `ctd fetch --catch-up --notify` raises a desktop alert), never filled from another source.
- **Purity.**
  - `bonds/`, `funding/`, `model/` and `risk/` (and the computational parts of `curve/` and `vol/`) are pure functions.
  - Only `data/` and `report/` do I/O.
  - `cli.py` connects them:
    - `ctd fetch --asof 2026-10-16`
    - `ctd run --contract ZBZ6 --asof 2026-10-16`
    - `ctd derive` (derived Parquet tables under `/data/derived/`, design §4; incremental, and must equal `--full`)
    - `ctd history --contract ZB --from 2022-01-01 --to 2026-10-16`
- **Bond math is hand-written (§5.1).** One street-convention pricing function (`ctd.bonds.pricing`) is used for every price, yield and duration calculation. QuantLib is a test-only dependency, used as an independent check.
  - Coupons and yields are decimals (0.045); prices are per 100 face. The price functions accept a numpy array of yields.
  - Coupon dates are stepped back from maturity (month-end maturities pay month-end). Treasuries are dated on schedule, so there is no odd-first-coupon logic. A bond in its final coupon period raises rather than being priced (street convention's simple-interest period isn't implemented).
- **Explicit conventions.** Settlement (T+1) and delivery dates are always passed in, never assumed. Accrual is actual/actual, compounding is semiannual, and days are business days for delivery calendars.
- **Reference data is data, not code (§2).**
  - Contract grades, delivery calendars and option products live in `reference/` as records with effective-from dates, never as constants. Verify each against the current CBOT rulebook when encoding it.
  - Conversion factors come from the 6% CF formula (`ctd.bonds.conversionfactor`; maturity rounded down to the quarter for ZN, TN, ZB and UB, the month for ZT and ZF, as `cf_round_months` in `cme_products.toml`) in both live and historical mode. CME's published tables (TCF, collected daily from its FTP server, §3.2) are validation data; the formula matches every stored TCF row. The light model (§5.11) reads CFs from TCF as a shortcut.
  - Baskets are rebuilt from the eligibility rules and Treasury security terms, and checked against the TCF files.
  - Store delivery calendars per contract month; don't compute them ad hoc.
  - Basket eligibility, measured from the first day of the delivery month:
    - ZN is 6.5 to 8y (original maturity ≤ 10y) from the September 2023 contract month; 6.5 to 10y before. Historical rebuilds must use the grade in force for each contract month (records in `src/ctd/reference/data/contract_grades.toml`, looked up with `ctd.reference.grades.grade_for`)
    - TN is 9y 5m to 10y (original maturity ≤ 10y)
    - ZB is 15 to under 25y
    - UB is 25y and over
    - Original-term limits apply per tranche: a 7-year note reopened as a 5-year counts as a 5-year for ZT and ZF from that reopening (CME's TCF lists it). Remaining-term limits are inclusive except ZB's "under 25y"; ZT's maximum (2y) runs from the last day of the delivery month.
  - A bond moves from UB's basket to ZB's when it drops below 25y, so baskets are dated per contract.

## Model invariants that are easy to get wrong

- **Horizon.** Pick one horizon for the whole basket, not one per bond: last delivery day if carry is positive, first delivery day if negative (§5.2).
- **Exact cash flows.** Coupons between today and the horizon must be in the forward price, and accrued must be at the correct settlement and delivery dates (§5.1).
- **Grid centring.** Centre everything on forward yields at the horizon. The per-bond convexity adjustment `c_i` (so that `E[P_i(z)]` equals the forward price) is optional and off by default in v1; add it only if backtests show a bias (§5.6).
- **Slope-adjusted widths.** The slope-adjusted width `S_eff` is used for **probabilities only**, never for DV01 or KRDs (§5.7).
- **Vol mapping.** Convert each option expiry's price vol with the CTD duration of *that expiry's* underlying contract, then interpolate total variance to the horizon (§5.5). Use quarterly and serial options only; weeklies are stored in the bulletin but not used (§2). If UB options are too thin, map vol from ZB through betas (TN from ZN), then fall back to realised vol (§3.1).
- **No fair value (§1, §5.8).** There is no model futures price, no comparison with the market settlement and no implied CTD repo. The end-of-month and wildcard options aren't modelled. Every bond is funded at GC. Market futures prices are used only for vol conversion and open interest.
- **Key rate durations.** KRDs are forward KRDs at the horizon, divided by CF and probability-weighted. Also report them per cluster, for jump risk (§5.9). The key-rate grid is fixed at 2, 5, 7, 10, 15, 20, 25 and 30 years: tent bumps to the linearly interpolated Treasury par curve, each bond's shares scaled to its DV01 from `ctd.bonds.pricing` ([decisions.md](docs/decisions.md)). Short-tenor KRDs of low-coupon bonds are negative by design; units are $/bp per $100mm notional.
- **Scenarios.** Recompute crossovers and probabilities at each shifted state (±1σ, ±2σ, the duration profile). Never read off the CTD at the shifted yield (§5.9).

## Validation targets (§8)

Required unit tests:
- accrued interest
- price/yield round trips to 1e-10 with the single pricing function
- CF formula vs the CME table for ZN, TN, ZB and UB
- delivery calendars, and option expiry dates vs CME's published calendar
- a bond crossing the 25-year ZB/UB boundary between contract months
- a note crossing the ZN grade change: 91282CFV8 (4⅛% Nov 2032) is deliverable for June 2023 (6.5–10y) but not September 2023 (6.5–8y)
- forward price vs a hand carry calculation, including a coupon between today and delivery
- settlement on a coupon date; end-of-month maturities
- crossover root-finding on a synthetic two-bond basket with a known answer
- term repo compounding
- region-weighted DV01 vs finite difference on a synthetic basket

Sanity check: on a flat 6% curve, all converted prices should be about 100.
