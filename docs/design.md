# CTD Model: Design

End-of-day model of cheapest-to-deliver (CTD) probabilities and futures key rate durations for CBOT Treasury futures, from public data plus a small paid Databento feed for CME settlements, with a historical mode for time series. This is the spec: how the model works, and the reasons for each settled choice. What gets published is in [outputs.md](outputs.md), the data in [data.md](data.md), progress in [roadmap.md](roadmap.md) and open questions in [open-questions.md](open-questions.md).

## 1. Purpose, goals and non-goals

### Purpose
A duration-drift monitor for Treasury futures users ([outputs.md](outputs.md), Positioning). The model outputs probability-weighted futures DV01 and KRDs as a daily time series, a duration profile across factor shifts (with ±1σ and ±2σ as points on it), and the distance to the next CTD switch. CTD probabilities are the engine, published as a supporting series.

### Goals
- Contracts: **ZN, TN, ZB and UB**, all four modelled, validated and published alike (section 2). ZT and ZF are collected only. The model code is contract-agnostic, so other contracts can be added through reference data alone.
- For a given contract, estimate each deliverable bond's probability of being CTD at delivery.
- Locate the **crossover levels** (factor shifts at which the CTD changes hands) and group bonds into clusters with similar key rate profiles.
- Produce futures **DV01 and key rate DV01s**, probability-weighted and per cluster.
- Produce a **duration profile** (DV01 and KRDs across factor shifts), recomputing probabilities at each shifted state (5.9).
- Produce the **comparison series** asset managers need: CTD-based DV01 (what vendor systems report, which jumps when the CTD changes), constant-CTD DV01, and DV01-weighted effective maturity (5.9).
- Run daily from end-of-day data, reproducibly, with every input stored.
- Build a **history** of CTD probabilities and futures durations from 2016 (section 7).

### Non-goals (v1)
- **Fair value of the futures contracts.** The inputs needed to price the contract to the tick aren't available:
  - no CUSIP-specific repo (specialness of the CTD and near-CTDs);
  - no reliable CUSIP-specific pricing relative to the curve (free prices are lagged and rounded);
  - no view on slope/curvature dynamics beyond the one-factor betas.

  So also out of scope: implied CTD repo, the end-of-month option, the wildcard option, and net basis/implied repo outputs. Market futures prices are collected and used only for vol conversion, open interest and the report's futures duration (5.9). **Wishlist (far down):** use market futures prices, e.g. the model-to-market residual across contracts, to infer slope vol or other curve dynamics.
- Curve fitting and idiosyncratic rich/cheap modelling of individual issues.
- Outputs aimed at basis traders, such as the basis-trade duration mismatch or the hedge-ratio change per $100mm of CTD ([outputs.md](outputs.md), Dropped or reframed).
- Intraday or live pricing.
- A full multi-factor term-structure model (phase 4).
- ZT and ZF models. Their baskets are narrow (about a year of maturity or less), so switches move duration little. Their facts are kept in reference data and their market data is collected (3.2).
- Cash-settled Treasury products (micro yield futures and other yield-based contracts) and non-CME venues. No delivery, so no CTD.

## 2. Contract facts the code must encode

All contracts: quarterly delivery months (Mar, Jun, Sep, Dec); first delivery day is the first business day of the contract month.

| Contract | Face | Original maturity | Remaining maturity (deliverable) | Basket span | CF maturity rounding | Reference CMT (5.4) |
|---|---|---|---|---|---|---|
| **ZN** (10-year) | $100k | ≤ 10y | 6y 6m to 8y from first day of delivery month (6y 6m to 10y before the September 2023 contract) | ~1.5y (~3.5y before Sep 2023) | Down to quarter | 7y |
| **ZB** (T-bond) | $100k | — | 15y to under 25y | ~10y | Down to quarter | 20y |
| **UB** (Ultra bond) | $100k | — | 25y and over | ~5y (25–30y) | Down to quarter | 30y |
| **TN** (Ultra 10-year) | $100k | ≤ 10y | 9y 5m to 10y | ~0.6y | Down to quarter | 10y |

ZN and ZB switch most. TN's basket is narrow, and UB's switches are between 30-year issues of similar duration, so their CTD risk is usually smaller, but they get the same outputs.

Not modelled (kept so they can be added through reference data):

| Contract | Face | Original maturity | Remaining maturity (deliverable) | CF maturity rounding | Calendar family |
|---|---|---|---|---|---|
| ZT (2-year) | $200k | ≤ 5y 3m | ≥ 1y 9m from first day, ≤ 2y from last day of delivery month | Down to whole month | Short |
| ZF (5-year) | $100k | ≤ 5y 3m | ≥ 4y 2m from first day of delivery month | Down to whole month | Short |

The figures are a working summary. **Verify each against the current CBOT rulebook chapter when encoding it.** They live in `reference/` as records with an effective-from date (`contract_grades.toml`, looked up with `ctd.reference.grades.grade_for`), never as constants in code, because CME changes grades (ZB in 2011; ZN from the September 2023 contract month).

- **Eligibility rules.**
  - Remaining maturity is measured from the first day of the delivery month, except ZT's maximum (2y), measured from the last day.
  - Remaining-term limits are inclusive, except ZB's "under 25y".
  - Original-term limits apply per tranche: a 7-year note reopened as a 5-year counts as a 5-year for ZT and ZF from that reopening (CME's TCF lists it so; 91282CGQ8, 912828Z78).
- **Delivery calendar** (computed from the rule, below). ZN, TN, ZB and UB share it:
  - last trading day = 7th business day before the last business day of the month;
  - last delivery day = last business day of the month.

  ZT and ZF: last trading day is the last business day of the month; last delivery day is the 3rd business day of the following month.
- **Conversion factor:** price per $1 par at a 6% yield, per CME's formula, with remaining maturity rounded down to the quarter (the month for ZT and ZF; `cf_round_months` in `cme_products.toml`). Computed with the formula in both live and historical mode. CME's published tables (TCF) are validation only; the formula matches every stored TCF row.
- **Invoice price** = futures settlement × CF × face/100 + accrued interest at the delivery date.
- **Basket changes.** Baskets are rebuilt from the eligibility rules and Treasury security terms (the derived `baskets` table, data.md) and checked against CME's TCF files; the first file a bond appears in dates its addition. New issues can join:
  - for ZN, new 7-year notes, and 10-year notes once under 8 years (new 10-year notes before September 2023; they're now deliverable into TN instead);
  - new 10-year notes for TN, which leave its basket about seven months after issue (under 9y 5m);
  - new 20-year bonds for ZB;
  - new 30-year bonds for UB;
  - aging 30-year bonds move from UB to ZB once under 25 years.

  Reopenings don't change CUSIP, coupon, maturity or CF. Crossovers are rerun whenever the basket changes.
- **Baskets are dated, not fixed per contract.** The basket used for a run is the one valid at the horizon date.
- **ZN grade change (September 2023).** From the September 2023 contract month CME caps ZN's remaining maturity at 8 years; before, 10 years. Basket rebuilds look up the grade in force for each contract month. TCF files start in December 2023, so pre-2023 ZN baskets can't be checked against them, and ZN backtest cycles before September 2023 run on the old, wider basket.
- **ZB/UB boundary.** A bond crosses from UB's basket to ZB's when its remaining maturity falls below 25 years, applied at each contract's first delivery day, so the same bond can be in UB for one contract and ZB for the next.

### Options on futures
- ZN, TN, ZB and UB each have listed options with quarterly, serial and weekly expiries. **The model uses quarterly and serial options only**; weeklies aren't collected from Databento and get no reference data (the bulletin prints them; the parser skips them).
- **Quarterly** options settle into the same-month futures contract. **Serial** options (non-quarterly months) settle into the next quarterly contract.
- **Expiry rule:** quarterly and serial options stop trading on the last Friday that is at least 2 business days before the last business day of the month *preceding* the option month (the business day before, if that Friday is a holiday). The rule is coded in `reference/options.py`, with the underlying contract per expiry, and matches every expiry CME has stated since 2016 (below).
- Exercise: American, physically settled into futures, premium paid upfront. Discount at SOFR to expiry when inverting prices.
- Strike interval and premium tick are read from the chain, not stored. The strike interval limits how finely a digital (5.11) can resolve a crossover.

**Delivery and option expiry dates are computed from the rules, not stored.** `refdata.delivery_dates` and `refdata.option_expiry` apply the rules above (`reference/delivery.py`, `reference/options.py`) on the `cme` holiday list, unless a record in `rule_exceptions.toml` overrides a month (there are none). They raise for a month the holiday list doesn't reach, so the holiday list is the one forward-looking input to keep up (data.md §2.5).
- **Why:** the rules have held since 2016. Every option expiry in the derived options table (816 option months, FEB16 to SEP26, ZT to UB, from Databento's definitions and the bulletins) equals the expiry rule, and every expired ZN, TN, ZB and UB contract's last row in the derived futures table (172 contracts, H6 2016 to U6 2026) is on the delivery rule's last trading day; `ctd derive` repeats both checks on every build and fails on a disagreement (data.md §9). Records generated from the same rules on the same holiday list add no information, and a record per product and month has to be added before each roll.
- **Rejected: a record per contract month and option month,** generated from the rule and tested against it: nothing beyond the rule, a chore before each roll, and about 700 records to reach back to 2016.

## 3. Data

What the model needs and why. Sources, formats, coverage and quirks are in [data.md](data.md).

| Data | Used for | Source |
|---|---|---|
| Basket and conversion factors | basket per contract month; CF validation | rules + CF formula; CME TCF files for validation |
| Security terms (CUSIP, coupon, maturity, dated date, original term) | cash flows, eligibility | TreasuryDirect, FiscalData |
| Bond prices by CUSIP | forward prices and yields | TreasuryDirect daily (5.1) |
| Treasury futures settlements and open interest | vol conversion (5.5), open interest, the roll, the report's futures duration | Databento |
| Option settlements by strike | ATM vol, digitals, smile (3.1) | Databento |
| Treasury par curve (CMT) | KRDs (5.9), betas (5.4), realised vol | Treasury; FRED as cross-check |
| SOFR | repo fixings (5.3) | NY Fed |
| 1-month SOFR futures (SR1) | repo strip (5.3) | Databento |
| 30-day fed funds futures (ZQ) | repo before May 2018 (open question) | Databento backfill; bookmarklet days |
| CTD-specific repo | not available free | GC for every bond |
| CFTC TFF, MSPD, SOMA, buybacks, Pace of the Roll | fragility dashboard ([outputs.md](outputs.md)) | not collected yet |

### 3.1 Options chain

The model reads every standard (quarterly and serial) option on ZN, TN, ZB and UB, every strike, puts and calls, from the daily Databento pull (data.md §5.14). CME settles every listed strike; the Section 42 bulletin prints only those with open interest or volume, so it is a cross-check, not a source.

| Field | Use |
|---|---|
| As-of date, option product, expiry date | keys; expiry drives the term-structure interpolation |
| Underlying futures contract and its settlement price | moneyness; mapping vol to the right CTD |
| Put/call, strike, settlement premium | implied vol, skew, digitals |
| Volume and open interest | which strikes traded (below); liquidity weights in the smile fit |

How the model uses the chain (5.5, 5.7, 5.11):
- **ATM vol**: out-of-the-money puts and calls nearest the money, inverted with a normal (Bachelier) model on the futures price. Early-exercise value is ignored for out-of-the-money strikes (flagged in diagnostics). Put-call parity checked at the strike nearest the money.
- **Skew**: implied vol by strike per expiry, re-expressed in bp-of-yield moneyness using the futures DV01 of that expiry's underlying.
- **Smile fit**: normal SABR per expiry on the filtered chain (5.5.1).
- **Crossover-strike vol** (interim, 5.5.2): the smile read at the futures price equivalent to each crossover.
- **Raw digitals** (5.11; diagnostic once the smile fit exists): put-spread slope between strikes that straddle each crossover's futures price.
- **Term structure**: the two expiries that bracket the horizon (5.5 step 3). The later one is usually a serial on the *next* quarterly contract.

**Strikes with no open interest are kept.**
- What the model does with them:
  - Every settled strike stays in the chain.
  - Each digital and the ATM vol record which of their strikes traded that day (cleared volume above zero) and which had no open interest.
  - Every output shows "strikes traded" (all, none, or which).
  - Option-derived numbers are called "option-implied, from CME settlements", never "market-implied".
- **Why:**
  - CME sets every settlement, traded or not, from its implied-vol skew for the expiry ([CME daily option settlement procedure](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457412876/CME+CBOT+NYMEX+COMEX+Daily+Option+Settlement+Procedures)). Open interest only records past positions. So dropping the untraded strikes makes the chain smaller, not more market-based.
  - The headline numbers (DV01, KRDs, the profile) use only ATM vol, so they don't depend on the wings. Measured: over 2026-09-01 to 10-15, dropping the strikes with no open interest and no volume left ZBZ6 and ZNZ6 essentially unchanged, and UBZ6's and TNZ6's ATM vol within 0.8% and DV01 within $10. On 2026-10-16 and 10-19, where both exist, the bulletin chain and the Databento chain give identical results for ZBZ6 and ZNZ6 and the same ATM vol, width and DV01 for UBZ6 and TNZ6; only far-wing digitals move, by up to 1 point.
  - Dropping them turns UB's and TN's near-the-money digitals into uninformative intervals: TNZ6 on 2026-09-22 goes from CTD 97–100% to 0–100%, UBZ6 on 10-02 from 49–51% to 0–100%.
- **How far to trust a digital:** a switch within about 1σ reads the well-anchored part of the skew. Beyond about 1.5σ, or with no traded strike, it reads CME's wing shape and is indicative. ZB's and ZN's digitals mostly rest on traded strikes; UB's and TN's mostly don't, and on many dates neither strike behind their ATM vol traded either (9).
- Databento's settlement flag (`stat_flags`) doesn't say whether an option traded; volume does (data.md §5.12).

Filters and fallbacks (for the smile fit):
- Drop strikes settled at the minimum tick, deep in-the-money strikes, and prices that break monotonicity or convexity in strike.
- Skip an expiry with fewer than a minimum number of usable strikes (a parameter, initially 5).
- If no expiry is usable (most likely for UB), in order:
  1. Map vol from the neighbouring contract through betas (UB from ZB, ZB from UB, TN from ZN).
  2. Use realised vol (as in historical mode).
- Record the source used in diagnostics.

### 3.2 Collection policy

**Collect broadly, model narrowly.** A source that only shows recent days is lost for good on any day it isn't pulled, so data that can't be backfilled is collected every business day, for every product, whether or not the model uses it yet. Backfillable data is pulled daily anyway and backfilled once at setup. Operations, schedules and recovery windows are in data.md §2–§4.

- **Every raw file is stored exactly as downloaded**, keyed by as-of date, and never overwritten (one exception: a provisional TreasuryDirect price file, replaced once end-of-day prices are published, data.md §5.1). The model reads only from the store.
- **Each date gets a manifest**; gaps are flagged and alerted, never filled from another source.
- **CME futures and options come from a daily Databento pull**, which is the record. The bookmarklet (CME settlement pages and the Section 42 bulletin) is an optional, free cross-check; a day not clicked is a permanent gap there, never an alert.
- **Exception: the Databento futures pull is narrow.** It takes the front two contracts of each Treasury future and the front seven SR1 months: everything the model reads. SR3 and ZQ are collected only on bookmarklet days; weekly options are not collected.
  - **Why:** a full-parent futures pull costs about 20 times the narrow one, and with option definitions for new instruments only the whole daily pull is about $4 a year against about $35. Databento can backfill anything left out if it's ever needed.

### 3.3 Which data a run uses

A run for date D uses **data dated on or before D, from any stored file**, whenever it was pulled. Runs are made after the fact: final output needs TreasuryDirect's end of day and D's SOFR, both published on D+1.
- **SOFR:** D's own fixing, the rate repo traded at on D. It's published the next morning, so it comes from D+1's NY Fed file. Until that file is stored, the run uses D−1's and warns.
- **Not realised repo after D.** Repo from settlement to the horizon is the SR1 strip on D, the market's expectation, never the fixings that followed. Forward prices on D are priced off expected repo, and the backtest scores against the realised CTD, which later data would leak into.
- **Open interest** for D arrives with D+1's data and is fine to use under the rule.
- **No point-in-time layer** for the historical runner: it reads the derived tables with the same rule.
- **History-type sources** (whole series in every pull) take each value from the latest pull, with any revision noted by the build (data.md).
- **Reproducibility:** re-running D gives the same answer once D+1's files are stored; each result lists the raw files it read.

## 4. Architecture

```
ctd/
  data/            # fetchers + raw store (one module per source); derived/ builds the Parquet tables
  reference/       # contract specs, delivery and option expiry rules, grades, holidays
  bonds/           # cash flows, accrued, price<->yield, conversion factor, forward price
  funding/         # term GC repo: flat SOFR and the SR1 strip
  curve/           # par curve, beta estimation, residual stats, realised vol
  vol/             # option implied vols, digitals, term-structure interpolation
  model/           # horizon, envelope, crossovers, probabilities, light model, profile
  risk/            # DV01, key rate DV01s, cluster profiles
  history/         # historical runner, backtest scoring
  report/          # result files, tables, charts, report pages
  cli.py           # ctd fetch | ingest | derive | run | history | report | check | backfill
tests/
docs/              # design.md, roadmap.md, open-questions.md, data.md, outputs.md
CLAUDE.md
```

- Python, numpy/scipy/pandas.
- Pure functions in `bonds/`, `funding/`, `model/`, `risk/` and the computational parts of `curve/` and `vol/`; I/O only in `data/` and `report/`.
- **Reading the store: three layers.** The model never touches paths, file formats or which source a number came from.

  | Layer | Holds | Source-specific? |
  |---|---|---|
  | Raw store (`data/raw/`) | files exactly as downloaded | yes, one format per source |
  | Readers (`parse`/`read` in each source's module) | one source's raw file for one date, as standard records (`OptionSettle`, `FuturesSettle`, `BondPrice`, ...) | yes, one reader per source |
  | Derived tables (`data/derived/`, Parquet) | the standard records across all dates, one table per kind of data | no: one schema whatever the source |

- **Runs read the derived tables** by default (`--inputs derived`); `--inputs raw` reads the date's own files and is kept as a cross-check.
- **Results** (`data/results/`, JSON) are the model's output, one file per model, contract and date. Like derived tables they are rebuilt from the raw store, never edited by hand, and a re-run overwrites them. Each records the raw files behind every input (with sha256, and the derived table it came through) and the code version (`git describe --dirty`).
  - **Why JSON:** one small file per run, readable by eye; a table can be built from them if a series needs one.
- **Derived tables** are a cache of the raw store, built by `ctd derive`. Table-by-table contents are in data.md; the rules are:
  - **Every row has a `source` column**, and a precedence rule per table says which source wins on a date where several exist. The winner's gaps are never filled from another source. Each build compares the sources where they overlap (`overlap` in `_build.json`), so overlap days are an automatic cross-check, and changing a source is a rule change and a rebuild, not a model change.
  - **Two stages.** Each source's rows go to staging (`data/derived/staging/<table>/<source>/...`), then the merged table applies the precedence rule. A slow source is read once, a precedence change only re-merges, and the overlap comparison reads staging.
  - **Incremental builds.** A source splits its raw files into units, each listing its raw files with sha256. A unit whose files change is re-read, and only the partitions it can fall in are rewritten. A unit can depend on more than one date (D's open interest comes with D+1's file, so storing D+1 re-reads D). Source and table `version`s are bumped by hand when output or columns change, and force that rebuild. A unit that fails is left out, reported (exit 1, an alert with `--notify`) and retried on the next build. Each build lists every product's missing trading days on the `cme` calendar.
  - **The invariant: an incremental build gives the same tables as `ctd derive --full`** (tested).
  - **Format: Parquet (zstd)**, partitioned by product and year (`data/derived/<table>/product=ZN/year=2026/part.parquet`), read with `DerivedStore.read(table, products, start, end)`.
    - **Why Parquet:** tables are written once and read many times, filtered by product and date, which Parquet's row-group statistics skip to. Dictionary encoding and zstd make it several times smaller, and every tool reads it.
    - **Rejected: Feather.** It reads faster with no filtering and suits scratch files, not a store read selectively for years.
- **Analytics** (yields, durations, DV01s) are computed when needed, not stored: they depend on the code and conventions, not only the raw files.
- Dates and conventions explicit everywhere: settlement date (T+1), delivery date, actual/actual accrual, semiannual compounding.

## 5. Model

### 5.1 Bond math (hand-written)
- Write the bond math directly; Treasury math is simple. QuantLib (or TreasuryDirect published values) is used **only in tests** as an independent check.
- **Yield convention: street convention, one pricing function used everywhere** (`ctd.bonds.pricing`). Scheduled (unadjusted) coupon dates, semiannual compounding, fractional exponent for the first period:
  `P_dirty = Σ_k CF_k / (1 + y/2)^(w + k)`, `w` = days to next coupon / days in current period.
  Every price→yield, yield→price and duration calculation uses this function. Business-day calendars are used only for settlement and delivery dates.
- What can be approximate: day counts within a period (1 day of accrual ≈ 0.3bp on the ZB crossover, partly cancelling across bonds), stray holidays.
- What must be exact:
  - **coupons between today and the horizon** in the forward price (a missed coupon is a 1–2.5 point error);
  - clean → dirty with accrued at the correct settlement date (TreasuryDirect prices are clean);
  - accrued at the delivery date (carry);
  - forward KRDs measured from the horizon date.

**Which TreasuryDirect price.** Each FedInvest file has buy, sell and end-of-day columns; end of day is filled in about a day later (data.md §5.1). The model uses **end of day** wherever it exists. Only for a date still provisional does it fall back to the buy/sell midpoint (sell where there is no buy), and the result is marked provisional.
- **Why:** end of day is much the nearer snapshot to the 2pm CT futures settlement. Over 2026-09-01 to 10-23 (37 dates × ZBZ6, ZNZ6, UBZ6, TNZ6, the light model re-run with each snapshot, all else equal), the recentring gap's daily change, as a yield, has a component common to all four contracts with standard deviation 1.32bp with end of day against 3.53bp with the midpoint (largest 3.6bp against 9.6bp); what's left per contract is 0.4bp against 0.6–1.2bp. End of day minus the midpoint is itself a yield move common to all four contracts (correlation 0.97–0.99, standard deviation 2.5bp, up to 6.2bp): the two are taken at different times. The 1.3bp left is the timing gap end of day still has (9). A provisional run on the midpoint is about 2.7 times noisier, one more reason it's replaced once end of day arrives.
- TreasuryDirect's own definition of the three columns hasn't been found.

### 5.2 Horizon (implied delivery date)
- **One horizon for the whole basket**, not one per bond: the short commits to a date before knowing which bond wins.
- **Rule:** the last delivery day if the basket's **probability-weighted carry** is positive, the first if negative.
  - Carry is `Σ p_i (F_first,i − F_last,i) / CF_i`: each bond's converted forward clean price on the first delivery day minus on the last (positive means holding to the last day pays).
  - The weights `p_i` are each bond's option-implied probability of being CTD (the light model's digitals, interval midpoints rescaled to sum to 1), with the envelope fixed at the last delivery day.
  - Carry is today's, at today's term repo (5.3); a warning flags dates where flat SOFR would give the other date.
- **Every implied delivery date goes through this one rule**, in `ctd.model.horizon` (`weighted_carry`, `light_horizon`): live and historical runs, saved results, and the report's implied delivery column. The full model uses the same definition.
- **Why weighted, not the CTD's own carry (rejected):** when the CTD alternates between bonds of opposite carry, the CTD's carry moves the date a month with each flip. Each flip moves the width to the horizon by about 22% (√ of 91 against 61 days), and with it the normal-model probabilities and the published date. Over 2026-09-01 to 10-23 the old rule moved ZNZ6's date 13 times (between the 4½% Aug-33, positive carry, and the 3⅞% Aug-33, negative), ZBZ6's and UBZ6's twice. With the weighted rule the date doesn't move for ZBZ6, UBZ6 or TNZ6 (all 31 December; weighted carry +0.2 to +2.2/32), and ZNZ6 moves 6 times: three single days at 1 December (09-15, 09-23, 10-13; weighted carry −0.4 to +1.3/32, within ±0.25/32 of zero on 7 dates). The flat-SOFR cross-check disagrees on 3 ZNZ6 dates instead of 12.
- **Why digitals, at the last day:**
  - The weights mustn't depend on the date being chosen. The normal model's width runs to the horizon, so weighting by it is circular; the digitals are measured at option expiry. Weighted by the normal model, the date would flip more (ZBZ6 6 times, ZNZ6 13); it agrees with the digitals' sign on 76–100% of dates.
  - The switch strikes the digitals are read at still depend on the envelope's date, so the envelope is fixed at the last day.
- **What the date changes** (each date run at both delivery days): the headline DV01 by under 1% (median $0.5–0.8k per $100mm), effective maturity by 0.08–0.16y, the width by about 22%. But where two bonds of opposite carry are near a tie, which bond is CTD and the per-bond probabilities can move a lot: ZNZ6's CTD differs between the two days on 25 of 37 dates and its per-bond probabilities by a median 58–63 points (ZBZ6 15–20).
- **Full model (phase 3):** if carry is near zero, or slightly negative with a crossover near, run both dates and take whichever gives the lower expected converted price for the short. This is an internal decision rule, not a published fair value. Limitations of the single date are in section 9.

### 5.3 Term GC repo and forward prices
- Overnight rate: **SOFR** (the closest proxy for DVP GC on basket bonds). **GC for all bonds**: CTD specialness isn't modelled (no free CUSIP-specific repo). A 50bp special rate on the CTD moves its crossover by about 2bp; covered as a sensitivity (8).
- Term rate to horizon, actual/360 compounding:
  `R_term = [Π_i (1 + r_i · d_i/360) − 1] × 360/D`
- **Default: the strip of 1-month SOFR futures** (`funding/strip.py`) whenever it covers the last delivery day; otherwise flat at the latest SOFR, with a warning.
  - SR1 settles at 100 minus the arithmetic average of daily SOFR over its calendar month, each non-business day at the business day before it (which can be in the previous month). **Verify this averaging rule against CME's SR1 rulebook chapter.**
  - Months are solved in order, each with one flat rate on its unknown days; the current month's known fixings and the days carried in from the previous month are fixed. Each month then reprices its SR1 average exactly.
  - Fixings, D's own included (3.3), come from the NY Fed files. A known business day with no fixing (an early-close Good Friday) takes the one before it.
  - Flat SOFR is still computed as a cross-check on the horizon (5.2).
  - **Why the strip:** it needs no new data and prices whatever the market expects for the FOMC and the year-end turn, though spread evenly over each month. On 2026-10-21 it gave 4.02% to a 31 December horizon against 3.89% flat (October's remaining days 3.91%, November 3.94%, December 4.11%): carry about 0.02 points lower per bond, the recentring gap about 0.026 points wider, horizon and CTD unchanged, futures DV01 +$40 per $100mm.
- **Deferred: stepped path (phase 3).** Steps at FOMC decisions, solved month by month, with the year-end spike placed on 31 December. Spread over December, the turn lifts repo to a 31 December horizon by about 1bp, though that day's rate isn't part of that repo. Needs an FOMC calendar in `reference/` (meeting and effective dates from 2016, unscheduled meetings included).
- Ignore term premium.
- Sensitivity: a 10bp repo error ≈ 0.013 points on a ZB bond over ~0.2 years (≈0.3bp of crossover); it matters more for the carry sign and so the horizon.
- Forward clean price at T for each bond from dirty price, term repo and coupons before T; converted to forward yield `y_i^fwd`. Everything is centred on these.

### 5.4 Factor and betas
- Factor `x` = constant-maturity yield near the current CTD, per contract (section 2): **7-year for ZN, 10-year for TN, 20-year for ZB, 30-year for UB**.
- For each published par-curve tenor that brackets the basket (5, 7 and 10y for ZN; 7 and 10y for TN; 10, 20 and 30y for ZB; 20 and 30y for UB), regress yield changes on the reference: `Δy(τ) = β(τ)·Δx + ε(τ)`.
  - 2–3 day or weekly changes; 6–12 month window or exponential weights (half-life ~3 months).
  - Re-estimate betas and vol daily (rolling or EWMA), never in occasional steps, so the DV01 series has no artificial jumps.
  - Shrink betas slightly toward 1.
  - Also estimate on **sell-off days only**; use those if materially different.
- **Betas between tenors: node betas interpolated linearly in maturity** to each bond's remaining maturity at T.
  - **Why:** with any interpolation linear in the node yields (linear, or a standard cubic spline), "interpolate yields, then regress" gives the same answer as "regress at the nodes, then interpolate the betas". So betas only need estimating at published tenors. Every basket sits between nodes: no extrapolation.
  - **Rejected: monotone schemes such as PCHIP.** They aren't linear in the node values, so the equivalence breaks.
  - Alternatives (spline weights, pooled bond-level betas) and the ZB reference factor are in open-questions.md.
  - **How much it matters:** CTD switches depend on beta *differences*. For ZB, a 0.03 beta error on a 30bp crossover moves it by about 1bp; the estimation window and sell-off betas matter more than the interpolation.
- Store residual SDs `σ_ε(τ)` and the residual SD of the spread between candidate bonds (used in 5.7, and a check on one-factor adequacy: under ~4bp over the horizon is fine, above ~6bp suggests a second factor).
- Until betas are built, the model runs with **β = 1** (parallel shifts in forward yields).

### 5.5 Volatility
1. Futures option implied vol from the contract's own options chain (3.1), ATM to start.
2. Price vol → normal yield vol of each expiry's CTD: `σ_y ≈ σ_price × F / (100 × D_F)`, using the CTD duration of **that expiry's underlying contract**.
3. **Interpolate total variance to the horizon** between the bracketing expiries: `V(T) = σ_y² T`, linear in time between expiries; `σ_y(T_h) = √(V(T_h)/T_h)`.
   - Example: for a December contract with a December horizon, December quarterly options on December futures expire in late November, and January serial options on March futures in late December. Those two bracket the horizon.
   - Captures vol term structure and event variance (e.g. December FOMC). √T alone isn't enough: when the December options cover 26 days of a 67-day horizon, a 20% error in the extrapolated vol moves S by about 10%, and a switch 1σ away by about ±2.5 points.
   - When the later expiry's underlying is the next contract, adjust its vol for that contract's different CTD maturity via betas. This matters most for ZB.
   - **Fallback**: √T scaling from a single expiry, when the horizon is close to the first expiry or only one expiry is usable.
4. To factor units: `σ_x = σ_y / β_CTD`; width `S = σ_x √T_h`.

**v1 uses a single ATM-based normal width `S` for all crossovers.** Crossover locations are set by forward prices, CFs and betas, not by vol, so find the crossovers first, then apply the distribution.

Historical mode: implied vol from the option history (data.md §5.12), as in live mode; realised vol (EWMA of daily changes in the reference CMT yield) as a comparison and a fallback where options are too thin.

#### 5.5.1 Smile-implied distribution (phase 3)
Replaces the single normal width with one market-implied distribution for the factor, used for every crossover. Handles any number of crossovers consistently (monotone tail probabilities by construction) and includes skew and the smile-slope term in each tail probability.

1. **Fit a smooth smile per expiry**: normal SABR (β = 0) on normal vols of the filtered chain (3.1).
   - Why fit rather than differentiate raw prices: strikes are discrete (crossovers fall between or beyond them), premiums are rounded to 64ths, wings are thinly traded, and differencing amplifies all of it (negative densities). The fit gives a continuous, differentiable, arbitrage-free price function.
   - Weight by liquidity (open interest or volume); drop minimum-tick/cabinet strikes; constrain extrapolation (e.g. cap wing vol at a multiple of ATM vol).
   - Record fit residuals per strike.
2. **Digitals from the first derivative** of fitted put prices with respect to strike: `P(F_E < K) = (∂Put/∂K) / DF` (density from the second derivative). Premium is paid upfront, so divide by the discount factor to expiry.
3. **Map futures price to factor through the envelope**: `F(z) = min_i C_i(z)`, monotone in z, so `P(F_E < K) = P(z > z(K))` with `z(K)` solving `min_i C_i(z) = K`. Use the envelope, not the CTD's own curve, because near a crossover the futures follow whichever bond is cheapest. Approximation: futures at expiry = cheapest converted forward price, ignoring residual switch value to delivery (slight upward bias in tails beyond a crossover).
4. **Recentre** so the distribution's mean (or median) in z is 0, matching the forwards. Log the size of the shift; a large one signals inconsistent inputs.
5. **Extend from option expiry to the horizon by convolution**: `z_h = z_E + ε`, `ε ~ N(0, V(T_h) − V(T_E))` in factor units, with V from step 3 above. Preferred over rescaling by `√(V(T_h)/V(T_E))`, because skew should fade somewhat over the extra time. The two agree when the horizon is close to expiry.
   - This needs `T_h ≥ T_E`. When the nearest usable expiry falls *after* the horizon, the increment is negative and convolution fails (open-questions.md).
6. **Result**: one density `φ(z)` on the grid at the horizon. All crossover tail probabilities, region probabilities, duration weights (5.9) and scenario profiles come from it.

Diagnostics:
- Compare each crossover's SABR digital with the raw put-spread digital from settlements; flag disagreements of more than a few points (bad fit or stale settlement).
- Report the ATM-normal probability alongside the smile-implied one; the gap shows how much skew and wing pricing contribute.
- Report the share of each tail probability beyond the furthest liquid strike, and label such crossovers' probabilities as extrapolated.

Caveats: rich or floor-priced wings fatten fitted tails and can overstate far crossovers (e.g. the later steps of ZB's staircase); implied tails also carry a risk premium (risk-neutral, not real-world).

#### 5.5.2 Interim alternative: one vol per crossover
If the smile fit isn't ready, read the implied vol at each crossover's futures strike `K_k = min_i C_i(z_k)` and give each crossover its own width `S_k`. It needs two patches that 5.5.1 makes unnecessary:
- **Monotonicity**: on each side of the forward, tail probabilities must decrease with distance; cap farther tails at the nearer one's value and warn.
- **Density for durations**: a piecewise density, the ATM normal shape within each region rescaled so the region's mass equals its probability: `φ*(z) = φ_ATM(z) × π_i / P_ATM(region i)`.

### 5.6 Pricing grid
**Window.**
- Normal width: z from −4S to +4S.
- With the smile-implied distribution (5.5.1), size the window by **quantiles**, since a skewed or fat-tailed distribution can put meaningful mass beyond ±4S on one side:
  - `z_min = Q(tol)`, `z_max = Q(1 − tol)`, `tol` a parameter (initially 1e-4), found on the CDF **after** the horizon convolution;
  - widen to include every crossover with tail probability above `tol`, and the reported scenario range (duration profile; ±1σ and ±2σ);
  - hard cap (e.g. ±8 × ATM-equivalent width, or ±300bp) against runaway SABR wings; record the mass beyond the cap, renormalise, and flag the fit if the truncated mass exceeds `tol`;
  - record the probability mass beyond the furthest listed strike (extrapolated).

**Spacing.** 1bp steps; optionally finer near the centre and crossovers. Crossovers are root-found exactly, so spacing only affects integrals (durations).

For each z on the grid:
```
y_i(z) = y_i^fwd + c_i + β_i · z
P_i(z) = clean price at T from y_i(z)
C_i(z) = P_i(z) / CF_i
```
`c_i` is solved per bond so that `E[P_i(z)] = forward price` under z ~ N(0, S²) (convexity adjustment, ~1–2bp for ZB). It moves crossovers only through its difference across bonds (a basis point or two), so it is **off by default**: centre on forward yields, and add it only if backtests show a bias.

### 5.7 Envelope, crossovers and probabilities
- `min_i C_i(z)`; record the argmin (the CTD in each state). Only the argmin is used; the envelope's value isn't published.
- Root-find the exact z where the argmin changes: crossovers `z_1 < z_2 < …`. Expect ZN: switches within the 6.5–8y basket (before September 2023, usually one major switch from the 6.5–7y cluster to the 9.5–10y cluster); ZB: a staircase of two or three; UB: one or two, between the shortest and longest 30-year issues; TN: rarely any that matter.
- Tail probability per crossover, measured from the forward (z = 0) on its own side:
  - sell-off side: `Q_k = P(z > z_k)`; rally side: `Q_k = P(z < z_k)`.
  - Normal width: `Q_k = Φ(−|z_k| / S)`. With 5.5.1: read from the smile-implied CDF. With 5.5.2: `Φ(−|z_k| / S_k)`, then the monotonicity cap.
- Region probabilities: differences of successive tail probabilities on each side; the current CTD's region gets the remainder.
- **Slope adjustment** per crossover between bonds S and L, for **probabilities only**:
  - Normal width: `S_eff = √(S² + (m · σ_ε,spread)²)`, `m = D_L / (D_L − D_S)` (beta-adjusted; level measured at the short bond's yield).
  - With 5.5.1: convolve that crossover's tail with `N(0, (m · σ_ε,spread)²)`, i.e. `Q_k = P(z_h + m·ε_slope > z_k)`.
  - **DV01 and KRDs use the unadjusted density** (5.9). Check that adjusted tails stay monotone across a staircase; if not, cap and warn (the multi-factor model is the clean fix).

### 5.8 Fair value: not modelled
See section 1. No model futures price, no comparison with market settlement, no implied CTD repo.

### 5.9 Risk and scenarios
- **Futures DV01**: region-weighted over the grid, each bond's DV01 evaluated where it is CTD:
  `DV01_F = Σ_grid φ(z) · DV01_argmin(z)(z) / CF_argmin(z) · Δz`
  For a factor shift this equals the derivative of the expected envelope, so no futures price is needed. It holds vol fixed (no vega).
- **Units**: $/bp per $100mm notional by default; per contract also available (`face` in `cme_products.toml`).
- **Key rate DV01s**: the same weighting, with each bond's forward KRDs at T.
  - **Grid: 2, 5, 7, 10, 15, 20, 25 and 30 years, fixed.** Changing it changes every published KRD and the effective-maturity series.
    - **Why these nodes:** 15 and 25 years aren't published par-curve points (their par yields are interpolated), but without them a ZB switch (about 15y to about 25y) would be split across the 10, 20 and 30-year buckets and barely show.
  - **Method: par-curve key-rate bumps, scaled to the pricing function's DV01.**
    1. *Curve:* the Treasury par curve stored for the as-of date, par yields interpolated linearly between published tenors onto a semiannual grid, discount factors bootstrapped from it (each grid point a par bond paying semiannually; log discount factors linear between grid points).
    2. *Bumps:* for each node, add 1bp × its triangular (tent) weight between neighbouring nodes to the par yields, re-bootstrap, and reprice the bond's cash flows after the horizon (times from the horizon; today's curve, not a forward curve). The price fall is the bond's KRD at that node. Tents keep KRDs and effective maturity smooth as a bond rolls past a node.
    3. *Scaling:* the bumps give only each node's share; the shares are scaled to the bond's DV01 at its forward yield from `ctd.bonds.pricing`, so one pricing function sets every duration number and the KRDs sum to the DV01 exactly.
  - **Why par bumps:** a par-curve KRD is the hedge in par bonds at each tenor, which is how the audience hedges and what vendor KRDs report.
  - **Rejected: cash-flow bucketing.** It describes where a bond's coupons fall (a STRIPS hedge). It agrees on total DV01 but not on shape, and disagrees most on the ZB switch, where the CTD is a high-coupon bond near par and the sell-off contenders are deep-discount low coupons. Flat curve at forward yields on 2026-10-21, from the 31 December horizon: the 5% May-45 CTD has effective maturity 15.5y bucketed and 18.6y bumped, the 1⅜% Aug-50 21.6y and 27.9y, so a switch between them moves effective maturity +6.1y bucketed and +9.3y bumped. ZN barely differs (4½% Aug-33: 6.3y and 6.7y).
  - **Rejected: z-spread per bond.** Solving a constant spread so the curve reprices each bond, and bumping with it fixed, needs a root-find per bond and gets the totals only within about 1%. The two differ only in the split across nodes (about 0.02y for a bond 10bp off the curve).
  - **Why linear interpolation is enough:** on a humped curve (2026-10-21), linear, PCHIP and natural cubic agree to within 0.07y in duration and effective maturity and 0.6 points in any bucket's share, inside the 0.1y tolerance.
  - **Consequence: negative KRDs.** A low-coupon bond equals a par bond less a stream of coupons, so its par hedge is more than 100% at its own maturity and short at earlier tenors. Its short-tenor KRDs are negative (the 2¼% Aug-46: −7% at 10y, +117% at 20y), and its effective maturity can exceed its maturity. Charts must allow negative shares.
- **Clusters**: bonds with the same dominant key rate and DV01 within ~5%; report blended KRDs and each cluster's KRDs (members weighted by probability).
- **Scenarios (±1σ, ±2σ)**: shift every forward yield by kσ × β_i, keep the remaining vol, and **recompute crossovers, probabilities, DV01 and KRDs at the shifted state**. Never read off the CTD at the shifted yield, which jumps and overstates the change. Record whether the smile is treated as sticky strike or sticky moneyness.
- **Duration profile**: blended DV01 and KRDs as a function of the shift, about −100 to +100bp (wider when ±2σ falls beyond); ±1σ and ±2σ are points on it. Shifts are labelled in bp and in percentiles of the move-to-horizon distribution (σ√T).
  - **Probabilities for the profile: a normal factor, `z ~ N(c, σ√T)`, with ATM vol and β = 1**, until the smile-implied distribution (5.5.1). The shift axis is cut into cells of at most 1bp with every switch as an edge; a state's weights are the cells' exact normal masses (`model/profile.py`). The light model's digitals are reported alongside as a cross-check.
  - **Why:** the profile needs probabilities at shifted states, and the digitals are today's option prices, which can't be moved to another state; the normal factor can. Its cost is no skew, so at c = 0 it won't match the digitals; the gap is reported.
  - Percentiles are the same in yield and futures-price space, because the mapping is monotone, so only the distribution matters.
- **Comparison measures:**
  - *CTD-based DV01:* DV01/CF of the single CTD at the forward (z = 0), the number most vendor systems report; it jumps when the CTD changes.
  - *Constant-CTD DV01:* the CTD on the contract's first date in the series, held for the whole contract and reset at each roll (the next basket and CFs differ). Built over the saved results (each stores every bond's `dv01_cf` and `krd_shares`), not by `ctd run`. Its gap to the probability-weighted DV01 is the change caused by the basket.
    - **Why the start-of-series bond:** today's CTD carried back would redraw the whole history whenever the CTD changes. The start-of-series bond keeps past values fixed. The bond stays in the basket for the whole contract (new issues can join, none leave).
- **Effective maturity**: DV01-weighted, `Σ_k KRD_k · T_k / Σ_k KRD_k` over the key-rate grid. A cleaner switch signal than DV01, since yield level and roll-down move it much less than a switch does. Against the par curve it *lengthens* as yields rise with the CTD unchanged ([outputs.md](outputs.md), chart 3).
- **Distance to switch**: shift to the nearest crossover on each side, in bp and in σ.
- **Futures duration (report only)**: today's DV01 per 100 face over the **market futures settlement**, probability-weighted and CTD-based.
  - **Why the market settlement:** it only rescales the model's DV01, so it brings in no model futures price (5.8). It isn't computed at shifted states, where the futures price would have to come from the model.
- Blended KRDs are local; they understate how fast weights change near a crossover (negative convexity). The slope of the duration profile carries futures gamma.

### 5.10 End-of-month option: out of scope
It affects futures value, not durations or the probability of a major switch materially. Not modelled (section 1).

### 5.11 Light model
The light model skips betas and vol fitting: it finds the futures price at which each switch happens, then reads the probability of the futures finishing below it from the option settlements. It is the same calculation as the raw put-spread digital diagnostic (5.5.1). It gives switch points and CTD probabilities; DV01, KRDs and the profile come from 5.9 on the same envelope.

1. **Basket and converted prices.**
   - Basket and conversion factors from CME's TCF file for the contract. This is a shortcut: the derived `baskets` table gives the same CUSIPs and CFs for every contract month, so the light model could read it instead.
   - Clean prices from TreasuryDirect (5.1); forward clean price of each bond at the horizon with term repo (5.3), divided by its CF. Horizon by the rule in 5.2.
2. **Switch points as futures prices.**
   - Shift every bond's **forward yield** in parallel (β = 1) in 1bp steps, about −100 to +150bp. Reprice each bond and take the cheapest converted price at each shift, `E(z) = min_i C_i(z)`.
   - Record each shift `z_k` where the cheapest bond changes, and the envelope value there, `E(z_k)`.
   - Recentre onto the market futures settlement, which won't match the envelope exactly: `K_k = F_market + (E(z_k) − E(0))`. The recentring gap `F_market − E(0)` is reported (9).
3. **Digitals from the option settlements** (`vol/digitals.py`).
   - Use the quarterly expiry on the same contract (the December quarterly for the December contract).
   - Out-of-the-money options only: puts below the futures price, calls above. Each pair of neighbouring priced strikes gives a digital at its midpoint, interpolated linearly to `K_k`:
     `P(F < K) ≈ [Put(K_hi) − Put(K_lo)] / (K_hi − K_lo) / DF`, and on the call side `P(F > K) ≈ −[Call(K_hi) − Call(K_lo)] / (K_hi − K_lo) / DF`, with DF the SOFR discount factor to expiry. A missing strike widens the pair.
   - A cabinet or minimum-tick settlement, or a pair with equal settlements (a floor in the wings), only says the price difference is under about one tick, so the digital is an **upper bound** (e.g. "≤ 3%": 1/64 over a ½-point gap), not a value. A `K_k` beyond the listed strikes gets no value.
   - The strikes used that traded that day, and those with no open interest, are recorded (3.1).
4. **Probabilities** (`model/probabilities.py`).
   - Sell-off side: the probability beyond the first switch is `P(F < K_1)`. The bond between the first and second switches gets `P(F < K_1) − P(F < K_2)`, and so on outward; the bond beyond the last switch keeps its full tail.
   - Rally side: the same with `P(F > K_k)`. The current CTD gets the remainder.
   - An upper-bound digital is the interval [0, bound], a missing one [0, the digital inward], so every probability is an interval, a point when both ends agree. An upper bound larger than the digital inward from it is capped at that digital.
   - Checks: probabilities sum to 1 and fall with distance. A true digital can't rise with distance, so a negative region is measurement error, almost always 64ths rounding (±1/128 on each price over a ½-point gap is up to ±3 points per digital), between two close switches. Such a region is set to 0 with a warning: the model can't separate those bonds. Switches that don't chain from the CTD, or a digital on the wrong side, are code errors and raise.

**What it gives up:**
- **Horizon**: the probability of crossing by option expiry (late November for December), not by delivery. Somewhat low if the CTD is delivered at month-end.
- **Parallel shifts**: no steepening tendency, so ZB's switch points can be off by a few basis points.
- **Noisy strikes**: a single put spread inherits 64ths rounding, so results are ± a couple of points.
- **Remaining switch value**: at expiry the futures still include some switch value, which biases tail probabilities slightly upward (as in 5.5.1 step 3).

## 6. Outputs

What gets published, and how, is in [outputs.md](outputs.md). Per contract and date the model computes the Tier 1 quantities in 5.9 and saves them in its result file (4). Also computed, not published:
- Basket table: CUSIP, coupon, maturity, CF, price, forward price, forward yield, β, carry, repo used, converted forward price.
- Crossover table: from-bond → to-bond, crossover z (bp), equivalent futures price, distance from forward, probability (option-implied and normal; slope-adjusted once built).
- Diagnostics: vol source, strikes and expiries used and which traded, horizon and why, repo path, beta window, residual SDs, warnings.
- Chart: converted forward prices against factor shift (the envelope), with the shift distribution overlaid.

## 7. Historical mode

Goal: time series of CTD probabilities, futures DV01 and KRDs for past contracts, from free data plus the paid Databento backfills of futures and options settlements.

**Start: 2016.** Historical mode goes back to the March 2016 contract month and no further, because earlier Treasury futures rule changes aren't encoded. Rule changes since then (e.g. ZN's 8-year cap) are dated reference records.

**Which contract a date runs (the run window).** A contract is run from the **Friday one week before the previous contract's quarterly options expire** (the next `cme` business day if that Friday is a holiday) to the day before its own quarterly options expire. Expiries come from `refdata.option_expiry` (section 2), never from a separate calculation.
- In the week before each expiry, two contracts run per product: the old one carries the series and the new one gives the roll comparison ([outputs.md](outputs.md), Tier 2). December 2026 contracts: 2026-08-14 to 11-19; March 2027: from 2026-11-13.
- Dates before a contract's start are left out by choice, not for lack of data: the December 2026 futures are in the backfill from 2026-06-18 (when they became the second listed contract) and the DEC26 options from 2026-03-23.
- **The series rolls at option expiry**, to the contract whose quarterly options are the nearest not yet expired.
- **Why calendar-only:** the rule needs no liquidity data, so the contracts run for a past date never change, and it's the same date for ZN, TN, ZB and UB (their options expire together). Checked on the derived tables for every quarterly expiry 2016–2026:
  - every quarterly expiry (43 per product) matches the rule in `reference/options.py`;
  - on every start date the next contract has a futures settlement and a priced quarterly chain (at least 108 strikes; one exception, TN's JUN19 chain on 2019-02-15);
  - futures open interest crosses over a median 1 business day after option expiry (−2 to +4), so the start precedes the futures roll; the start falls 6 to 11 business days before the last business day of the month before delivery;
  - the start is on time for ZB: its December 2026 quarterly options stepped up in the week to 2026-08-14, from 5,000–6,500 a day to 19,000 (148k open), with both at-the-money strikes trading every day from then. It is about three weeks conservative for ZN, whose options stepped up in the week to 07-24 (about 4,000 a day to 40,000, 203k open) (open-questions.md);
  - TN and UB options barely trade before the roll whatever the start (UB had no volume and 1 contract open until the expiry week; TN a few hundred contracts in one week), though CME settles their whole chain daily and every chain passes `options_quality`. A standing caveat on their outputs (3.1), not something a start rule can fix.
- **Edge cases:** Presidents' Day can fall in the week before the March options expire, leaving four overlap days. On some Fridays a chain's Sunday finals are stale and `options_quality` flags it, which can cost the first day (data.md §9).
- **Why roll at option expiry:** after its options expire, a contract's vol has to come from the next expiry (5.5 step 3). That case is unsolved (open-questions.md), so the December contract after its options expire, when its CTD question matters most, is left for phase 2.
- **Data needs nothing extra:** the daily pull takes each Treasury future's front two contracts (which roll at futures expiry, weeks after option expiry) and every standard option, and CME's TCF lists the next three contract months. Delivery and expiry dates come from the rules (section 2), so a roll needs no new records, only a holiday list that reaches it.

**Inputs:**
- **Baskets**: rebuilt per contract month from the security terms (including matured issues) and the grade records, with CFs from the formula (the derived `baskets` table, checked against every TCF file).
- **Prices**: TreasuryDirect prices by CUSIP, stored from 2016.
- **Repo**: SOFR from April 2018; the SR1 strip from the derived futures table, which has the front eight SR1 and ZQ months (data.md §5.13). Before May 2018 there is no SR1 or SOFR (open-questions.md).
- **Vol**: implied from the option history, as in live mode; realised EWMA vol as comparison and fallback.
- **Futures and option settlements**: from the Databento backfills (front two futures contracts; every standard option) and the daily pull; the precedence by date is in data.md.
- Futures DV01 and KRDs need no futures price: they are probability-weighted basket DV01s over conversion factors.
- Runtime is trivial; data is the constraint. Historical mode doubles as the backtest (8).

**Long history** (more than one contract, or before mid-2026) needs: the roll between contracts in `ctd history`, baskets from the derived table before the TCF files start (2023-12-11), and a repo rule before May 2018 (roadmap phase 4).

## 8. Validation

- **Unit tests**:
  - accrued interest;
  - price/yield round trip to 1e-10 with the single pricing function;
  - CF formula vs CME's table for ZN, TN, ZB and UB;
  - delivery calendars vs CME's published calendar, and option expiry dates vs every expiry CME has stated since 2016;
  - a bond crossing the 25-year ZB/UB boundary between contract months;
  - a note crossing the ZN grade change: 91282CFV8 (4⅛% Nov 2032), 9.46y remaining for June 2023 (deliverable under the 10-year cap), 9.21y for September 2023 (not deliverable under the 8-year cap);
  - forward price vs a hand carry calculation including a coupon between today and delivery;
  - settlement on a coupon date; end-of-month maturities;
  - crossover root-finding on a synthetic two-bond basket with a known answer;
  - term repo compounding; a flat SR1 strip giving back flat SOFR;
  - region-weighted DV01 vs finite differences of the expected envelope on a synthetic basket;
  - digitals and probabilities against a normal option model with known probabilities.
- **Independent checks**: a handful of bonds vs QuantLib (test dependency only) or TreasuryDirect published values.
- **Sanity**: on a flat 6% curve all converted prices ≈ 100; below 6% low-duration bonds are CTD, above 6% high-duration.
- **Backtest**: run historical mode over past cycles with large moves (2022–23; the 2026 long-end sell-off). Score probabilities against the actual CTD at delivery (Brier score and a reliability plot; published as the calibration output).
  - The actual CTD is computed from prices: on each delivery day, the bond with the smallest gross basis (cash price − futures × CF). The final futures price is fixed on the last trading day, but the CTD can still change over the last 7 delivery days.
  - Flag a cycle as ambiguous when the two smallest bases are within price noise (TreasuryDirect prices are rounded and struck at a different time from the futures settlement), and exclude it from scoring.
  - CME delivery reports aren't part of the core build (CME posts only the current month); a report saved by hand is an optional validation input ([outputs.md](outputs.md), Data dependencies).
  - Check that the model shows the switches reported in 2026 (ZB moving along the basket in August and October). Score each contract separately; report ZN cycles before September 2023 apart.
- **Daily envelope check**: does yesterday's envelope, moved by the day's yield change (the change in yesterday's CTD's forward yield), predict today's CTD? A miss is a near-tie, a relative move a parallel shift can't capture, or a horizon change. Cheap, daily, and it separates parallel moves from relative ones.
- **Trial run, 2026-09-01 to 10-23** (the four December contracts, 37 dates each; light model and the single-date outputs, [roadmap.md](roadmap.md) 1c.1–1c.5, from the derived tables):
  - Probabilities summed to 1 and fell with distance on every date but one: ZNZ6 on 10-19, two switches 2.7bp apart with wing digitals of 4.2% and 3.2% from 64ths-rounded puts, clipped as designed (sum 1.010).
  - Across the 10-15/10-16 seam, where options switch from Databento to the bulletin, the headline DV01 moved as on any other day (ZBZ6 $137.8k to $138.0k, ZNZ6 $61.4k to $61.1k, UBZ6 and TNZ6 unchanged).
  - ZBZ6's CTD moved to the low-coupon bonds (2⅞% Aug-45, 3% Nov-44, 2½% Feb-45) from 09-28 to 10-13 as its forward yield rose from 5.35% (09-22) to 5.78% (10-05), and back to the 2045 coupon bonds as it fell, consistent with the ZB switches reported in 2026. UBZ6 did the same; TNZ6's CTD never changed.
  - The envelope check predicted today's CTD on 25 of 36 days for ZBZ6, 33 for UBZ6, 36 for TNZ6 and 22 for ZNZ6. ZBZ6's misses were mostly near-ties (4 of 7 after a switch within 5bp); ZNZ6's were the delivery-date flips that led to the rule in 5.2.
- **Sensitivity**: β ± 0.05; horizon first vs last delivery; vol ± 10%; smile-implied vs ATM-normal probabilities; interpolated vs √T vol; convolution vs rescaling to the horizon; grid tolerance and cap; flat vs stripped repo; GC vs 50bp special CTD repo; with vs without `c_i`.
- **Cross-check**: dealer/Bloomberg CTD scenarios when available.

## 9. Known limitations

- **One factor**: independent slope moves are only approximated (5.7); probabilities near closely spaced crossovers are unreliable.
- **Bond prices**: free prices are lagged and rounded; a few ticks of noise moves crossovers.
- **Timing gap between TreasuryDirect prices and the futures settlement.** Even with end-of-day prices, the recentring gap's daily change is a yield offset common to all four contracts, barely related to the day's move: the two snapshots aren't simultaneous. Over 2026-09-01 to 10-23, daily gap changes correlate 0.91–0.95 across the four contracts but only 0.1–0.2 with the day's yield move; in yield terms each contract tracks the four-contract average with correlation 0.96–0.98 and slope 0.8–1.2, standard deviation 1.1–1.6bp, largest −3.6bp (09-25) and +2.8bp (10-22). The gap's level reflects the delivery options (ZB about −8/32 on average, UB about −6/32, ZN and TN about 0). It could be removed by centring on yields consistent with the futures settlements (open-questions.md).
- **No CTD-specific repo**: GC for all bonds; specialness ignored.
- **No fair value**, so no model-to-market check on inputs.
- **ZN's delivery date is genuinely ambiguous.** With the envelope at the first delivery day, the digital weights give the opposite carry sign on 81% of ZNZ6's dates (2026-09-01 to 10-23): each date favours its own bond (the 3⅞% Aug-33 at the first, the 4½% Aug-33 at the last), so both dates are self-consistent and the last-day anchor decides (5.2). ZBZ6, UBZ6 and TNZ6 agree under either anchor on 89–100% of dates.
- **One delivery date for every scenario**: in a sell-off ZN's CTD would be delivered early, in a rally late; a single date is an approximation either way.
- **Option-implied, not traded.** Every option-derived number comes from CME settlements, set from CME's skew whether or not a strike traded (3.1). UB's and TN's digitals, and often their ATM vol, rest on untraded strikes; so does any digital beyond about 1.5σ.
- **The digitals** are measured at option expiry, with less spread than at delivery, so they lean toward today's CTD; they carry 64ths rounding (about 1–3 points each).
- **Option-implied probabilities** are risk-neutral, on futures prices rather than bonds, and extended to the horizon by an assumed normal increment.
- **Far tails** come from SABR extrapolation and can be inflated by rich or floor-priced wing settlements; far crossovers are flagged as extrapolated.
- **Vol across contracts** uses different underlyings (different CTDs, embedded switch options).
- **Carry is today's**, at today's term repo; repo after D isn't known, and SR1 spreads each month's expectation evenly over the month.
- **American exercise** is ignored when inverting out-of-the-money option prices.
- **UB options are thin**; on some days UB vol may have to come from ZB through betas, or from realised vol.
- **Historical mode** uses GC repo only.
- Only ZN, TN, ZB and UB are modelled; other contracts need reference data and validation before use.

## 10. Roadmap

Moved to [roadmap.md](roadmap.md).

## 11. Open questions

Moved to [open-questions.md](open-questions.md).
