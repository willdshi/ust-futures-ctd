# Roadmap

What's built and what's next. One line per item, ticked in the commit that finishes it. How each piece works is in [design.md](design.md); open questions are in [open-questions.md](open-questions.md).

**Item IDs are stable.** Refer to items by ID (e.g. `1e.5`). Never renumber: a new item takes the next free number in its phase, and a dropped item stays, struck through, with the reason.

**First milestone:** Tier 1 outputs ([outputs.md](outputs.md)) for ZN, TN, ZB and UB, plus the December/March roll comparison, before the December options expire on 2026-11-20.

## Phase 1: deterministic core

- [x] **1.1** Daily collection of every source in design §3.2, with manifests and gap alerts ([data.md](data.md))
- [x] **1.2** Reference data for ZN, TN, ZB and UB: grades, delivery calendars, option products

## Phase 1b: light model (design §5.11)

*A. Foundation*
- [x] **1b.A1** Dates and conventions: coupon schedule, accrued, T+1 settlement (`bonds/schedule.py`)
- [x] **1b.A2** The single pricing function (`bonds/pricing.py`, design §5.1)
- [x] **1b.A3** CF formula, matching every stored TCF row (`bonds/conversionfactor.py`)
- [x] **1b.A4** Store readers: TreasuryDirect prices, TCF baskets, CME futures, NY Fed SOFR
- [x] **1b.A5** Delivery calendars per contract month (`reference/data/delivery_calendar.toml`; Z6 and H7)
- [x] **1b.A6** Term repo, forward prices and the delivery-date rule (`funding/repo.py`, `bonds/forward.py`, `model/horizon.py`)
- [x] **1b.A7** Envelope and switch points (`model/envelope.py`)

*B. Light-model pieces*
- [x] **1b.B1** Option reference data, NOV26 to JUN27 (`reference/options.py`, `option_expiries.toml`)
- [x] **1b.B2** Section 42 parser, TN included (`cme_bulletin.parse_options`)
- [x] **1b.B3** Digitals (`vol/digitals.py`)
- [x] **1b.B4** Probability assembly (`model/probabilities.py`)
- [x] **1b.B5** `ctd run` output and saved results (`model/light.py`, `report/light.py`, `report/results.py`)
- [x] **1b.B6** Series for the four December contracts from 2026-09-01
- [x] **1b.B7** Morning SOFR fetch (`scripts/morning_sofr.py`)

*C. Definition of done*
- [x] **1b.C** Design §8 tests for these pieces, the flat-6% sanity check, reproducible results

*D. Open questions:* settled ones are in design.md (§5.11 shifts forward yields; §4 saved results; §5.1 TreasuryDirect snapshot; §7 roll at option expiry). The recentring-gap tolerance is in open-questions.md.

## Phase 1c: single-date outputs (Tier 1 for one date)

- [x] **1c.1** Futures DV01, probability-weighted and CTD-based (`risk/dv01.py`)
- [x] **1c.2** Par curve, bond KRDs, cluster KRDs and effective maturity (`curve/par.py`, `risk/krd.py`)
- [x] **1c.3** ATM vol and distance to switch (`vol/atm.py`)
- [x] **1c.4** Shifted-state profile: region-weighted DV01 and KRDs, ±1σ/±2σ, vol ±10% bands (`model/profile.py`)
- [x] **1c.5** Charts and report pages (`report/`, `ctd report`)
- [ ] **1c.6** March contracts (ZNH7, TNH7, ZBH7, UBH7) through 1c.1–1c.5, and the December/March roll comparison
- [ ] **1c.7** Total-variance vol interpolation with the January serial as second expiry (design §5.5 step 3; √T stays as fallback)
- [x] **1c.8** Repo from the SR1 strip (`funding/strip.py`, design §5.3)

## Phase 1d: historical trial (2026-09-01 on)

- [x] **1d.1** Inputs from the derived tables (`cli.light_inputs`, readers in `data/derived/`)
- [x] **1d.2** Derived inputs reproduce the raw-page results on the overlap dates
- [x] **1d.3** Provenance: results list the raw files behind every derived input
- [x] **1d.4** `ctd history` over a date range
- [x] **1d.5** Review of the series (conclusions are in design §3.1, §5.1, §5.2, §8 and §9)
- [x] **1d.6** First time-series view: chart 3 in the report

## Phase 1e: daily CME collection from Databento (data.md §5.14)

- [x] **1e.1** Fetcher and source `databento_daily`
- [x] **1e.2** Option definitions for new instruments only
- [x] **1e.3** Readers `read_daily_futures`, `read_daily_options`
- [x] **1e.4** Derived tables take `databento_daily` from 2026-10-26
- [ ] **1e.5** Morning task `ctd-morning` (fetch with Databento, SOFR, derive, in order; data.md §4) collects and derives cleanly on a first morning
- [x] **1e.6** Runs read the derived tables by default (`--inputs raw` kept as a cross-check)
- [ ] ~~**1e.7** Two weeks alongside the bookmarklet before making Databento the record~~ Dropped: Databento is the production source; the bookmarklet is an optional cross-check.
- [ ] **1e.8** Buy `databento_daily` for 2026-10-20 to 10-23 (about $1), closing the bulletin-only stretch in the options table

## Phase 1f: automated daily run

- [ ] **1f.1** Run-window rule in code: `contracts_on(asof, expiries, products)` in `reference/`, modelled products marked in `cme_products.toml`; `ctd history` and `ctd report` default to it (design §7)
- [ ] **1f.2** Fill the December series from 2026-08-14 to 08-31: the saved series starts 2026-09-01, run under the earlier start rule (needs SEP26 option records, or `--contract`)
- [ ] **1f.3** `scripts/morning_run.py [--asof D]`: the day's contracts, `ctd history`, then `ctd report`; alert and non-zero exit on any failure
- [ ] **1f.4** Chain it to the morning derive: a fourth step in `scripts/morning.py`, run only when the derive step exits 0, logging to `data/morning.log`
- [ ] **1f.5** Reference data ahead of each roll (June 2027 calendars by 2027-02-12), with a warning 30 days before a missing record is needed
- [ ] **1f.6** Robustness: wake timers, a logon trigger, `--catch-up` over 10 business days, tasks run from a `main` worktree (data.md §4)
- [ ] **1f.7** Later, opt-in: publishing to GitHub Pages

## R: Report

- [x] **R.1** Chart 3's ±1σ band in the interactive chart
- [ ] **R.2** Interactive chart 3: mark the band's +1σ and −1σ edges distinctly, as the PNG's two lines do (▲ and ▽)
- [x] **R.3** Constant-CTD DV01 line on chart 3
- [ ] **R.4** The other `[NI]` items in [outputs.md](outputs.md)

## W: Writeup

[writeup.md](writeup.md) lags the other docs between milestones. To reconcile it: check its claims and limitations against the diff of the other docs since the commit in its header (`git diff <commit>..HEAD -- docs ':!docs/writeup.*' ':!docs/images'`); where the model changed, re-run the quoted date and regenerate the figures (`scripts/writeup_figures.py`); rebuild the PDF; record the new commit in its header.

- [x] **W.1** Reconcile with the restructured docs
- [ ] **W.2** Reconcile at the first milestone

## Phase 2: one-factor model

- [x] **2.1** Derived tables: futures, options, options quality, bond prices, securities, par curve, rates, baskets (data.md §9)
- [ ] **2.2** Betas, re-estimated daily (design §5.4); then replace the report's β = 1 wording (`LIGHT_MODEL_*` in `report/`)
- [ ] **2.3** Realised-vol fallback and comparison
- [ ] **2.4** Constant-CTD effective maturity, from the saved results (design §5.9)
- [ ] **2.5** Event flags: roll and re-estimation (basket and CTD changes are marked)
- [ ] **2.6** Product series that roll at option expiry (design §7)
- [ ] **2.7** The December contract after its options expire (vol from the next expiry; open-questions.md)

## Phase 3: refinements

- [ ] **3.1** Beta adjustment for the next contract's CTD in the vol interpolation
- [ ] **3.2** Smile-implied distribution (design §5.5.1) with the quantile grid window (§5.6)
- [ ] **3.3** Slope adjustment by convolution (§5.7)
- [ ] **3.4** Digital and ATM-normal diagnostics
- [ ] **3.5** Full horizon logic: run both dates when carry is near zero (§5.2)
- [ ] **3.6** Stepped repo (§5.3): FOMC calendar and year-end turn

## Phase 4: history and extensions

- [ ] **4.1** Long history (design §7): reference data for every past contract month, the roll, baskets from the derived table before 2023-12-11, repo before May 2018
- [ ] **4.2** Repo before May 2018 from ZQ, if chosen (open-questions.md)
- [ ] **4.3** Backtest scoring and reliability plot (design §8)
- [ ] **4.4** Tier 2 outputs and the fragility dashboard, with their new sources
- [ ] **4.5** Two- or three-factor PCA simulation with idiosyncratic noise
- [ ] **4.6** ZT and ZF, if wanted
