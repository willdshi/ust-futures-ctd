# CTD Model: Design

End-of-day model of cheapest-to-deliver (CTD) probabilities and futures key rate durations for CBOT Treasury futures, built from free public data. Includes a historical mode for building a time series of CTD probabilities and futures durations. What gets published, and how it's charted, is specified in [outputs.md](outputs.md).

## 1. Purpose, goals and non-goals

### Purpose
A **duration-drift monitor for Treasury futures users**: how stable is the duration held through futures, what would change it, and when. Output **probability-weighted futures DV01 and KRDs** as a daily time series, a **duration profile** across factor shifts (with ±1σ and ±2σ as points on it), and the distance to the next CTD switch. CTD probabilities are the engine, published as a supporting series rather than the headline.

The audience is a broad rates audience and asset managers who use futures as duration substitutes or overlays. Basis traders are not the audience; they have better tools. Market impact is context, not the headline: a CTD switch transfers duration between longs and shorts rather than creating it ([outputs.md](outputs.md), Positioning).

### Goals
- Contracts: **ZN and ZB first**, because they are prone to switching (section 2). Then **UB and TN**, mainly as stable-duration comparisons. Build and validate on ZN and ZB first. The model code is contract-agnostic, so other contracts can be added later through reference data alone.
- For a given contract, estimate each deliverable bond's probability of being CTD at delivery.
- Locate the **crossover levels** (factor shifts at which the CTD changes hands) and group bonds into clusters with similar key rate profiles.
- Produce futures **DV01 and key rate DV01s**, both probability-weighted and per cluster.
- Produce a **duration profile** (DV01 and KRDs across factor shifts, ±1σ and ±2σ marked), recomputing probabilities at each shifted state (5.9).
- Produce the **comparison series** asset managers need: CTD-based DV01 (what vendor systems report, which jumps when the CTD changes) and constant-CTD DV01, plus DV01-weighted effective maturity (section 6).
- Run daily from end-of-day data, reproducibly, with every input snapshot stored.
- Build a **history** of CTD probabilities and futures durations from free historical data (section 7).
- **First milestone:** Tier 1 outputs for ZN and ZB, plus the December/March roll comparison, ready before the late-November 2026 roll (section 10).

### Non-goals (v1)
- **Fair value of the futures contracts.** Not modelled, because the inputs needed to price the contract to the tick aren't available:
  - no CUSIP-specific repo (specialness of the CTD and near-CTDs);
  - no reliable CUSIP-specific pricing relative to the curve (free prices are lagged and rounded);
  - no view on slope/curvature dynamics beyond the one-factor betas.

  Consequently the following are also out of scope: implied CTD repo calibration, the end-of-month option, the wildcard option, and net basis/implied repo outputs. Market futures prices are still collected (section 3.2) and used only where needed (vol conversion, open interest). **Wishlist (far down):** use market futures prices, e.g. the model-to-market residual across contracts, to infer slope vol or other curve dynamics.
- Curve fitting and idiosyncratic rich/cheap modelling of individual issues.
- Outputs aimed at basis traders, such as the basis-trade duration mismatch or the hedge-ratio change per $100mm of CTD ([outputs.md](outputs.md), Dropped or reframed).
- Intraday or live pricing.
- Full multi-factor term-structure model (later extension, section 10).
- ZT and ZF. Their baskets are narrow (about a year of maturity or less), so switches move duration little. Keep their facts in reference data (section 2) and **collect their market data from day one (section 3.2)**, but don't build or validate models for them in v1.
- Cash-settled Treasury products (micro Treasury yield futures, any yield-based contracts) and non-CME venues. No delivery, so no CTD.

## 2. Contract facts the code must encode

All contracts: quarterly delivery months (Mar, Jun, Sep, Dec); first delivery day is the first business day of the contract month.

| Contract | Face | Original maturity | Remaining maturity (deliverable) | Basket span | CF maturity rounding | Reference CMT (5.4) |
|---|---|---|---|---|---|---|
| **ZN** (10-year) | $100k | ≤ 10y | 6y 6m to 8y from first day of delivery month (6y 6m to 10y before the September 2023 contract) | ~1.5y (~3.5y before Sep 2023) | Down to quarter | 7y |
| **ZB** (T-bond) | $100k | — | 15y to under 25y | ~10y | Down to quarter | 20y |
| **UB** (Ultra bond) | $100k | — | 25y and over | ~5y (25–30y) | Down to quarter | 30y |
| **TN** (Ultra 10-year) | $100k | ≤ 10y | 9y 5m to 10y | ~0.6y | Down to quarter | 10y |

ZN and ZB are the contracts prone to switching. UB and TN are modelled mainly as stable-duration comparisons: TN's basket is narrow, and UB's switches are between 30-year issues of similar duration.

Other contracts, not in v1 (kept so they can be added later through reference data only):

| Contract | Face | Original maturity | Remaining maturity (deliverable) | CF maturity rounding | Calendar family |
|---|---|---|---|---|---|
| ZT (2-year) | $200k | ≤ 5y 3m | ≥ 1y 9m from first day, ≤ 2y from last day of delivery month | Down to whole month | Short |
| ZF (5-year) | $100k | ≤ 5y 3m | ≥ 4y 2m from first day of delivery month | Down to whole month | Short |

The figures above are a working summary. **Verify each against the current CBOT rulebook chapter when encoding it**. They live in `reference/` as data (one record per contract, with an effective-from date because CME has changed grades before, e.g. ZB in 2011, and ZN from the September 2023 contract month), never as constants in code.

- **Delivery calendar** (stored per contract month, not computed ad hoc). ZN, TN, ZB and UB share it:
  - last trading day = 7th business day before the last business day of the month;
  - last delivery day = last business day of the month.

  The short contracts (ZT, ZF) use a different calendar: last trading day is the last business day of the month, and last delivery day is the 3rd business day of the following month.
- Conversion factor: price per $1 par at a 6% yield, per CME's formula, with remaining maturity rounded down to the quarter. **Computed with the formula in both live and historical mode.** CME's published table (TCF) is validation data, collected daily from CME's public FTP server (section 3.2), and the formula is tested against it.
- Invoice price = futures settlement × CF × face/100 + accrued interest at delivery date.
- **Basket changes**: rebuild each basket from the eligibility rules and Treasury security terms on each contract-month roll and after each auction in any basket's maturity range. New issues can join:
  - for ZN, new 7-year notes, and 10-year notes once they fall under 8 years (new 10-year notes before September 2023; they're now deliverable into TN instead);
  - new 10-year notes for TN, which leave its basket about seven months after issue (under 9y 5m);
  - new 20-year bonds for ZB;
  - new 30-year bonds for UB;
  - aging 30-year bonds move from UB to ZB once under 25 years.

  Check rebuilt baskets against CME's daily TCF files (section 3.2); the first file a bond appears in dates its addition to the basket. Reopenings don't change CUSIP, coupon, maturity or CF. Rerun crossovers whenever the basket changes.
- **Baskets are dated, not fixed per contract.** The basket used for a run is the one valid at the horizon date.
- **ZN grade change (September 2023).** From the September 2023 contract month, CME caps ZN's remaining maturity at 8 years; before that the cap was 10 years. Basket rebuilds look up the grade in force for each contract month, never a single rule. CME's TCF files start in December 2023, so pre-2023 ZN baskets can't be checked against them, and ZN backtest cycles before September 2023 run on the old, wider basket.
- **ZB/UB boundary.** A bond crosses from UB's basket to ZB's when its remaining maturity falls below 25 years. Basket rebuilds (historical mode) must apply the boundary at each contract's first delivery day, so the same bond can be in UB for one contract and ZB for the next.

### Options on futures (reference data per option product)
- ZN, TN, ZB and UB each have listed options with quarterly, serial and weekly expiries. **The model uses quarterly and serial options only.** Weeklies are still collected, because the bulletin is stored whole (section 3.1), but they get no reference data and the parser skips them. Store the product codes, and which futures contract each expiry settles into, in `reference/`.
- **Quarterly** options settle into the same-month futures contract. **Serial** options (non-quarterly months) settle into the next quarterly contract.
- Expiry calendar per option product: quarterly and serial options stop trading on the last Friday that is at least 2 business days before the last business day of the month *preceding* the option month. Store the expiry dates; verify the rule against the rulebook.
- Exercise: American, physically settled into futures, with the premium paid upfront. Discount at SOFR to expiry when inverting prices.
- Strike interval and premium tick per product (stored, not hard-coded). The strike interval limits how finely the digital in 5.7 can resolve a crossover.

## 3. Data sources (all free, end of day)

| Data | Source | Live | History | Known weaknesses |
|---|---|---|---|---|
| Basket and conversion factors | Rules + CF formula; CME's daily TCF files (public FTP) for validation | Yes | Rebuild from rules + formula; TCF files from December 2023 | Validate rebuilt baskets and CFs against the TCF files |
| Security terms (CUSIP, coupon, maturity, dated date) | TreasuryDirect / FiscalData | Yes | Yes | Include since-matured issues for history |
| Bond prices by CUSIP | TreasuryDirect daily prices | Yes (the file stored under a date has that day's prices; end of day is filled in a day later, so the same-evening file is replaced once complete, data.md §5.1) | Yes, from 30 May 2008 (until about September 2008, CUSIP and prices only); stored from 2016 | Single price, rounded; timing against the futures settlement not yet checked; off-the-runs noisy |
| Futures settlements (all six Treasury contracts, all listed months) | CME settlements | Yes | Front two contracts from 2016, paid one-off Databento backfill (data.md §5.11) | Used only for vol conversion (5.5), open interest and today's futures duration in the report (DV01 over the settlement; [decisions.md](decisions.md)); collection may be manual; respect terms of use |
| Futures daily bars, cross-check (six Treasury contracts) | Yahoo Finance chart endpoint | Yes | Listed contracts since listing; continuous front month from 2000 (2010 for UB, TN) | Closes equal CME settlements on dates checked; misses some listed months (e.g. June 2027 ZT, ZF, ZN, TN); continuous series rolls on the last trading day, unadjusted; unofficial endpoint, personal-use terms |
| Futures option settlements by strike (section 3.1) | CME settlements | Yes | From 2016, paid one-off Databento backfill to 2026-10-19 (data.md §5.12) | Discrete strikes; noisy far from the money; UB thinner than ZN/ZB |
| Constant-maturity yields | Treasury par yield curve (CMT) and daily bill rates, FRED | Yes | Yes, decades | Smoothed curve, not bond-specific |
| GC funding | NY Fed SOFR (also TGCR, BGCR) | Yes | Since 2018 | Overnight only |
| 1-month and 3-month SOFR, 30-day fed funds futures | CME settlements | Yes | Front two contracts from 2016, Databento backfill as above | For stepped/stripped repo path |
| CTD-specific repo | **Not available free** | — | — | Not used: GC for all bonds (no fair value, section 1) |
| Positions by trader type (asset managers, leveraged funds) | CFTC Traders in Financial Futures, futures only (Socrata dataset `gpe5-46if`) | Weekly | Yes | Tuesday positions released Friday; not collected yet. For the fragility dashboard (section 6) |
| Amount outstanding and stripped, by CUSIP | Monthly Statement of the Public Debt (MSPD), FiscalData | Monthly | Yes | Monthly, so the float is stale between releases; not collected yet |
| Fed holdings by CUSIP | NY Fed SOMA holdings | Weekly | Yes | Not collected yet |
| Treasury buyback results | Treasury buyback operations | Per operation | Yes | Not collected yet |
| Roll progress against past rolls | CME Pace of the Roll | Yes | Unknown | OI by contract month is already in the CME settlements; this only adds the comparison with past rolls. Not collected yet; confirm what it publishes |

Design rules:
- **Every raw file is stored as downloaded, keyed by as-of date**; the model reads only from that store. Re-running any past date gives the same answer.
- **Collect broadly, model narrowly.** Data that can't be backfilled for free is collected every business day from day one, for every product listed in 3.2, whether or not the model uses it yet (section 3.2).

### 3.1 Options chain required

Daily, for all six Treasury futures contracts, store the full CME option settlements as downloaded (the model reads ZN, TN, ZB and UB). They come as the Daily Bulletin's Section 42 PDF, saved from cmegroup.com in a browser each morning, which covers all six contracts, every listed expiry and strike, weeklies included (stored, not used by the model). The model needs these fields:

| Field | Use |
|---|---|
| As-of date, option product, expiry date | Keys; expiry drives the term-structure interpolation |
| Underlying futures contract and its settlement price | Moneyness; mapping vol to the right CTD |
| Put/call, strike, settlement premium | Implied vol, skew, digitals |
| Volume and open interest (if on the settlement page) | Liquidity tiebreaker only; the filters below are price-based |

Coverage:
- **Expiries**: every listed expiry (quarterly, serial and all weeklies) on every listed underlying month. The model uses quarterly and serial expiries only; storing all of them is cheap, keeps past dates reproducible, and can't be done later.
- **Strikes**: the full chain, both puts and calls. The smile fit and digitals need strikes out to the furthest crossover and the grid window (section 5.6), not just near the money.

How the model uses the chain (section 5.5, 5.7):
- **ATM vol**: out-of-the-money puts and calls nearest the money, inverted with a normal (Bachelier) model on the futures price. Early-exercise value is ignored for out-of-the-money strikes (flag in diagnostics). Check put-call parity at the strike nearest the money.
- **Skew**: implied vol by strike per expiry, re-expressed in bp-of-yield moneyness using the futures DV01 of that expiry's underlying.
- **Smile fit**: normal SABR per expiry on the filtered chain; digitals and the factor distribution come from the fit (5.5.1).
- **Crossover-strike vol** (interim, 5.5.2): the smile read at the futures price equivalent to each crossover.
- **Raw digitals** (diagnostic): put-spread slope between adjacent strikes that straddle each crossover's futures price, compared with the SABR digital.
- **Term structure**: the two expiries that bracket the horizon (5.5 step 3). The later one is usually a serial on the *next* quarterly contract.

Filters and fallbacks:
- Drop strikes with a settlement at the minimum tick, deep in-the-money strikes, and prices that break monotonicity or convexity in strike.
- Skip an expiry with fewer than a minimum number of usable strikes (a parameter, initially 5).
- If no expiry is usable (most likely for UB, whose options are thinner than ZN's and ZB's), use the following, in order:
  1. Map vol from the neighbouring contract through betas (UB from ZB, ZB from UB, TN from ZN).
  2. Use realised vol (as in historical mode).
- Record the source used in diagnostics.

### 3.2 Collection policy

A free source that only shows recent days is lost for good on any day it isn't pulled. So collection is wider than the model and runs every business day.

**Not backfillable for free: pull every business day, full files, unfiltered.**
- CME futures settlements: all six Treasury contracts (ZT, ZF, ZN, TN, ZB, UB), all listed months, including calendar-spread settlements if published.
- CME option settlements: options on all six, every listed expiry, every strike, puts and calls. Collected as the Daily Bulletin's Section 42 PDF (section 3.1).
- CME 1-month SOFR, 3-month SOFR and 30-day fed funds futures settlements (repo path, 5.3).
- Yahoo Finance daily bars for the six Treasury futures: each listed contract Yahoo carries and the continuous front-month series, 10 days per daily pull, full history backfilled once. A cross-check on CME settlements; not a replacement, since Yahoo drops expired contracts and skips some listed months.
- TreasuryDirect daily prices: the whole file, every CUSIP, every day. Past dates can currently be looked up back to 30 May 2008, but don't rely on that lasting. History from 2016 is stored once with `ctd backfill --prices-from 2016-01-01`.

**Backfillable: pull daily anyway, and backfill once at setup.**
- CME Treasury conversion factor tables (TCF) from CME's public FTP server (`ftp.cmegroup.com/settle/TCF/`): a CSV and an xlsx for every business day, back to December 2023. Validation data for the CF formula and basket rebuilds; consecutive files show the day CME changed a basket. How long CME keeps them is unknown (section 11), hence the daily pull.
- Treasury nominal par yield curve (CMT) and daily bill rates, FRED series. Not Treasury's real yield curve or long-term rate tables: TIPS aren't deliverable and the long-term composites are averages the model doesn't use.
- NY Fed SOFR, TGCR and BGCR.
- FiscalData / TreasuryDirect security terms and auction results, including matured issues.
- Not collected yet, needed for the fragility dashboard ([outputs.md](outputs.md)): CFTC Traders in Financial Futures (weekly), MSPD outstanding and stripped amounts (monthly), NY Fed SOMA holdings (weekly), Treasury buyback results. All have free history, so they can be added and backfilled when the dashboard is built. CME Pace of the Roll is on cmegroup.com and may not be backfillable; check before relying on it.

**Operations**
- `ctd fetch` runs on a schedule every business day after CME final settlements are published. It is idempotent: re-running a date never overwrites a stored file, it only fills what's missing. The one exception is a provisional TreasuryDirect price file, replaced once its end-of-day prices are published (data.md §5.1).
- Each date gets a manifest listing every expected file and its status. A completeness check flags missing products, and a gap triggers retry and an alert.
- Recovery window for a missed run: CME futures and option settlement pages show **5 trailing business days**. Beyond the window, record the gap rather than fill it from another source.
- Store files exactly as downloaded (lossless compression at rest is fine). Record the source URL and download timestamp alongside each file.
- Respect each source's terms of use (section 11).

## 4. Architecture

```
ctd/
  data/            # fetchers + raw store (one module per source); derived/ builds the Parquet tables
  reference/       # contract specs, delivery calendars, CF tables + CF formula, basket rules
  bonds/           # cash flows, accrued, price<->yield, forward price, KRDs
  funding/         # term GC repo from overnight rates
  curve/           # CMT history, beta estimation, residual stats, realised vol
  vol/             # option implied vols, put-slope digitals, term-structure interpolation
  model/           # factor grid, envelope, crossovers, probabilities
  risk/            # DV01, key rate DV01s, cluster profiles, scenarios
  history/         # historical runner, basket rebuild, backtest scoring
  report/          # daily output tables + charts
  cli.py           # `ctd fetch --asof 2026-10-16`   (snapshot every source in 3.2, all products)
                   # `ctd run --contract ZBZ6 --asof 2026-10-16`
                   # `ctd derive`   (bring the derived Parquet tables up to date)
                   # `ctd history --contract ZB --from 2022-01-01 --to 2026-10-16`
tests/
docs/design.md
CLAUDE.md
```

- Python, numpy/scipy/pandas.
- Pure functions in `bonds/`, `funding/`, `model/`, `risk/`; I/O only in `data/` and `report/`.
- **Reading the store: three layers.** The model never touches paths, file formats or which source a number came from.

  | Layer | Holds | Source-specific? |
  |---|---|---|
  | Raw store (`data/raw/`) | files exactly as downloaded: bulletin PDFs, Databento DBN, CME JSON, TreasuryDirect CSV | yes, one format per source |
  | Readers (`parse`/`read` in each source's module in `data/`) | one source's raw file for one date, as standard records: `OptionSettle`, `FuturesSettle`, `BondPrice`, ... | yes, one reader per source |
  | Derived tables (`data/derived/`, Parquet) | the standard records across all dates, one table per kind of data | no: one schema whatever the source |

  - **Readers** (phase 1b) are enough for any single-date run: `ctd run` for one date calls them directly.
  - **Results** (`data/results/`, JSON) are the model's own output, one file per model, contract and date (phase 1b D, section 10). Like derived tables they are rebuilt from the raw store, never edited by hand, and a re-run overwrites them; each records the raw files (with sha256) and the code version it came from.
  - **Derived tables** (phase 2) are for anything across dates: betas, history, the backtest. Each table is built from the raw store by `ctd derive` (running the readers over every date), never edited by hand, and records the raw files it was built from. It is a cache: the raw store stays the source of truth, and a derived table never holds data the raw store lacks. Code: `data/derived/` (`store.py` the layout and build, one module per table).
  - **Every derived row has a `source` column, and a precedence rule per table says which source wins on a date where several exist** (e.g. options: Databento before 2026-10-16, the Section 42 bulletin from then on). The winner's gaps are never filled from another source. Building the table also compares the sources where they overlap (`overlap` in `_build.json`, disagreements printed), so the overlap days are an automatic cross-check. Changing the daily source (e.g. to Databento instead of the bulletin and settlement pages) changes the rule and a rebuild, not the model.
  - **Format and layout.** Parquet (zstd), not Feather: tables are written once and read many times, filtered by product and date, which Parquet's row-group statistics skip to; it is several times smaller and read by every tool. Partitioned by product and year, `data/derived/<table>/product=ZN/year=2026/part.parquet`, with the partition columns in the path. Read with `DerivedStore.read(table, products, start, end)`.
  - **Two stages.** Each source's rows go first to staging, `data/derived/staging/<table>/<source>/...`, as read; the merged table applies the precedence rule to the staging partitions. So a slow source (the 7.6 GB option backfill) is read once, a precedence change only re-merges, and the overlap comparison reads staging.
  - **Incremental builds.** A source splits its raw files into units (a date's file, or a product's backfill), each listing the raw files it is read from with their sha256. `_build.json` records them; a unit whose files differ is read again and replaces its rows, and only the partitions it can fall in are rewritten. A unit can depend on more than one date: a CME futures row for D takes its open interest from D+1's page, so storing D+1 re-reads D. A source's `version` and the table's `version` (schema) are bumped by hand when a reader's output or the columns change, and force that rebuild. A unit that fails to read is left out, reported (exit 1, a desktop alert with `--notify`) and retried on the next build. Each build also lists every product's missing trading days, the days on the `cme` calendar (`holidays.csv`, derived from the data for 2016–2025, [data.md](data.md) §2.5) between its first and last date with no rows, so a skipped date needs no diagnosis: it's printed, recorded in `_build.json` (`missing_days`), and simply absent from the table. **The invariant: an incremental build gives the same tables as `ctd derive --full`** (tested).
  - Tables, built when a step first needs them:
    - **options**: one row per date, product, option month (`label`), right and strike: `expiry` (last trading day, as the source states it: page 1 of the bulletin, Databento's definitions), `underlying_month`, `settle` (null for a cabinet), `cabinet`, `volume`, `open_interest`, `source`. No delta: Treasury options are American and CME's deltas come from its own model; a Black-76 delta from the implied vol is enough for anything the model does, and the bulletin PDFs keep CME's. Sources: Databento for 2016 to 2026-10-15, Section 42 from 2026-10-16 (TN from its "ADDITIONAL" section, calls and puts told apart by put-call parity), the daily Databento pull from 2026-10-26. Databento also settles strikes the bulletin leaves out (about twice as many rows a day).
    - **futures**: one row per date, product and contract month: `contract` (`ZNZ6`), `settle`, `open_interest` (at the close of `asof`), `source`, for the six Treasury futures and SR1, SR3, ZQ. CME pages from 2026-10-14, Databento before, the daily Databento pull from 2026-10-26 (Treasuries and SR1) (front two contracts only: enough, since the model needs option volatility no more than 3 months out, on the front two futures; decided 2026-10-25, [data.md](data.md) §5.11; SR1 and ZQ have the front eight months, for the repo strip, §5.13). No volume: CME's page has a same-day estimate, Databento the final cleared volume ([data.md](data.md) §5.8).
    - **options_quality**: one row per option chain (date, product, option month), built from the options and futures tables by `ctd derive` whenever either changes (`data/derived/quality.py`), so bad chains are skipped with a filter (`ok`) instead of diagnosed. Checks, each a column and, on failure, a name in `issues`: `stale`, the at-the-money straddle scaled by √(days to expiry) jumping away from neighbouring days that agree with each other (a real volatility move persists and isn't flagged); `parity`, near-the-money call minus put against futures minus strike, beyond 4/32; `forward`, the futures price a chain implies by parity against the other chains on the same futures that day, beyond 4/32 (no futures settlement needed, so it covers the deferred months the futures backfill lacks); `order`, calls rising or puts falling with strike at two or more strikes. They catch the stale Sunday republications of Friday finals ([data.md](data.md) §5.12): every TN chain on 2017-11-24, 2018-08-24 and 2020-11-20, and the deferred ZB and UB chains breaking parity. Flagged: 0.1% of chains for ZN, ZF and ZT, 0.4% ZB, 1.6% UB, 3.8% TN, mostly Fridays.
    - **bond_prices**: one row per date and CUSIP, every security type in the TreasuryDirect file (bills, notes, bonds, TIPS, FRNs), 2016 on: `type` (the partition column, with the year), `coupon`, `maturity`, `call_date`, and all three prices as published, `buy`, `sell` and `eod` (null where TreasuryDirect gives 0), plus `provisional` for a same-evening file without end of day (replaced later, and then read again). Which price a step uses is its own choice ([decisions.md](decisions.md)); the table reproduces `td_prices.read` exactly. Missing days are checked on the `sifma` calendar, which for 2016–2025 was derived from these same files, so the check bites only from 2026 (`data/derived/bonds.py`).
    - **securities**: one row per CUSIP from TreasuryDirect's security terms (one record per auction): the first auction's `original_term` (`10-Year` for a reopened note, which ZN's original-maturity rule needs), `dated_date` and `original_issue_date`, plus `coupon`, `maturity`, `last_issue_date`, `auctions` and the callable, TIPS and floating flags. A single file, rebuilt when a newer pull of the terms is stored; the latest pull is used because terms don't change once issued, so a newer pull only adds CUSIPs. Every priced CUSIP is in it, with the same coupon and maturity. Join to `bond_prices` on `cusip`.
    - **par_curve**: one row per date (1990 on), a column per tenor (`y_1m` … `y_30y`, decimals), from Treasury's year files; FRED's CMT series are a second source that never wins, so every build compares them (they agree on all 97,450 shared values).
    - **rates**: one row per date and rate (SOFR, TGCR, BGCR, EFFR, 2018 on) with the rate, its percentiles and volume, and EFFR's target range, from the NY Fed, with FRED's SOFR and fed funds as the cross-check. Both take each value from the latest pull and note any a newer pull changes ([decisions.md](decisions.md)); missing days are checked on the `sifma` calendar from 2016 (`data/derived/rates.py`).
    - **baskets**: every contract month's deliverable notes and bonds (all six contracts, quarterly from March 2016), rebuilt from the grade records (`contract_grades.toml`, `reference.grades.eligible`) and the security terms, with the CF from the formula and `eligible_from`, the auction that makes a bond deliverable; the basket on a date is the rows with `eligible_from` before it. The original-term limit applies per tranche, as CME applies it: a 7-year note reopened as a 5-year (91282CGQ8) qualifies for ZT and ZF from that reopening (`security_auctions`, one row per auction, alongside `securities`). Every build checks the rules against every stored TCF file (December 2023 on): membership and CF agree for all 89 contract months CME lists, except four new issues CME listed a few days late in May 2025 (`cme_late`); a disagreement fails `ctd derive`. A single file, rebuilt when the securities, grades, product records or TCF files change (`data/derived/baskets.py`).
    - Analytics (yields, durations, DV01s) are computed from these tables when needed, not stored as data: they depend on the code and conventions, not just the raw files.
- Dates and conventions explicit everywhere: settlement date (T+1), delivery date, actual/actual accrual, semiannual compounding.

## 5. Model

### 5.1 Bond math (hand-written)
- Write the bond math directly; Treasury math is simple. QuantLib (or TreasuryDirect published values) is used **only in tests** as an independent check.
- **Yield convention: street convention, one pricing function used everywhere.** Scheduled (unadjusted) coupon dates, semiannual compounding, fractional exponent for the first period:
  `P_dirty = Σ_k CF_k / (1 + y/2)^(w + k)`, `w` = days to next coupon / days in current period.
  Every price→yield, yield→price and duration calculation uses this function. Business-day calendars are used only for settlement and delivery dates.
- What can be approximate: day counts within a period (1 day of accrual ≈ 0.3bp on the ZB crossover, and partly cancels across bonds), stray holidays.
- What must be exact:
  - **coupons between today and the horizon** in the forward price (a missed coupon is a 1–2.5 point error);
  - clean → dirty with accrued at the correct settlement date (TreasuryDirect prices are clean);
  - accrued at the delivery date (carry);
  - forward KRDs measured from the horizon date.

### 5.2 Horizon
- Compute each likely CTD's daily carry: coupon accrual minus repo on dirty price.
- Positive carry: horizon = last delivery day. Negative: first delivery day. Carry is the basket's, **probability-weighted** over the bonds likely to be CTD, as the light model does ([decisions.md](decisions.md), Delivery date for the light model's forward prices): following today's CTD alone moves the date each time two bonds of opposite carry trade places.
- **One horizon for the whole basket**, not one per bond (the short commits to a date before knowing which bond wins).
- If carry is near zero, or slightly negative with a crossover near: run both dates and take whichever gives the lower expected converted price for the short. This expectation is an internal decision rule, not a published fair value.

### 5.3 Term GC repo and forward prices
- Overnight rate: **SOFR** (closest proxy for DVP GC on basket bonds).
- Term rate to horizon, actual/360 compounding:
  `R_term = [Π_i (1 + r_i · d_i/360) − 1] × 360/D`
- Path for `r_i`, in increasing effort:
  1. **Flat** at today's SOFR (or 5-day average). The fallback when the strip doesn't cover the last delivery day.
  2. **Stepped** at FOMC dates using fed funds / 1-month SOFR futures. Deferred to historical mode (needs an FOMC calendar; [decisions.md](decisions.md), Repo path for the light model).
  3. **Strip of 1-month SOFR futures** (`funding/strip.py`). Default ([decisions.md](decisions.md)): each month flat at the rate that reprices its SR1 average, after the month's known fixings.
- **Year-end/month-end turn**: for December contracts add a turn adjustment with options 1 or 2 (option 3 includes it, spread over the month).
- Ignore term premium.
- **GC for all bonds.** CTD specialness is not modelled (no free CUSIP-specific repo). A 50bp special rate on the CTD moves its crossover by about 2bp; covered as a sensitivity (section 8).
- Sensitivity: 10bp repo error ≈ 0.013 points on a ZB bond over ~0.2 years (≈0.3bp of crossover); matters more for the carry-sign/horizon decision.
- Forward clean price at T for each bond from dirty price, term repo, and coupons before T.
- Convert to forward yield `y_i^fwd`. Everything is centred on these.

### 5.4 Factor and betas
- Factor `x` = constant-maturity yield near the current CTD, per contract (section 2 table): **7-year for ZN, 10-year for TN, 20-year for ZB, 30-year for UB**.
- For each published CMT tenor that brackets the basket (5, 7 and 10y for ZN; 7 and 10y for TN; 10, 20 and 30y for ZB; 20 and 30y for UB), regress yield changes on the reference: `Δy(τ) = β(τ)·Δx + ε(τ)`. Linear interpolation of these node betas equals regressing on a linearly interpolated curve, so nothing is lost by estimating only at published tenors (method and alternatives in [decisions.md](decisions.md)).
  - 2–3 day or weekly changes; 6–12 month window or exponential weights (half-life ~3 months).
  - Re-estimate betas and vol daily (rolling or EWMA), never in occasional steps, so the DV01 time series has no artificial jumps.
  - Shrink betas slightly toward 1.
  - Also estimate on **sell-off days only**; use those if materially different.
- Interpolate β linearly at each bond's remaining maturity at T (the basket spans ZN ~6–9y, or ~6–11y for contract months before September 2023; TN ~9–10y; ZB ~14–26y; UB ~24–30y).
- Store residual SDs `σ_ε(τ)` and the residual SD of the spread between candidate bonds (used in 5.7; diagnostic for one-factor adequacy: under ~4bp over the horizon is fine, above ~6bp suggests a second factor).

### 5.5 Volatility
Live mode:
1. Futures option implied vol from the contract's own options chain (section 3.1), ATM to start.
2. Price vol → normal yield vol of each expiry's CTD: `σ_y ≈ σ_price × F / (100 × D_F)`, using the CTD duration of **that expiry's underlying contract**.
3. **Interpolate total variance to the horizon** between the bracketing expiries:
   `V(T) = σ_y² T`, linear in time between expiries; `σ_y(T_h) = √(V(T_h)/T_h)`.
   - Example for a December contract with a December horizon: December quarterly options on December futures expire in late November. January serial options on March futures expire in late December. Those two bracket the horizon.
   - Captures vol term structure and event variance (e.g. December FOMC).
   - When the later expiry's underlying is the next contract, adjust its vol for that contract's different CTD maturity via betas. This matters most for ZB, whose basket is widest.
   **Fallback**: square-root-of-time scaling from a single expiry, when the horizon is close to the first expiry or only one expiry is usable.
4. To factor units: `σ_x = σ_y / β_CTD`; width `S = σ_x √T_h`.

**v1 uses a single ATM-based normal width `S` for all crossovers.** Crossover locations are set by forward prices, CFs and betas, not by vol, so no iteration between vol and crossovers is needed: find the crossovers first, then apply the distribution.

#### 5.5.1 Smile-implied distribution (phase 3)
Replaces the single normal width with one market-implied distribution for the factor, used for every crossover. This handles any number of crossovers consistently (monotone tail probabilities by construction) and includes skew and the smile-slope term in each tail probability.

1. **Fit a smooth smile per expiry**: normal SABR (β = 0) on normal vols of the filtered chain (section 3.1).
   - Why fit rather than differentiate raw prices: strikes are discrete (crossovers fall between or beyond them), premiums are rounded to 64ths, wings are thinly traded, and differencing amplifies all of it (negative densities). The fit gives a continuous, differentiable, arbitrage-free price function.
   - Weight by liquidity (open interest or volume); drop minimum-tick/cabinet strikes; constrain extrapolation (e.g. cap wing vol at a multiple of ATM vol).
   - Record fit residuals per strike.
2. **Digitals from the first derivative** of fitted put prices with respect to strike:
   `P(F_E < K) = (∂Put/∂K) / DF`
   (density, if needed, from the second derivative). Premium is paid upfront, so divide by the discount factor to expiry.
3. **Map futures price to factor through the envelope**: `F(z) = min_i C_i(z)`, monotone in z, so `P(F_E < K) = P(z > z(K))` with `z(K)` solving `min_i C_i(z) = K`. Use the envelope, not the CTD's own curve, because near a crossover the futures follow whichever bond is cheapest. Approximation: futures at expiry = cheapest converted forward price, ignoring residual switch value to delivery (slight upward bias in tails beyond a crossover).
4. **Recentre** so the distribution's mean (or median) in z is 0, matching the forwards. Log the size of the shift; a large one signals inconsistent inputs.
5. **Extend from option expiry to the horizon by convolution**: `z_h = z_E + ε`, `ε ~ N(0, V(T_h) − V(T_E))` in factor units, with V from the total-variance interpolation (step 3 above). Preferred over rescaling the whole distribution by `√(V(T_h)/V(T_E))`, because skew should fade somewhat over the extra time. The two agree when the horizon is close to expiry.
   - This needs `T_h ≥ T_E`. When the nearest usable expiry falls *after* the horizon, the increment is negative and convolution fails. This happens after the contract's own options expire, e.g. a negative-carry December contract in early December, whose only expiry is the January serial on March futures. Section 11 has the case and the interim choice.
6. **Result**: one density `φ(z)` on the grid at the horizon. All crossover tail probabilities, region probabilities, duration weights (5.9) and scenario profiles come from it.

Diagnostics:
- Compare each crossover's SABR digital with the raw finite-difference put-spread digital from settlements; flag disagreements of more than a few percentage points (bad fit or stale settlement).
- Report the ATM-normal probability alongside the smile-implied one; the gap shows how much skew and wing pricing contribute.
- Report the share of each tail probability that lies beyond the furthest liquid strike (pure extrapolation), and label such crossovers' probabilities as extrapolated.

Caveats: rich or floor-priced wings fatten fitted tails and can overstate probabilities for far crossovers (e.g. the later steps of ZB's staircase); implied tails also carry a risk premium (risk-neutral, not real-world).

#### 5.5.2 Interim alternative: one vol per crossover
If the smile fit isn't ready, read the implied vol at each crossover's futures strike `K_k = min_i C_i(z_k)` and give each crossover its own width `S_k`. Requires two patches that 5.5.1 makes unnecessary:
- **Monotonicity**: on each side of the forward, tail probabilities must decrease with distance; cap farther tails at the nearer one's value and log a warning.
- **Density for durations**: build a piecewise density, using the ATM normal shape within each region rescaled so the region's mass equals its probability: `φ*(z) = φ_ATM(z) × π_i / P_ATM(region i)`.

Historical mode: implied vol from the Databento option history (section 7), as in live mode; realised vol (EWMA of daily changes in the reference CMT yield) is kept as a comparison and a fallback where options are too thin.

### 5.6 Pricing grid
**Window.**
- v1 (normal width): z from −4S to +4S.
- With the smile-implied distribution (5.5.1), size the window by **quantiles**, not multiples of S, since a skewed or fat-tailed distribution can put meaningful mass beyond ±4S on one side and waste points on the other:
  - `z_min = Q(tol)`, `z_max = Q(1 − tol)`, with `tol` a parameter (initially 1e-4), found by root-finding on the CDF **after** the horizon convolution;
  - widen to include every crossover with tail probability above `tol`, and the reported scenario range (duration profile, e.g. ±100 to ±150bp; ±1σ and ±2σ);
  - hard cap (e.g. ±8 × ATM-equivalent width, or ±300bp) against runaway SABR wings; record the mass beyond the cap, renormalise, and flag the fit as suspect if the truncated mass exceeds `tol`;
  - record the probability mass beyond the furthest listed strike (extrapolated).

**Spacing.** 1bp steps across the window; optionally finer near the centre and crossovers and coarser in the far tails. Crossovers are root-found exactly, so spacing only affects integrals (durations).

For each z on the grid:
```
y_i(z) = y_i^fwd + c_i + β_i · z
P_i(z) = clean price at T from y_i(z)
C_i(z) = P_i(z) / CF_i
```
`c_i` solved per bond so that `E[P_i(z)] = forward price` under z ~ N(0, S²) (convexity adjustment, ~1–2bp for ZB). **Optional without fair value**: it moves crossovers only through its difference across bonds (a basis point or two). Default off in v1 (centre on forward yields); add it if backtests show a bias.

### 5.7 Envelope, crossovers and probabilities
- `min_i C_i(z)`; record the argmin (the CTD in each state). Only the argmin is used; the envelope's value is not published.
- Root-find the exact z where the argmin changes: crossovers `z_1 < z_2 < …`. Expect ZN: switches within the 6.5–8y basket since September 2023, so smaller duration jumps; before then usually one major switch (6.5–7y cluster → 9.5–10y cluster); ZB: a staircase of two or three; UB: one or two, between the shortest and longest 30-year issues; TN: rarely any that matter, since its basket is under a year wide.
- Tail probability per crossover, measured from the forward (z = 0) on its own side:
  - sell-off side: `Q_k = P(z > z_k)`; rally side: `Q_k = P(z < z_k)`.
  - v1: `Q_k = Φ(−|z_k| / S)`. With 5.5.1: read from the smile-implied CDF. With 5.5.2: `Φ(−|z_k| / S_k)`, then the monotonicity cap.
- Region probabilities: differences of successive tail probabilities on each side; the current CTD's region gets the remainder.
- Slope adjustment per crossover between bonds S and L, for probabilities only:
  - v1: `S_eff = √(S² + (m · σ_ε,spread)²)`, `m = D_L / (D_L − D_S)` (beta-adjusted; level measured at the short bond's yield).
  - With 5.5.1: convolve that crossover's tail with `N(0, (m · σ_ε,spread)²)`, i.e. `Q_k = P(z_h + m·ε_slope > z_k)`.
  - Use the unadjusted density for durations (5.9). Check that adjusted tails stay monotone across a staircase; if not, cap and warn (the empirical two-factor model is the clean fix).
- Raw put-spread digitals from settlements are a **diagnostic** against the SABR digitals (5.5.1), not a separate model output.

### 5.8 Fair value: not modelled
See section 1. No model futures price, no comparison with market settlement, no implied CTD repo. Wishlist: use market futures prices to infer slope vol or other curve dynamics.

### 5.9 Risk and scenarios
- **Futures DV01**: region-weighted over the grid, each bond's DV01 evaluated where it is CTD:
  `DV01_F = Σ_grid φ(z) · DV01_argmin(z)(z) / CF_argmin(z) · Δz`
  For a factor shift this equals the derivative of the expected envelope, so no bump-and-reprice of a futures price is needed. It holds vol fixed (no vega).
- **Key rate DV01s**: same weighting, with each bond's forward KRDs at T: tent bumps to the Treasury par curve (linearly interpolated, bootstrapped), cash flows timed from T, each bond's KRD shares scaled to its DV01 from the pricing function ([decisions.md](decisions.md), How KRDs are computed). Short-tenor KRDs of low-coupon bonds are negative: their par-bond hedge is short there. Key-rate grid: **2, 5, 7, 10, 15, 20, 25, 30 years**, fixed ([decisions.md](decisions.md)). The 15 and 25-year nodes make a ZB switch (about 15y to about 25y) visible.
- **Units**: $/bp per $100mm notional by default; per contract also available.
- **Clusters**: group bonds with similar key rate profiles (same dominant key rate, DV01 within ~5%). Report expected (blended) KRDs and each cluster's KRDs.
- **Scenarios (±1σ, ±2σ)**: shift every forward yield by kσ × β_i, keep the remaining vol, and recompute crossovers, probabilities, DV01 and KRDs at the shifted state. Don't just read off the CTD at the shifted yield, which jumps and overstates the change. Record whether the smile is treated as sticky strike or sticky moneyness.
- **Duration profile**: blended DV01 and KRDs as a function of the shift (about −100 to +100bp, wider when ±2σ falls beyond; `profile.half_range`); ±1σ and ±2σ are points on it. Label shifts both in bp and in percentiles of the move-to-horizon distribution (σ√T).
- **Comparison measures** (section 6): *CTD-based DV01* is DV01/CF of the single CTD at the forward (z = 0), the number most vendor systems report; it jumps when the CTD changes. *Constant-CTD DV01* holds one bond fixed through the series (the CTD on the contract's first date, reset at each roll; [decisions.md](decisions.md)), so its gap to the probability-weighted DV01 is the part of the change caused by the basket.
- **Effective maturity**: DV01-weighted, `Σ_k KRD_k · T_k / Σ_k KRD_k` over the key-rate grid. A cleaner switch signal than DV01, since yield level and roll-down move it much less than a switch does; against the par curve it lengthens as yields rise with the CTD unchanged ([outputs.md](outputs.md), chart 3).
- **Distance to switch**: shift to the nearest crossover on each side, in bp and in σ.
- Blended KRDs are local; they understate how fast weights change near a crossover (negative convexity). The slope of the duration profile carries futures gamma.

### 5.10 End-of-month option: out of scope
Affects futures value, not durations or the probability of a major switch materially. Not modelled (section 1).

### 5.11 Light model (first build)
The lightest version skips the factor model, the betas and the vol fitting: find the futures price at which each switch happens, then read the probability of the futures finishing below it from the put settlements. One basket, one option chain, a loop over shifts. It is the same calculation as the raw put-spread digital diagnostic (5.5.1, 5.7), so the work carries over to the full model.

1. **Basket and converted prices.**
   - Basket and conversion factors from CME's TCF file for the contract (a shortcut: the full model rebuilds the basket and uses the CF formula, section 2; the derived `baskets` table already does and matches every TCF file, so the light model could switch to it and the TCF files could be dropped without issue, data.md §5.7); clean prices from TreasuryDirect.
   - Forward clean price of each bond at the delivery date with flat SOFR (5.3, path 1), divided by its CF. Delivery date: the last delivery day if the basket's probability-weighted carry (weighted by the option-implied probabilities of step 3) is positive, the first if negative ([decisions.md](decisions.md); the CTD's own carry until 2026-10-26).
   - Lighter still: skip carry and use today's converted prices. The ranking near a crossover can then be off by a few ticks, a basis point or two.
2. **Switch points as futures prices.**
   - Shift every bond's yield in parallel (β = 1) in 1bp steps, about −100 to +150bp. Reprice each bond and take the cheapest converted price at each shift, `E(z) = min_i C_i(z)`.
   - Record each shift `z_k` where the cheapest bond changes, and the envelope value there, `E(z_k)`.
   - Recentre onto the market futures settlement, which won't match the envelope exactly:
     `K_k = F_market + (E(z_k) − E(0))`
3. **Digitals from the put settlements.**
   - Use the expiry closest to delivery: the quarterly on the same contract (the December quarterly for the December contract).
   - For each `K_k`, take the listed strikes either side, `K_lo < K_k < K_hi`:
     `P(F < K_k) ≈ [Put(K_hi) − Put(K_lo)] / (K_hi − K_lo) / DF`
     with DF the SOFR discount factor to expiry.
   - If neighbouring strike pairs give different slopes, interpolate linearly between them.
   - For a crossover on the rally side, use calls, `P(F > K_k) ≈ −[Call(K_hi) − Call(K_lo)] / (K_hi − K_lo) / DF`, or 1 − the put digital.
4. **Probabilities.**
   - Sell-off side: the probability beyond the first switch is `P(F < K_1)`. The bond between the first and second switches gets `P(F < K_1) − P(F < K_2)`, and so on outward; the bond beyond the last switch keeps its full tail `P(F < K_n)`.
   - Rally side: the same with `P(F > K_k)`.
   - The current CTD gets the remainder.

**What it gives up:**
- **Horizon**: it gives the probability of crossing by option expiry (late November for December), not by delivery. Somewhat low if the CTD is delivered at month-end.
- **Parallel shifts**: any steepening tendency the betas would capture is missing, so ZB's switch points could be off by a few basis points.
- **Noisy strikes**: a single put spread inherits settlement rounding (64ths), so treat results as ± a couple of percentage points. Check that probabilities fall as switches get further away.
  - A true digital can't rise with distance (it is a cumulative distribution), so a negative region is always measurement error, almost always rounding: ±1/128 on each price over a ½-point gap is up to ±3 points per digital. Two close switches, especially two between the same strikes, have digitals that differ by less than that, and their difference can come out negative (ZBZ6 on 2026-10-21: 40.5% and 38.8%, a 1.7% region inside the noise). Stale or off-market wing settlements can do the same but are rarer, since CME settles from a fitted vol curve and most wing strikes don't trade. Tails summing to more than 1 are the same noise when the first switch on each side is near the market.
  - Such a region is set to 0 with a warning: the model can't separate those two bonds. Switches that don't chain from the CTD, or a digital on the wrong side, are code errors and raise.
- **Remaining switch value**: at expiry the futures still include some switch value, which biases the tail probabilities slightly upward (as in 5.5.1 step 3).
- **Outputs**: switch points and CTD probabilities only; no DV01, KRDs or duration profile.

For a snapshot of where the market prices the switch today, that's a reasonable trade-off.

## 6. Outputs (daily, per contract)

The published charts and their tiers are specified in [outputs.md](outputs.md). The headline is duration (chart 1: duration profile with key-rate shape; chart 2: diverging key-rate change bars; chart 3: DV01 time series with effective maturity). The model computes, per contract and date:

**Tier 1**
- Probability-weighted DV01 and KRDs on the key-rate grid, blended and per cluster (5.9).
- Duration profile across shifts, with ±1σ and ±2σ (or the 5th, 25th, 75th and 95th percentiles), and the change in each KRD versus today at those points.
- CTD-based DV01 and constant-CTD DV01 alongside the probability-weighted DV01 (constant-CTD is a series measure, built with the time series in phase 2).
- DV01-weighted effective maturity, also for the constant CTD, so the basket's contribution can be read as the gap.
- Distance to switch in bp and σ, flagged when below 1σ.
- CTD probabilities per bond and per cluster (a supporting series).
- Event flags per date: basket change, contract roll, parameter re-estimation. Any step in a series must be attributable to one of these, or to near-expiry collapse of probabilities.

**Tier 2**
- Contract roll: run the December and March contracts (generally the expiring and next) on the same date and show the DV01 and KRD change at the roll with no yield move.
- Cross-contract comparison: ZN, TN, ZB and UB at today's yields.
- Uncertainty bands: rerun at vol ±10% and betas ±0.05.
- Calibration backtest (section 8).
- Calendar overlay: auctions adding issues, roll period, first notice day, delivery dates.
- Daily attribution of DV01 changes, sequential in a fixed order: basket, then time, then vol/betas, then yields. Event flags stand in until it's built.
- Later: charts 1 and 2 for a user-entered mix of contracts.

**Fragility dashboard** (context, not a composite score): asset-manager duration held via futures (CFTC TFF asset-manager long × probability-weighted DV01), deliverable float of the next CTD (outstanding − SOMA − stripped, against open interest), and rebalancing timing (switch zones that coincide with month-end or the roll). Needs the sources marked "not collected yet" in section 3.

**Internal, not published**
- Basket table: CUSIP, coupon, maturity, CF, price, forward price, forward yield, β, carry, repo used, converted forward price.
- Crossover table: from-bond → to-bond, crossover z (bp), equivalent futures price, distance from forward, probability (base, slope-adjusted, option-implied).
- Diagnostics: vol source, strike and expiries used; horizon chosen and why; repo path used; beta window; residual SDs; warnings.
- Chart: converted forward prices vs factor shift (the envelope), with the shift distribution overlaid.

## 7. Historical mode

Goal: time series of CTD probabilities, futures DV01 and KRDs for past contracts, from free data plus two paid one-off backfills (Databento futures and options settlements).

**Today (2026-10-26):** only the December 2026 contracts can be run historically, from 2026-09-01 (phase 1d); each contract is run only while it is liquid, from the previous contract's roll to its own option expiry ([decisions.md](decisions.md), Which dates a contract is run for). A long history needs reference data for every past contract month, the roll between contracts, baskets from the derived `baskets` table before the TCF files start (2023-12-11) and a repo rule before May 2018; that list is in the same entry.

**Start: 2016.** Historical mode goes back to the March 2016 contract month and no further, because earlier Treasury futures rule changes aren't handled. Rule changes since then (e.g. ZN's 8-year cap from September 2023) are dated reference records.

- **Baskets**: rebuild per past contract from the issue list (including since-matured issues) and eligibility rules; compute CFs with the formula. Validate against any published past tables. This is the main effort.
- **Prices**: past TreasuryDirect prices by CUSIP, stored from 2016 (available from May 2008). Before about September 2008 the files have no coupon or maturity columns; join on CUSIP to the security terms.
- **Repo**: SOFR (from 2018); GC only. The SR1 strip needs about the front six months; the derived futures table has the front eight of SR1 and ZQ ([data.md](data.md) §5.13), but `ctd run` still reads SR1 from the `cme_stir` page only, so the historical runner must read it from the table ([decisions.md](decisions.md), Repo path for the light model). Before May 2018 (no SR1 or SOFR): flat, or ZQ plus a spread, to be decided.
- **Vol**: implied from the option history below, as in live mode; realised EWMA vol of the reference CMT yield as a comparison and a fallback.
- **Futures settlements**: front two contracts of each product from 2016, from a paid one-off Databento backfill (data.md §5.11), for open interest, the roll and the futures price. From 2026-10-14 the CME files are the record; on overlapping dates Databento cross-checks them and never fills their gaps.
- **Option settlements**: every standard (quarterly and serial) option on all six contracts from 2016, settlement and open interest by strike, from a paid one-off Databento backfill ending 2026-10-19 (data.md §5.12). Historical mode can therefore use option-implied probabilities, including the light model's digitals (5.11), and the backtest can score them. From 2026-10-16 the Section 42 bulletin is the record; on overlapping dates Databento cross-checks it and never fills its gaps. Reading ten years of options per run needs the derived Parquet tables (section 4).
- Futures DV01/KRDs need no futures price: they are probability-weighted basket DV01s over conversion factors.
- Runtime is trivial; data collection is the constraint.
- Doubles as the backtest (section 8).

## 8. Validation

- **Unit tests**: accrued interest; price/yield round trip to 1e-10 with the single pricing function; CF formula vs CME table for ZN, ZB and UB; delivery calendars, and option expiry dates vs CME's published calendar; a bond crossing the 25-year ZB/UB boundary between contract months; a note crossing the ZN grade change (91282CFV8, 4⅛% Nov 2032: 9.46y remaining for June 2023, deliverable under the 10-year cap; 9.21y for September 2023, not deliverable under the 8-year cap); forward price vs carry hand calculation including a coupon between today and delivery; settlement on a coupon date; end-of-month maturities; crossover root-finding on a synthetic two-bond basket with a known answer; term repo compounding; region-weighted DV01 vs finite-difference on a synthetic basket.
- **Independent checks**: a handful of bonds vs QuantLib (test dependency only) or TreasuryDirect published values.
- **Sanity**: on a flat 6% curve all converted prices ≈ 100; below 6% low-duration bonds are CTD, above 6% high-duration.
- **Backtest**: run historical mode over past cycles with large moves (2022–23; the 2026 long-end sell-off). Score probabilities against the actual CTD at delivery (Brier score and a reliability plot; published as the calibration output, section 6). The actual CTD is computed from prices: on each delivery day, the bond with the smallest gross basis (cash price − futures × CF). The final futures price is fixed on the last trading day, but the CTD can still change over the last 7 delivery days. Flag a cycle as ambiguous when the two smallest bases are within price noise (TreasuryDirect prices are rounded and struck at a different time from the futures settlement). Exclude ambiguous cycles from scoring. CME delivery reports are not part of the core build (CME posts only the current month, so there is no history); a report saved by hand during a delivery month is an optional validation input ([outputs.md](outputs.md), Data dependencies). Check that the model shows the switches reported in 2026 (ZB moving along the basket in August and October). Score each contract separately. ZN cycles before September 2023 use the old 6.5–10y grade; report them apart from later cycles.
- **Sensitivity**: β ± 0.05; horizon first vs last delivery; vol ± 10%; smile-implied vs ATM-normal probabilities; interpolated vs √T vol; convolution vs rescaling to the horizon; grid tolerance and cap; flat vs stripped repo; GC vs 50bp special CTD repo; with vs without `c_i`.
- **Cross-check**: dealer/Bloomberg CTD scenarios when available.

## 9. Known limitations

- One factor: independent slope moves only approximated (5.7); probabilities near closely spaced crossovers unreliable.
- Free bond prices are lagged and rounded; a few ticks of noise moves crossovers.
- No CTD-specific repo: GC for all bonds; specialness ignored.
- No fair value, so no model-to-market check on inputs.
- Vol interpolation across contracts uses different underlyings (different CTDs, embedded switch options).
- Option-implied probabilities are risk-neutral, measured at option expiry, and on futures prices rather than bonds; extended to the horizon by an assumed normal increment.
- Far tails come from SABR extrapolation and can be inflated by rich or floor-priced wing settlements; probabilities for far crossovers are flagged as extrapolated.
- UB options are thinner than ZN and ZB options; on some days UB vol will come from ZB through betas, or from realised vol.
- Only ZN, TN, ZB and UB are modelled. Other contracts have collected data but need reference data and validation before use.
- American exercise is ignored when inverting out-of-the-money option prices.
- Historical mode uses GC repo only, and its option-implied inputs end with the one-off backfill (2026-10-19); later dates rely on the daily bulletin.

## 10. Roadmap

1. **Phase 1, deterministic core** (ZN, ZB): raw data store and fetchers, bond math with tests, CF formula (tested against saved CME tables), term GC repo (flat), forward prices, parallel-shift grid and crossovers (no probabilities). Check against published switch levels. **Before anything else, start the scheduled daily collection in section 3.2 (all six contracts, full options chains, SOFR and fed funds futures, TreasuryDirect prices), with manifests and gap alerts.** Reference data (grades, calendars, option products) for ZN, ZB and UB.

   **Phase 1b, light model (5.11)**: switch points as futures prices and CTD probabilities from put-spread digitals, for ZNZ6 and ZBZ6, built one date at a time starting with 2026-10-21 (a complete snapshot in the store). Every run is `ctd run --contract ZBZ6 --asof D`, reading only from the store, so later dates are a loop. Progress is tracked by the checkboxes below; tick an item in the commit that finishes it.

   *A. Foundation (phase 1 items the light model needs)*
   1. [x] Dates and conventions (`bonds/schedule.py`): coupon schedule from maturity (scheduled, unadjusted; end-of-month maturities), actual/actual accrued, previous/next coupon, T+1 settlement on the `sifma` calendar.
   2. [x] The single pricing function (`bonds/pricing.py`, 5.1): dirty price from yield, clean = dirty − accrued, yield from price by root-finding, DV01/duration from the same function.
   3. [x] CF formula (`bonds/conversionfactor.py`), tested against the stored TCF files: matches every row from December 2023 (the light model reads CFs from TCF, but the test checks the date code).
   4. [x] Store readers (`parse`/`read` in each source's module in `data/`, no network): TreasuryDirect prices with coupon and maturity (end of day, or the buy/sell midpoint for a provisional date, [decisions.md](decisions.md)); TCF basket and CFs per contract; CME futures settlements (`F_market`); SOFR from the NY Fed.
   5. [x] Delivery calendar per contract month (first and last delivery days, last trading day), stored as reference data (`reference/data/delivery_calendar.toml`, section 2): Z6 verified, H7 generated.
   6. [x] Flat-SOFR term repo (`funding/repo.py`) and forward clean price and yield with coupons before delivery (`bonds/forward.py`, 5.3); delivery date by the light-model rule (`model/horizon.py`).
   7. [x] Envelope and switch points (`model/envelope.py`): parallel shifts, cheapest converted price, exact root-finding of each switch.

   *B. Light-model pieces*
   1. [x] Option reference data (`reference/options.py`, `reference/data/option_expiries.toml`): expiry and underlying contract per standard expiry for ZN, TN, ZB and UB, NOV26 to JUN27, generated from the CBOT rule and checked against the last trade dates printed on page 1 of Section 42. Strike interval and premium tick are read from the chain, not stored.
   2. [x] Section 42 parser (`cme_bulletin.parse_options`, section 11 has the layout): standard blocks for ZT, ZF, ZN, ZB and UB, weeklies and TN skipped; per-block checks (strikes increasing, volume and open interest equal to the TOTAL line, trade date = as-of); strike and premium codes decoded per product. Parses every stored bulletin (2026-10-16 to 10-22, about 1,700 settlements each) and reproduces the 2026-10-16 hand check.
   3. [x] Digitals (`vol/digitals.py`): SOFR discount factor to expiry; out-of-the-money options (puts below the futures price, calls above); each pair of neighbouring priced strikes gives a digital at its midpoint, interpolated linearly to `K_k`; a missing strike widens the pair; a `K_k` beyond the listed strikes gets no value, flagged; the strikes used that traded that day (volume above zero) and those with no open interest are recorded, not flagged (results schema 10; [decisions.md](decisions.md), Option strikes with no open interest). A cabinet (`CAB` in the bulletin, 0.001 in Databento) or minimum-tick settlement only says the option is worth less than about one tick, so anything touching one is reported as an upper bound ("≤ 3%": 1/64 over a ½-point gap), not a probability. So is a pair with equal settlements, a floor in the wings (ZN puts from 98.5 to 100.5 all at 2/64 on 2026-10-16): once rounded they are at most one tick apart (added with B5). Tested against a normal option model with known probabilities: interpolation error is a few tenths of a point, 64ths rounding about 1–2 points. Later refinement: tighten bounds with a priced strike further out.
   4. [x] Probability assembly (`model/probabilities.py`): `K_k = F_market + E(z_k) − E(0)`; regions on each side (the bond beyond switch k gets `D_k − D_{k+1}`), remainder to the current CTD; checks that probabilities sum to 1 and fall with distance (warn and clip otherwise). An upper-bound digital is the interval [0, bound] and a missing one (beyond the listed strikes) [0, the digital inward], so every probability is an interval, a point when both ends agree. Tested against a normal option model (within 1 point) and on synthetic digitals.
   5. [x] Output: `ctd run` prints a basket table and a crossover table (from → to bond, shift in bp, `K_k`, strikes used, digital, region probabilities, warnings) and the recentring gap `F_market − E(0)`. The run is `model/light.py` (pure, inputs read by `cli.light_inputs`), printed by `report/light.py`; it stops with an error once the contract's quarterly options have expired. Shifts are applied to forward yields (the proposal in D). An upper bound outside a smaller digital is capped at it, as a missing digital is. Runs on every stored date from 2026-10-16 to 10-22 for ZNZ6 and ZBZ6. Recentring gaps: ZBZ6 −3 to −15/32 (futures below the cheapest converted forward, as the delivery options imply), ZNZ6 −3 to +4/32.
   6. [x] Run 2026-10-16 to date for ZNZ6 and ZBZ6, then daily. The series was to start 2026-10-16, the first stored Section 42 bulletin; phase 1d took it back to 2026-09-01 from the derived tables, and all four December contracts have saved results for every date to 10-23. The daily run is by hand, not scheduled: date D needs its CME files (the bookmarklet click the next morning) and its SOFR (published the next morning, B7), so it runs on D+1 after both, with `ctd ingest` then `ctd history --contract ZBZ6 --contract ZNZ6 ... --from D --to D`. A scheduled run after the evening fetch would fail on any day the click hasn't happened yet.
   7. [x] Morning SOFR fetch. A date's SOFR is published at about 8am the next business day and stored under that day's as-of date ([decisions.md](decisions.md), Which data a run uses), but the only scheduled fetch ran at 19:00, so a run for D made before D+1's evening fetch took D−1's SOFR and warned (2026-10-23's results, run on 10-26 after a midday fetch). The scheduled task `ctd-morning-sofr` (`scripts/register_morning_tasks.ps1`) runs `scripts/morning_sofr.py` at 09:15 Eastern on weekdays: it stores only `nyfed_rates` under today's as-of date, and only once the previous `sifma` business day's fixing is published, so a file without it can't make the evening fetch skip and hold the run back a day. Other sources are left out of that manifest, not recorded as missing; the evening fetch adds them and finds the NY Fed file stored. No change to the readers: `nyfed.read_known` already takes D's fixing from files stored after D. A same-day revision by the NY Fed (rare) now arrives a day later, in the next morning's file.

   *C. Definition of done*
   - [x] Section 8 unit tests for the pieces built: accrued, price/yield round trip, CF formula vs TCF, forward price across a coupon, synthetic two-bond crossover, term repo compounding; plus the parser on a stored bulletin. Also in place: the 91282CFV8 grade change, the 25y ZB/UB boundary, settlement on a coupon date, month-end maturities, delivery calendars, option expiries against Section 42's page 1, and region-weighted DV01 against finite differences.
   - [x] Sanity: flat 6% curve gives converted prices ≈ 100.
   - [x] ZBZ6 and ZNZ6 on 2026-10-21: plausible switch points and CTD, probabilities summing to 1 and falling with distance, results reproducible from the store. ZBZ6: CTD the 5% May-45, switches at −19bp (rally, to the 4⅝% May-44) and +6bp (sell-off, to the 4⅝% Nov-45), digitals falling outward on each side (rally 24.2%, 23.8%, 19.5%; sell-off 40.5%, 38.8%, 19.8%, 6.4%), region probabilities summing to 100%. ZNZ6: CTD the 4½% Aug-33 at 63%, the 3⅞% Aug-33 at 34% beyond +10bp, the 2034s each ≤ 3.1%; no rally switch in range. A re-run on 2026-10-26 at a later commit reproduced both saved files exactly apart from the code version and run time.
   - [x] A series from 2026-10-16 that runs daily (from 2026-09-01, run by hand each morning; B6).

   *D. Open questions for phase 1b*
   - **Which yield to shift**: forward yields (consistent with the full model, 5.6) or today's yields. Proposed: forward yields.
   - **Recentring gap**: `F_market` settles at 2pm CT and TreasuryDirect prices are struck earlier, so `F_market − E(0)` also absorbs that timing difference. Log it daily; what size counts as inconsistent inputs?
   - **Saved results** (decided): `ctd run` prints and also writes one JSON file per contract and date, `data/results/light/ZBZ6/2026-10-21.json` (`report/results.py`; `--no-save` prints only). It holds the header (horizon and why, SOFR, `F_market`, `E(0)`, the gap, option expiry and DF), every basket bond with its probability, every crossover with its strike, digital and region, and the warnings. A result is derived, so a re-run overwrites it; to tell runs apart it records the raw files read (source, unit, name, sha256) and the code version (`git describe --dirty`). A series is the files of one contract in date order (`results.read_light`); B6 builds on it. JSON rather than Parquet: one small file per run, readable by eye, and a derived table can be built from them later if a series needs one.
   - **Which TreasuryDirect snapshot matches the futures settlement** (answered 2026-10-26: end of day, the closer of the two by far; [decisions.md](decisions.md), Which TreasuryDirect price the model uses): the model uses end of day ([decisions.md](decisions.md)). Confirm it on a few dates: compare the CTD's gross basis from end of day and from buy/sell against the 2pm CT settlement (the snapshot taken at the same time shows the least correlation between basis changes and futures changes), and find TreasuryDirect's own definition of the columns. Evidence from phase 1d item 5 (2026-10-26): the gap's daily changes are one yield offset common to all four contracts (correlation 0.96–0.98 in bp, standard deviation 1.1–1.6bp, up to 3.6bp), barely related to the day's move. Which way round the two times are is not yet known. Re-running the light model on the buy/sell midpoint instead triples it (3.5bp), so end of day is the nearer snapshot, and the 1.3bp left is the timing gap it still has. It could be removed by centring on yields consistent with the futures settlements rather than recentring each switch strike.
   - **After December option expiry** (decided): roll at option expiry. ZBZ6 and ZNZ6 run through 2026-11-19, ZBH7 and ZNH7 with MAR27 options from 2026-11-20; the March contracts also run alongside from now for the roll comparison ([decisions.md](decisions.md), When December options expire).

   **Phase 1c, single-date outputs**: Tier 1 for one date, without time series ([outputs.md](outputs.md)), for ZNZ6 and ZBZ6 and then the March contracts. Charts use a normal factor with β = 1 and ATM vol, with the light model's digitals as a cross-check ([decisions.md](decisions.md), Probabilities in the published charts); rendered as matplotlib PNGs in one HTML page per date ([decisions.md](decisions.md), Chart rendering).
   1. [x] Futures DV01 (`risk/dv01.py`): per bond DV01/CF at the forward yield, probability-weighted and CTD-based, in $/bp per $100mm notional (and per contract, from `face` in `cme_products.toml`). Interval probabilities give the exact DV01 range they allow. Printed by `ctd run` and saved (results schema 2). Weighted at z = 0 with the light model's probabilities, so each bond's DV01 is taken at today's forward yield rather than where it becomes CTD; region-weighting (item 4) replaces this. ZBZ6 on 2026-10-21: $134,000 per $100mm probability-weighted against $124,000 CTD-based (the low-coupon sell-off contenders have DV01/CF up to $190,000); ZNZ6 on 10-16: $60,400 against $59,900.
   2. [x] Par curve and bond KRDs (`curve/par.py`, `risk/krd.py`, reader `par_curve.read_latest`): linear par interpolation, bootstrap, tent bumps, shares scaled to each bond's DV01 ([decisions.md](decisions.md), How KRDs are computed); probability-weighted and CTD-based KRDs and effective maturity, printed by `ctd run` and saved (results schema 3). Interval probabilities enter the KRDs as midpoints rescaled to sum to 1, with a warning only when they could move effective maturity by more than 0.05y (at most 0.04y on the stored dates, so far never). Tested: the bootstrap reprices par bonds at par, a par bond on a node loads only on it, the 2¼% Aug-46 matches the decisions.md comparison. ZBZ6 on 2026-10-21: effective maturity 19.9y probability-weighted against 18.6y CTD-based, with $13,300 at 25y from the 1⅜% 2050; ZNZ6 6.8y against 6.7y. KRDs per cluster (5.9: same dominant key rate, DV01 within 5%; members weighted by probability), printed and saved (results schema 4): ZBZ6's clusters run from 17.2y to 27.9y effective maturity and $120k to $190k per $100mm. A warning when the par curve predates the as-of date.
   3. [x] ATM vol (`vol/atm.py`): implied vol of the at-the-money quarterly option, converted to yield vol with the CTD's DV01/CF at that expiry's underlying (5.5), scaled to the horizon by √T; distance to switch in σ. Written per expiry, so item 7 can add a second one. For the cross-check at today's state (no shift of the centre; `c = 0` in item 4) against the light model's digitals, use the width at option expiry, not at the horizon, so the gap measures skew rather than the extra time to delivery. Normal (Bachelier) implied vol of the out-of-the-money put below and call at or above the futures price, interpolated linearly in strike to it; time in calendar days over 365. `ctd run` prints the vol, the widths to the horizon and to expiry, the nearest switch on each side in bp and σ (flagged below 1σ), and per crossover its σ and its normal tail at expiry next to the digital; saved in results schema 5. ZBZ6 on 2026-10-21: 12.7 points per √year, 102bp per √year in yield, a 45bp width to the 31 December horizon; the normal tails run 1–3 points above the digitals. ZNZ6: 109bp per √year, 48bp.
   4. [x] Shifted-state model (`model/profile.py`): for each centre `c` from −100 to +100bp, probabilities as the normal mass of each CTD region on the envelope, and region-weighted DV01 and KRDs (5.9) evaluated where each bond is CTD; ±1σ and ±2σ as points; the change in each KRD at those points; vol ±10% bands. With β = 1 the switches don't move with `c`, so the shift axis is cut once into cells of at most 1bp with every switch as an edge, each carrying its CTD's DV01/CF and KRDs at the shifted forward yield and a par curve shifted by the same amount; a state's weights are the cells' exact normal masses, so probabilities are exact Φ differences between switches. The cells reach ±(100bp or 2σ, + 6 widths at vol +10%). The state at 0 is now the headline DV01 and KRDs; item 1's z = 0 weighting with the option-implied probabilities stays as the cross-check. `ctd run` prints the states at −2σ to +2σ (shift, percentile, CTD at the shift, DV01 and CTD-based DV01, effective maturities) and the KRD changes from today, model and CTD-based; results schema 6 holds the whole profile. Tested: region-weighted DV01 against finite differences of the expected envelope (section 8), two-bond probabilities as normal tails, a narrow width giving the CTD-based staircase. ZBZ6 on 2026-10-21: $137,000 per $100mm today (vol ±10%: $136,100–137,700), $147,800 at +1σ against a CTD-based $172,100; at +1σ the model moves $66k per $100mm into the 25y bucket where the CTD-based jumps $197k. Found while testing: against the par curve, a fixed-coupon bond's effective maturity *lengthens* as yields rise (a discount bond sits beyond its maturity, a par bond on it), the opposite of a cash-flow-weighted maturity; outputs.md chart 3 (effect 3) corrected to match.
   5. [x] Charts and report (`report/charts.py`, `report/page.py`, `ctd report [--asof] [--contract ...] [--out]`): chart 1 (DV01 profile with bp and percentile axes, CTD-based staircase, bucket shares allowing negatives), chart 2 (diverging KRD change bars), tables (probabilities from both models, DV01 vs CTD-based DV01, distance to switch), one self-contained HTML page per date in `/output/`. Drawn from the saved results only (schema 8 or later, which adds the delivery window and the carry behind the horizon; an older file is refused with a request to re-run), every contract saved for the date in `cme_products.toml` order, charts as small multiples. The summary gives each contract's CTD with P(RCaD), the probability that it remains CTD at the implied delivery date, from both models (the digitals can only measure it at option expiry), and the implied delivery date (a column, with the carry rule as a footnote). Chart 1: the region-weighted DV01 with the vol ±10% band, the CTD-based staircase and the ±1σ/±2σ states as points with guides through both panels; below, each bucket's share of the DV01 as a heatmap, one row per bucket, positive shares blue and negative gray (ZBZ6's low-coupon contenders take its short buckets to −35% in all at +100bp; first drawn as stacked bands, changed for legibility, [decisions.md](decisions.md) Chart rendering). Chart 2: the four states' bars per bucket (blue rally, red sell-off), the CTD-based change as a marker; end buckets under 0.5% of today's DV01 in every state are left out (ZN's 15y to 30y). Tables per contract: the states (DV01, CTD-based DV01 and effective maturities), the KRDs today and their changes (chart 2's numbers), the probabilities (digitals and ATM normal), every switch with its σ, digital and normal tail (flagged below 1σ), and the inputs and warnings. PNGs carry no version stamp, so the same result redraws the same bytes. Tested: the page holds both charts and every table per contract, refuses an old schema, and the command writes the date's page in contract order.
   6. [ ] March contracts (ZBH7, ZNH7 with MAR27 options) through items 1–5, and the roll comparison: DV01 and KRDs of December and March on the same date.
   7. [ ] Total-variance vol interpolation (5.5 step 3, brought forward from phase 3): the January serial (on March futures, about 24 December) as a second expiry, converted with the March CTD's DV01/CF from item 6; `V(T) = σ²T` linear between the December quarterly and the January serial, so the extra weeks to delivery (with the December FOMC) get their own priced variance rather than √T. No beta adjustment for the March CTD's different maturity while β = 1 (slightly off for ZB). √T from a single expiry stays as the fallback. Why √T alone isn't enough: on 2026-10-25 the December options cover 26 days of a 67-day horizon, and a 20% error in the extrapolated vol moves S by about 10%, a switch 1σ away by about ±2.5 points.
   8. [x] Repo from the SR1 strip (`funding/strip.py`, 5.3 path 3; [decisions.md](decisions.md), Repo path for the light model): each month flat at the rate that reprices its SR1 average after the month's known fixings and the days carried in from the month before; flat SOFR as the fallback with a warning, and as a cross-check on the horizon. Readers: `read_futures(..., "cme_stir")`, `nyfed.read_known` (fixings from earlier as-of dates' files). Printed by `ctd run` and saved (results schema 7). Tested: a flat strip gives back flat SOFR, each month reprices its average including carried-in weekend and holiday days, missing months and fixings fall back. ZBZ6 on 2026-10-21: 4.02% to the 31 December horizon against 3.89% flat, horizon and CTD unchanged. Path 2 (FOMC steps, year-end turn) is deferred. The extra SR1 months for history are bought and in the derived futures table (data.md §5.13), not yet read by `ctd run`.
   **Phase 1d, historical trial run (2026-09-01 to date)**: the start is a choice, not a data limit: a contract is run only once it is liquid, from the previous contract's roll (late August for December), and the futures data would reach back to 2026-06-18 ([decisions.md](decisions.md), Which dates a contract is run for). The light model and phase 1c outputs run back through September for ZBZ6 and ZNZ6, the first use of the derived tables in a run. A good trial: one contract throughout (the December contracts and their DEC26 quarterly options are live all period), a volatile stretch for rates from early September, and the live dates from 2026-10-16 as a check. The model is unchanged (β = 1, ATM vol with √T, SR1 strip): only where the inputs come from changes. Checked 2026-10-26: every business day from 2026-09-01 has ZBZ6 and ZNZ6 settlements, 7 or 8 SR1 months and the DEC26 chains (134 to 150 ZB rows, 218 to 232 ZN) in the derived tables, plus the TreasuryDirect file and TCF under its own as-of date.
   1. [x] Inputs from the derived tables. `cli.light_inputs` reads futures, SR1, options, the par curve and SOFR fixings from the `futures`, `options`, `par_curve` and `rates` tables, filtered to dates on or before the as-of date; TreasuryDirect prices and the TCF basket stay as they are (stored under every date). Needed because before 2026-10-14 there are no CME pages or bulletins, no par curve file is stored under a September date, and `nyfed.read_known` only looks at files within two weeks of the date, which the 2026-10-19 backfill isn't. The option rows map onto `OptionSettle` with no delta, which the model doesn't use. **Decided (2026-10-26): history only for now, by date.** A run for a date before 2026-10-16 (the first date with every live source: futures pages from 10-14, the bulletin from 10-16) reads the derived tables; from 10-16 it reads the raw pages, so daily runs don't depend on `ctd derive`. `ctd history` is a loop over `ctd run`, so the path depends only on the date and a date's saved result never changes path. Once a daily Databento download is set up (section 11, which feed), every run switches to the derived tables and the raw-page path is retired, leaving one way of loading inputs. Readers: `futures.settlements`, `options.chain`, `rates.par_latest` and `rates.fixings` in `data/derived/`; each also returns the sources its rows came from (item 3). ZBZ6 and ZNZ6 run on 2026-09-01 without warnings (ZBZ6: CTD the 5% May-45 at 36%, switches −22bp and +11bp; ZNZ6: recentring gap −0.6/32).
   2. [x] Same answer on the live dates. `ctd run --inputs derived` forces the derived path on any date (`--inputs raw` is the live path; the default picks by date); with `--no-save`, re-run 2026-10-16 to 10-23 and compare with the saved results (raw pages). It is also the test for the eventual switch: every number should agree, since the derived tables match the raw pages on the overlap. Any difference is a reader bug to fix before going back further. Done 2026-10-26 for ZBZ6, ZNZ6, UBZ6 and TNZ6: every saved result from 10-16 to 10-22 reproduced exactly (all fields but the inputs list, code version and run time). The saved 10-23 results differ because they were run before 10-23's SOFR was stored (3.90% of 10-22 against 3.92%; item B7); a fresh raw-path run for 10-23 agrees exactly with the derived path, and 10-23 is re-saved.
   3. [x] Provenance for derived inputs. A result lists the raw files it read with their sha256; for a derived table, record the table, the winning source and the raw files of the units the rows came from (from the derived store's state), so a September result still names its raw files (the Databento backfill files, for most inputs). Results schema 9: each file read through a derived table is listed like any other raw file (source, unit, name, sha256, the as-of date it's stored under) plus the `table` (`DerivedStore.raw_files`: the units of the rows read, from the staging tables, and each unit's files from `_build.json`). A unit lists every file it was built from, so the list can be generous: ZN's options unit also names the small 2026-10-16 to 10-20 Databento test pull, and SOFR names every NY Fed file, since the latest pull wins. ZBZ6 on 2026-09-01: 22 files.
   4. [x] `ctd history --contract ZBZ6 --from 2026-09-01 --to 2026-10-23`: `ctd run` for each `cme` business day, saving each result, carrying on past a failed date and ending with a summary (dates run, failed with the reason, warning counts). Then ZNZ6, and UBZ6 and TNZ6 if they run cleanly. Built (`cli.cmd_history`; `--contract` repeats, `--no-save`, `--inputs` as for run): one line per date (CTD and its probability, DV01 against CTD-based, recentring gap, nearest switch each side, warning count), then per contract the dates run, failures with the reason, and warnings grouped by wording (`warning_kind`). Days the bond market is closed but CME isn't (Columbus Day, 2026-10-12) are skipped and listed: no TreasuryDirect prices. Run 2026-10-26 for all four December contracts, 37 dates each (2026-09-01 to 10-23), all saved, none failed. For item 5: ZBZ6's CTD moves through five bonds (the 5% May-45, the 4⅝% Nov-44 and the 4⅞% Aug-45, then the 3% Nov-44 and 2½% Feb-45 from late September to 10-13, back to the 2045s from 10-14), with near-ties (switches within 2bp) on 09-25, 10-13 and 10-19; recentring gap +2.3 to −15.8/32. ZNZ6 alternates between the 4½% Aug-33 and the 3⅞% Aug-33; 12 dates warn that flat SOFR would move the horizon, 3 that a basket bond has no TreasuryDirect price, 1 that probabilities don't sum to 1. Zero-open-interest warnings come only before 10-16 (ZBZ6 3, UBZ6 54, TNZ6 48; none after): Databento keeps the strikes with no open interest that the bulletin leaves out, so the chains differ in kind at the seam.
   5. [x] Review the series: probabilities sum to 1 and fall with distance on every date; the recentring gap's range against October's (−3 to −15/32 for ZBZ6); warnings by type; continuity across 2026-10-15/10-16, where the options switch from Databento to the bulletin (Databento also has the far strikes the bulletin leaves out, so more zero-open-interest flags before the switch); every CTD switch in the period checked against the yield moves that day. **Decided (2026-10-26):** the strikes with no open interest stay in the chains; zero open interest is no longer a warning, and each digital and the ATM vol record which of their strikes traded that day, shown in every output with the caveat that all option numbers come from CME settlements (option-implied, not traded); measurements, the CME procedure and the caveats are in [decisions.md](decisions.md), Option strikes with no open interest.
      **Review (2026-10-26, 37 dates × 4 contracts, 2026-09-01 to 10-23):**
      - *Checks that pass.* Probabilities sum to 1 and fall with distance on every date but one (ZNZ6 on 10-19, a live date: two switches 2.7bp apart, wing digitals 4.2% and 3.2% from 64ths-rounded puts, clipped as designed; sum 1.010). Across the 10-15/10-16 seam the headline DV01 moves as on any other day (ZBZ6 137.8 to 138.0k, ZNZ6 61.4 to 61.1k, UBZ6 and TNZ6 unchanged). The 3 ZNZ6 warnings for a basket bond with no TreasuryDirect price (09-25 to 09-29) are the new 7-year 5% Sep-33 (91282CRM5), in CME's basket from the day after its 09-24 auction and issued 09-30; once priced it converts 0.16–0.27 points above the CTD and never gets a probability.
      - *CTD path.* ZBZ6's CTD moves to the low-coupon bonds as its forward yield rises from 5.35% (09-22) to 5.78% (10-05) and back as it falls: the 2⅞% Aug-45, 3% Nov-44 and 2½% Feb-45 hold it from 09-28 to 10-13, the 2045 coupon bonds before and after. UBZ6 does the same (TG3, TD0 from 10-02 to 10-09); TNZ6's CTD never changes. Taking the day's move as the change in yesterday's CTD's forward yield, yesterday's envelope predicts today's CTD on 25 of 36 days for ZBZ6, 33 for UBZ6, 36 for TNZ6 and 22 for ZNZ6. The misses are near-ties (ZBZ6: 4 of 7 days after a switch within 5bp) and relative moves a parallel shift can't capture; ZNZ6's are the horizon flips below. Meanwhile the headline DV01 moves smoothly: ZBZ6's CTD-based DV01 drops from 138.5k to 122.0k on 10-14 as the CTD flips from the 2½% Feb-45 to the 4⅝% Nov-44, the probability-weighted from 140.9k to 139.9k.
      - **Finding 1: the implied delivery date flips with the CTD.** The rule takes the horizon from the CTD's carry, so when the CTD alternates between bonds with opposite carry the horizon jumps a month: ZNZ6 between the 4½% and 3⅞% Aug-33s 13 times (every CTD flip; 12 dates warn that flat SOFR would choose the other date), ZBZ6 and UBZ6 twice each. The width to the horizon jumps with √T, about 22% (ZNZ6 60bp to 48bp on 10-01), and so do the normal-model probabilities and the "implied delivery" shown in the report; the headline DV01 barely moves (ZNZ6 $400 per $100mm on flip days, $90 otherwise). **Decided (2026-10-26): probability-weighted carry**, weighted by the option-implied probabilities with the envelope at the last delivery day; re-run, the date no longer moves for ZBZ6, UBZ6 or TNZ6, and ZNZ6 moves 6 times instead of 13 (three single days), its two Aug-33s being genuinely ambiguous ([decisions.md](decisions.md), Delivery date for the light model's forward prices).
      - **Finding 2: the recentring gap's daily noise is one yield offset common to all contracts.** Daily gap changes correlate 0.91–0.95 across the four contracts but only 0.1–0.2 with the day's yield move. In yield terms (gap change over the CTD's DV01/CF) each contract tracks the four-contract average with correlation 0.96–0.98 and slope 0.8–1.2, standard deviation 1.1–1.6bp, largest −3.6bp (09-25), +2.8bp (10-22). The same yield gap between the TreasuryDirect prices and the 2pm CT futures settlement, every day, is what a snapshot-timing mismatch would produce; see phase 1b D, Which TreasuryDirect snapshot matches the futures settlement. The gap's level is the delivery options (ZBZ6 mean −8.3/32, UBZ6 −5.7/32, ZNZ6 and TNZ6 about 0).
   6. [ ] A first time-series view, the seed of chart 3 ([outputs.md](outputs.md)): probability-weighted against CTD-based DV01, CTD probabilities stacked, and distance to the nearest switch in σ, by date, read from the saved results (`results.read_light`). A notebook first; into `report/` once the layout settles. Single-date pages need nothing new: `ctd report --asof` works for any date with saved results.

   **Phase 1e, daily CME collection from Databento**: replaces the bookmarklet as the record for CME futures and option settlements, so the daily run no longer waits for a manual click ([decisions.md](decisions.md), Daily CME collection from Databento). The CME pages and the Section 42 bulletin stay as a free secondary source.
   1. [x] Fetcher and source `databento_daily` (`data/databento_daily.py`, registered in `registry.py`): dataset `GLBX.MDP3`, schema `statistics`, the front two contracts of ZT, ZF, ZN, TN, ZB and UB and the front seven SR1 months (`<P>.c.k`, `stype_in=continuous`; no SR3 or ZQ, [decisions.md](decisions.md)), and parents `O<P>.OPT` for the six option products (`stype_in=parent`; weeklies not collected), one unit per product. One file per as-of date D covering a fixed window, 00:00 Chicago time on D to 00:00 on the next `cme` business day, so every record lands in exactly one file (Friday's runs to Monday and catches the Sunday finals). Stored with the free `symbology.resolve` lookup for the same window. Store a date only once `metadata.get_dataset_range` has passed the window's end (otherwise `missing`, retried by `--catch-up`) and its `get_dataset_condition` is `available`; `degraded` is stored and flagged in the manifest. Recovery window unlimited: any past date can be bought again. Not stored either if a futures contract lacks a final or open interest, or the options have no finals. First pull 2026-10-26 (run by hand on 10-27: all 13 units, $0.037, 10 minutes; data.md 5.14).
   2. [x] Option definitions for new instruments only: after the statistics pull, request `definition` by `instrument_id` for the (id, raw symbol) pairs not in any stored definitions file (ids are reused, so the pair is the key), over the session that lists them. Start from one full-session definitions pull ($0.11). Futures need none: contract codes come from the symbology lookup and expiries from `reference/`, as in the backfill.
   3. [x] Readers: `databento.read_daily_futures` and `read_daily_options` take one date's files: its statistics (records for that trade date only; the window already holds the whole settlement window, Sunday finals included) and, once stored, the next business day's, which brings the revised open interest (sent about 09:05 CT the next day; until then the evening's first figure), as with the CME pages. Options match each settlement to its contract by (instrument id, raw symbol) on the date, through the date's lookup and every definitions file up to it.
   4. [x] Derived tables: `databento_daily` wins futures (Treasuries and SR1; SR3 and ZQ stay with `cme_stir`) and options from 2026-10-26; the CME pages and the bulletin become cross-checks in the `overlap` report and never fill its gaps. A unit is one date and product, listing the next day's statistics file, so storing it re-reads the date. 2026-10-26 built on 10-27; the light model runs on it from the derived tables (ZBZ6 $136,200 per $100mm).
   5. [ ] Morning tasks (`scripts/register_morning_tasks.ps1`, data.md §4), all for the previous business day D, each with its own log: `ctd-daily-fetch` at 09:00 (every other daily source, moved from 19:00 so TreasuryDirect's file has end-of-day prices; `--skip-source databento_daily`), `ctd-morning-sofr` and `ctd-morning-databento` at 09:15, then `ctd-morning-derive` at 09:30 (`scripts/morning_derive.py`), which derives once D's data is in the store and otherwise, after an hour, skips with an alert ([decisions.md](decisions.md), When the morning derive may run). `ctd run --asof D` for the published contracts and `ctd report --asof D` are started by hand afterwards. Tick once a first morning has collected and derived cleanly.
   6. [x] Every run reads the derived tables by default (2026-10-27): `ctd run` and `ctd history` take `--inputs derived` (default) or `--inputs raw`, the date's own CME pages, bulletin and files, kept as a cross-check for dates with a bookmarklet click; the date rule of phase 1d item 1 (raw from 2026-10-16) is gone. 2026-10-26, which has no CME files, runs only this way.
   7. [ ] Run alongside the bookmarklet for about two weeks with clean overlaps, then make Databento the record in CLAUDE.md, section 3 and data.md. Bookmarklet files stay a secondary source: any date not clicked is a permanent gap there, since CME serves only recent settlement pages and the latest bulletin.
   8. [ ] Later: buy `databento_daily` back from 2026-10-20 (options; the option backfill ends 10-19, the futures backfill 10-21) to the first daily date, about $0.15 a day. Until then options are Databento to 10-15, the bulletin from 10-16, then Databento, and the bulletin dates lack the strikes with no open interest. Measured effect: none on the headline numbers, which use ATM vol only; far-wing digitals move up to 1 point, mostly UB and TN ([decisions.md](decisions.md), Option strikes with no open interest).

2. **Phase 2, one-factor model**: betas, vol calibration (single expiry, √T), probabilities, region-weighted DV01 and KRDs, scenarios and duration profile, comparison series and effective maturity, distance to switch, event flags, daily report with charts 1–3. Phase 1c brings a minimal single-date version forward (β = 1, ATM vol); phase 2 adds betas, the time series and the December contract after its options expire. With the betas, replace the report's light-model wording (`LIGHT_MODEL_*` in `report/`: the page's opening paragraph and chart 1's shift axis), which describes the factor as the CTD's forward yield. The constant-CTD DV01 and effective maturity are post-processing over the saved results (each run already stores every bond's `dv01_cf` and `krd_shares`): the first file's CTD, read through the contract's later files. First on ZN and ZB, then UB and TN once they pass the phase-2 checks.

   **Derived tables** (section 4). Needed before any multi-date use of options or futures (vol history, light-model backtest, the roll).
   - [x] The layer: `DerivedStore`, staging and merged partitions, incremental build from raw-file hashes, precedence and overlap report, `ctd derive [--table] [--full] [--notify]`; tested on a synthetic table (incremental equals full, failures retried, version bumps).
   - [x] Futures table: CME pages (`cme_fut`, `cme_stir`) from 2026-10-14 and the Databento backfill before. On the overlap (2026-10-14 to 10-21) every settlement, contract code and open interest agrees once CME's open interest is moved back a day.
   - [x] Options table, Section 42 path: every stored bulletin from 2026-10-16, expiry from page 1.
   - [x] Options table, Databento path (`databento.read_options`): the option backfill read in chunks for 2016 to 2026-10-15, 15.3 million rows over six products in about 5½ minutes; cabinets (0.001, ZT 0.0005) as `settle` null. On the overlap (2026-10-16 and 10-19) every bulletin row is in Databento and none of the 3,280 differs in expiry, underlying month, settlement, cabinet, volume or open interest. Data quirks found and handled are in [data.md](data.md) §5.12.
   - [x] Missing trading days per product against the `cme` calendar (`holidays.csv`, derived from the data for 2016–2025), listed by every build.
   - [x] Options quality table (`options_quality`): stale, parity, cross-chain forward and strike-order checks per chain, so bad chains are skipped without diagnosis.
   - [x] TN options from the bulletin (its "ADDITIONAL" section), so TN has option rows from 2026-10-16 on.
   - [x] Bond prices (`bond_prices`, every TreasuryDirect row 2016 on, 1.1 million) and security terms (`securities`, one row per CUSIP); the engine's partition column is now per table (`type` for bonds).
   - [x] Par curve (`par_curve`, 1990 on) and reference rates (`rates`, 2018 on), each checked against FRED. Treasury's par curve also fixed the `sifma` calendar's Good Fridays.
   - [x] Baskets and CFs per contract month (`baskets`), rebuilt from the grade records (now all six contracts) and checked against every TCF file: no disagreement.
   - [ ] Run `ctd derive --notify` after the daily fetch (scheduled task).

   **First milestone (before the late-November 2026 roll):** Tier 1 for ZN and ZB plus the December/March roll comparison ([outputs.md](outputs.md)). Phase 1c gives the single-date outputs; the time series need phase 2. Chart 3's time series needs history: phase 1d takes it back to 2026-09-01 for the December contracts; further back waits for the historical runner (phase 4).
3. **Phase 3, refinements**: total-variance vol interpolation (if not done in phase 1c item 7), with the beta adjustment for the next contract's CTD; smile-implied distribution (SABR fit, digitals, envelope mapping, recentring, horizon convolution) with quantile-based grid window; slope adjustment by convolution; digital and ATM-normal diagnostics; horizon decision logic; stepped repo path (5.3 path 2, with the FOMC calendar and the year-end turn; the strip is built). Per-crossover vols (5.5.2) only as a stopgap if the smile fit lags.
4. **Phase 4, history and extensions**: basket rebuild, historical runner (implied vol from the Databento option history, realised vol as a comparison), backtest scoring and reliability plot; Tier 2 outputs and the fragility dashboard (with its new sources, section 3); two-/three-factor PCA simulation with idiosyncratic noise; other contracts (ZT, ZF) if wanted. Far down the wishlist: infer slope vol from market futures prices.

## 11. Open questions

- ~~How to collect CME settlements reliably? CME has no free download feed for settlements, and its public FTP server carries only the TCF tables of what's needed. Until a paid feed is chosen, futures settlement JSONs and the options bulletin are downloaded in a browser with the `ctd bookmarklet` (one click a day). Which feed, if any (DataMine, Databento, Barchart OnDemand)?~~ Answered 2026-10-27: a daily Databento pull at 09:15 Eastern the next business day, about $4 a year, with the bookmarklet files kept as a free secondary source (phase 1e; [decisions.md](decisions.md), Daily CME collection from Databento).
- Option settlements from the Section 42 PDF: tested on 2026-10-16 with pdfplumber and pypdf, and the text extracts cleanly (about 3,200 strike rows in 35 pages). Layout: a product and put/call header (e.g. "10Y NOTE CALL", or a weekly such as "HYO OPT WK THU"), then an expiry label ("DEC26"), then one row per strike: strike (1055 = 105.5), open, high, low, close, settlement, change, delta, exercises, volume, open interest, OI change, contract high and low, prices in 64ths. Each block ends in a TOTAL line. The header also states the trade date and FINAL. Check: the 100.5 ZN call in the November serial block (on December futures) settled at 4-61/64 with delta 1.000, against December futures at 105-14.5 (intrinsic 4.95); the December quarterly 100.5 call settled at 4-62/64. Parser written (phase 1b item B2, `cme_bulletin.parse_options`). Found while writing it: strike and premium codes differ by product (ZN, ZF, ZB, UB strikes in quarter-point codes, ZT in eighths; ZN, ZB, UB premiums in 64ths, ZT and ZF in halves of 64ths); `CAB` marks a cabinet settlement below one tick (about 400 rows a day, stored as no price); page 1 prints CME's last trade dates per expiry, which check `option_expiries.toml`. TN options, in the bulletin's "ADDITIONAL" section with calls and puts mixed, are parsed too (data.md §5.9).
- How long does CME keep TCF files on its FTP server (December 2023 onwards as of October 2026)? Low stakes: they could be dropped without issue. The light model's basket and CFs could come from the derived `baskets` table, which reproduces every stored TCF file; the files are kept only as validation and as the record of the day CME lists a new issue (data.md §5.7).
- Which beta window and decay best predicts realised basket moves (settle by backtest)?
- Realised-vol window for the comparison and fallback, and how realised compares with implied vol (testable over 2016–2026 with the option backfill)?
- How to estimate betas between the par curve's published points (1, 2, 3, 5, 7, 10, 20 and 30 years) is worked through in [decisions.md](decisions.md). Starting point: regress at the published tenors and interpolate β linearly, which equals interpolating the curve. No basket needs extrapolation: ZN's bonds sit between the 5, 7 and 10-year points, ZB's between 10, 20 and 30, and UB's (25 to 30 years) between 20 and 30. Still open: whether pooled bond-level betas (possible now, with TreasuryDirect prices stored from 2016) beat node betas in the backtest, and whether ZB should use a reference other than the 20-year CMT.
- Smile-implied distribution when the option expiry is after the horizon (5.5.1 step 5). A contract keeps trading for about a month after its own options expire (quarterly options expire in late November; December futures trade to mid-December and deliver to month-end), and its CTD question matters most then. Its vol then comes from the next contract's options (5.5 step 3).
  - **When it happens:** positive carry (horizon = last delivery day) usually still has two expiries bracketing the horizon, e.g. the January serial (~24 December) and the February serial (late January) for a 31 December horizon, so convolution from the January serial works. Negative carry (horizon = first delivery day) does not: after the December options expire, the first usable expiry is the January serial, three weeks after a 1 December horizon. The ATM path is unaffected, since the √T fallback in 5.5 step 3 already scales down.
  - **Interim choice:** rescale the factor distribution to the horizon, `z_h = z_E × √(V(T_h)/V(T_E))`. This keeps the expiry's skew unchanged, so if anything it overstates skew at the shorter horizon.
  - **Alternative:** deconvolve, fitting a horizon distribution `φ_h` so that `φ_h` convolved with `N(0, V(T_E) − V(T_h))` matches the expiry distribution. It is consistent with step 5 but ill-posed (noise in the fitted wings is amplified), so it is worth trying only if backtests show the rescaling biases tail probabilities.
  - **Also needed either way:** the expiry's distribution is on the *next* contract's futures, so step 3 maps it through that contract's envelope and the betas to the expiring contract's factor (as for the ATM vol in 5.5 step 3). The approximation is weakest for ZB, whose two contracts' CTDs can differ most.
  - **Open:** confirm with history how often this case arises (negative-carry dates after option expiry), and whether rescaling and deconvolution differ materially there.
- Option-implied percentile marks on chart 1, before the smile fit (phase 3). The phase 1c profile uses a normal factor with ATM vol ([decisions.md](decisions.md), Probabilities in the published charts), so its percentile axis is symmetric. An interim step: keep that profile, but add a second set of axis marks from the light model's digitals at c = 0. Compute a digital at every listed strike (not only at the crossover strikes), map each strike to z through the envelope (`z(K)` solving `E(z) − E(0) = K − F_market`, as in 5.11 step 2), and mark the 5th, 25th, 75th and 95th percentiles of the resulting CDF. The gap to the normal marks shows the skew the charts leave out, as the ATM-vs-smile diagnostic in 5.5.1 does. It reuses `vol/digitals.py` and `model/envelope.py`. It describes today's distribution only, so it labels the axis but doesn't feed the shifted-state weights. The rounding noise and upper bounds in the wings (5.11) fall where the outer percentiles sit. Open: whether it's worth building before phase 3, once chart 1 exists.
- How often are UB options too thin to use, and is ZB vol mapped through betas a good enough substitute?
- ~~Chart 3 before the historical runner exists: start the series at the first live run, or bring forward a minimal historical runner (realised vol, rebuilt baskets) for ZN and ZB before the first milestone?~~ Answered 2026-10-26: the light model runs back from the derived tables (phase 1d), so the December contracts' series starts on 2026-09-01; each contract is run only while liquid, from the previous contract's roll ([decisions.md](decisions.md), Which dates a contract is run for).
- What CME Pace of the Roll publishes and whether past rolls can be retrieved; month-level open interest already comes from the daily settlements.

Which further outputs to publish was settled in [outputs.md](outputs.md), which replaces the list of candidates that was here. Its "Dropped or reframed" table records what was dropped (basis-trade outputs) and what was reframed (market impact as gross duration transfer, gamma as the slope of the duration profile).
