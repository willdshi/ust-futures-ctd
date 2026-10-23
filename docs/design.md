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
- Produce the **comparison series** asset managers need: CTD-label DV01 (what vendor systems report, which jumps at label flips) and constant-CTD DV01, plus DV01-weighted effective maturity (section 6).
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
| Futures settlements (all six Treasury contracts, all listed months) | CME settlements | Yes | Front two contracts from 2016, paid one-off Databento backfill (data.md §5.11) | Used only for vol conversion (5.5) and open interest; collection may be manual; respect terms of use |
| Futures daily bars, cross-check (six Treasury contracts) | Yahoo Finance chart endpoint | Yes | Listed contracts since listing; continuous front month from 2000 (2010 for UB, TN) | Closes equal CME settlements on dates checked; misses some listed months (e.g. June 2027 ZT, ZF, ZN, TN); continuous series rolls on the last trading day, unadjusted; unofficial endpoint, personal-use terms |
| Futures option settlements by strike (section 3.1) | CME settlements | Yes | **No** (paid) | Discrete strikes; noisy far from the money; UB thinner than ZN/ZB |
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

Daily, for all six Treasury futures contracts, store the full CME option settlements as downloaded (the model reads ZN, TN, ZB and UB). While cmegroup.com blocks scripts, they come as the Daily Bulletin's Section 42 PDF, which covers all six contracts, every listed expiry and strike, weeklies included (stored, not used by the model). CME's per-product option settlement files are collected only if automated access ever works. The model needs these fields:

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
  data/            # fetchers + raw store (one module per source)
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
                   # `ctd history --contract ZB --from 2022-01-01 --to 2026-10-16`
tests/
docs/design.md
CLAUDE.md
```

- Python, numpy/scipy/pandas.
- Pure functions in `bonds/`, `funding/`, `model/`, `risk/`; I/O only in `data/` and `report/`.
- **Reading the store.** The raw store keeps its layout (one folder per as-of date, files as downloaded, a manifest per date); the model never touches paths or file formats directly.
  - **Per-date readers** (`data/`, phase 1b): one function per source turns one as-of date's raw files into a clean table, e.g. TreasuryDirect prices as CUSIP, coupon, maturity, price. Enough for any single-date run.
  - **Derived tables** (phase 2, when betas first need a time series): Parquet tables across dates, e.g. `data/derived/td_prices.parquet` with one row per date and CUSIP, built by running the per-date readers over the store (one parser per source). They are a cache: rebuilt with one command, never edited by hand, each recording the raw files it was built from. The raw store stays the source of truth, and a derived table never holds data the raw store lacks.
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
- Positive carry: horizon = last delivery day. Negative: first delivery day.
- **One horizon for the whole basket**, not one per bond (the short commits to a date before knowing which bond wins).
- If carry is near zero, or slightly negative with a crossover near: run both dates and take whichever gives the lower expected converted price for the short. This expectation is an internal decision rule, not a published fair value.

### 5.3 Term GC repo and forward prices
- Overnight rate: **SOFR** (closest proxy for DVP GC on basket bonds).
- Term rate to horizon, actual/360 compounding:
  `R_term = [Π_i (1 + r_i · d_i/360) − 1] × 360/D`
- Path for `r_i`, in increasing effort:
  1. **Flat** at today's SOFR (or 5-day average). Default.
  2. **Stepped** at FOMC dates using fed funds / 1-month SOFR futures. Use if a meeting falls before the horizon.
  3. **Strip of 1-month SOFR futures**. Use if the carry sign is close.
- **Year-end/month-end turn**: for December contracts add a turn adjustment with options 1 or 2 (option 3 includes it).
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

Historical mode: realised vol (EWMA of daily changes in the reference CMT yield) replaces implied vol (section 7), with a single normal width.

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
- **Key rate DV01s**: same weighting, with each bond's forward KRDs at T (cash-flow bucketing with triangular (tent) weights; curve-based KRDs later if needed). Key-rate grid: **2, 5, 7, 10, 15, 20, 25, 30 years**, fixed ([decisions.md](decisions.md)). The 15 and 25-year nodes make a ZB switch (about 15y to about 25y) visible.
- **Units**: $/bp per $100mm notional by default; per contract also available.
- **Clusters**: group bonds with similar key rate profiles (same dominant key rate, DV01 within ~5%). Report expected (blended) KRDs and each cluster's KRDs.
- **Scenarios (±1σ, ±2σ)**: shift every forward yield by kσ × β_i, keep the remaining vol, and recompute crossovers, probabilities, DV01 and KRDs at the shifted state. Don't just read off the CTD at the shifted yield, which jumps and overstates the change. Record whether the smile is treated as sticky strike or sticky moneyness.
- **Duration profile**: blended DV01 and KRDs as a function of the shift (about −100 to +100bp); ±1σ and ±2σ are points on it. Label shifts both in bp and in percentiles of the move-to-horizon distribution (σ√T).
- **Comparison measures** (section 6): *CTD-label DV01* is DV01/CF of the single CTD at the forward (z = 0), the number most vendor systems report; it jumps when the label flips. *Constant-CTD DV01* holds one bond fixed through the series, so its gap to the probability-weighted DV01 is the part of the change caused by the basket.
- **Effective maturity**: DV01-weighted, `Σ_k KRD_k · T_k / Σ_k KRD_k` over the key-rate grid. A cleaner switch signal than DV01, since it barely moves with yield level or roll-down.
- **Distance to switch**: shift to the nearest crossover on each side, in bp and in σ.
- Blended KRDs are local; they understate how fast weights change near a crossover (negative convexity). The slope of the duration profile carries futures gamma.

### 5.10 End-of-month option: out of scope
Affects futures value, not durations or the probability of a major switch materially. Not modelled (section 1).

### 5.11 Light model (first build)
The lightest version skips the factor model, the betas and the vol fitting: find the futures price at which each switch happens, then read the probability of the futures finishing below it from the put settlements. One basket, one option chain, a loop over shifts. It is the same calculation as the raw put-spread digital diagnostic (5.5.1, 5.7), so the work carries over to the full model.

1. **Basket and converted prices.**
   - Basket and conversion factors from CME's TCF file for the contract (a shortcut: the full model rebuilds the basket and uses the CF formula, section 2); clean prices from TreasuryDirect.
   - Forward clean price of each bond at the delivery date with flat SOFR (5.3, path 1), divided by its CF.
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
- **Remaining switch value**: at expiry the futures still include some switch value, which biases the tail probabilities slightly upward (as in 5.5.1 step 3).
- **Outputs**: switch points and CTD probabilities only; no DV01, KRDs or duration profile.

For a snapshot of where the market prices the switch today, that's a reasonable trade-off.

## 6. Outputs (daily, per contract)

The published charts and their tiers are specified in [outputs.md](outputs.md). The headline is duration (chart 1: duration profile with key-rate shape; chart 2: diverging key-rate change bars; chart 3: DV01 time series with effective maturity). The model computes, per contract and date:

**Tier 1**
- Probability-weighted DV01 and KRDs on the key-rate grid, blended and per cluster (5.9).
- Duration profile across shifts, with ±1σ and ±2σ (or the 5th, 25th, 75th and 95th percentiles), and the change in each KRD versus today at those points.
- CTD-label DV01 and constant-CTD DV01 alongside the probability-weighted DV01.
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

Goal: time series of CTD probabilities, futures DV01 and KRDs for past contracts, from free data.

**Start: 2016.** Historical mode goes back to the March 2016 contract month and no further, because earlier Treasury futures rule changes aren't handled. Rule changes since then (e.g. ZN's 8-year cap from September 2023) are dated reference records.

- **Baskets**: rebuild per past contract from the issue list (including since-matured issues) and eligibility rules; compute CFs with the formula. Validate against any published past tables. This is the main effort.
- **Prices**: past TreasuryDirect prices by CUSIP, stored from 2016 (available from May 2008). Before about September 2008 the files have no coupon or maturity columns; join on CUSIP to the security terms.
- **Repo**: SOFR (from 2018); GC only.
- **Vol**: realised EWMA vol of the reference CMT yield replaces implied vol.
- **Futures settlements**: front two contracts of each product from 2016, from a paid one-off Databento backfill (data.md §5.11), for open interest, the roll and the futures price. From 2026-10-14 the CME files are the record; on overlapping dates Databento cross-checks them and never fills their gaps.
- **No option history** (paid), so historical mode drops option-implied probabilities. Probabilities are realised-vol based, not risk-neutral.
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
- Historical mode uses realised vol and GC repo only.

## 10. Roadmap

1. **Phase 1, deterministic core** (ZN, ZB): raw data store and fetchers, bond math with tests, CF formula (tested against saved CME tables), term GC repo (flat), forward prices, parallel-shift grid and crossovers (no probabilities). Check against published switch levels. **Before anything else, start the scheduled daily collection in section 3.2 (all six contracts, full options chains, SOFR and fed funds futures, TreasuryDirect prices), with manifests and gap alerts.** Reference data (grades, calendars, option products) for ZN, ZB and UB.

   **Phase 1b, light model (5.11)**: switch points as futures prices and CTD probabilities from put-spread digitals, for ZNZ6 and ZBZ6, built one date at a time starting with 2026-10-21 (a complete snapshot in the store). Every run is `ctd run --contract ZBZ6 --asof D`, reading only from the store, so later dates are a loop. Progress is tracked by the checkboxes below; tick an item in the commit that finishes it.

   *A. Foundation (phase 1 items the light model needs)*
   1. [x] Dates and conventions (`bonds/schedule.py`): coupon schedule from maturity (scheduled, unadjusted; end-of-month maturities), actual/actual accrued, previous/next coupon, T+1 settlement on the `sifma` calendar.
   2. [x] The single pricing function (`bonds/pricing.py`, 5.1): dirty price from yield, clean = dirty − accrued, yield from price by root-finding, DV01/duration from the same function.
   3. [x] CF formula (`bonds/conversionfactor.py`), tested against the stored TCF files: matches every row from December 2023 (the light model reads CFs from TCF, but the test checks the date code).
   4. [x] Store readers (`parse`/`read` in each source's module in `data/`, no network): TreasuryDirect prices with coupon and maturity (end of day, or the buy/sell midpoint for a provisional date, [decisions.md](decisions.md)); TCF basket and CFs per contract; CME futures settlements (`F_market`); SOFR from the NY Fed.
   5. [ ] Delivery calendar per contract month (first and last delivery days), stored as reference data (section 2).
   6. [ ] Flat-SOFR term repo and forward clean price with coupons before delivery (5.3).
   7. [ ] Envelope and switch points (`model/`): parallel shifts, cheapest converted price, exact root-finding of each switch.

   *B. Light-model pieces*
   1. [ ] Option reference data for OZN and OZB: expiry rule and dates (checked against CME's calendar), strike interval, premium tick (64ths), underlying contract per expiry.
   2. [ ] Section 42 parser (section 11 has the layout): quarterly and serial blocks only, weeklies skipped; per-block checks (strikes increasing, columns complete, TOTAL line, trade date = as-of); strikes and 64ths converted. Tested against the 2026-10-16 hand check.
   3. [ ] Digitals: SOFR discount factor to expiry; strike pair bracketing each `K_k`, interpolating between neighbouring pairs; calls on the rally side; rules for missing, minimum-tick or zero-open-interest premiums; a switch beyond the listed strikes is flagged, not extrapolated.
   4. [ ] Probability assembly: regions on each side, remainder to the current CTD; checks that probabilities sum to 1 and fall with distance (warn otherwise).
   5. [ ] Output: `ctd run` prints a basket table and a crossover table (from → to bond, shift in bp, `K_k`, strikes used, digital, region probabilities, warnings) and the recentring gap `F_market − E(0)`.
   6. [ ] Run 2026-10-14 to date for ZNZ6 and ZBZ6, then daily after the fetch.

   *C. Definition of done*
   - [ ] Section 8 unit tests for the pieces built: accrued, price/yield round trip, CF formula vs TCF, forward price across a coupon, synthetic two-bond crossover, term repo compounding; plus the parser on a stored bulletin.
   - [ ] Sanity: flat 6% curve gives converted prices ≈ 100.
   - [ ] ZBZ6 and ZNZ6 on 2026-10-21: plausible switch points and CTD, probabilities summing to 1 and falling with distance, results reproducible from the store.
   - [ ] A series from 2026-10-14 that runs daily.

   *D. Open questions for phase 1b*
   - **Delivery date for the forward**: the light model has no horizon logic (5.2). Proposed default: last delivery day if the CTD's carry is positive, first if negative.
   - **Which yield to shift**: forward yields (consistent with the full model, 5.6) or today's yields. Proposed: forward yields.
   - **Recentring gap**: `F_market` settles at 2pm CT and TreasuryDirect prices are struck earlier, so `F_market − E(0)` also absorbs that timing difference. Log it daily; what size counts as inconsistent inputs?
   - **Saved results**: print only, or also write results per date (e.g. a results directory) so a series can be built and compared later?
   - **Which TreasuryDirect snapshot matches the futures settlement**: the model uses end of day ([decisions.md](decisions.md)). Confirm it on a few dates: compare the CTD's gross basis from end of day and from buy/sell against the 2pm CT settlement (the snapshot taken at the same time shows the least correlation between basis changes and futures changes), and find TreasuryDirect's own definition of the columns.
   - **After December option expiry (about 2026-11-20)**: stop the light model on December contracts, or roll to March contracts and the January serial (with the expiry-after-horizon issue in section 11)?
2. **Phase 2, one-factor model**: betas, vol calibration (single expiry, √T), probabilities, region-weighted DV01 and KRDs, scenarios and duration profile, comparison series and effective maturity, distance to switch, event flags, daily report with charts 1–3. First on ZN and ZB, then UB and TN once they pass the phase-2 checks.

   **First milestone (before the late-November 2026 roll):** Tier 1 for ZN and ZB plus the December/March roll comparison ([outputs.md](outputs.md)). That needs phases 1 and 2 for ZN and ZB. Chart 3's time series needs history: until the historical runner (phase 4) exists, it covers only the dates since live runs began (section 11).
3. **Phase 3, refinements**: total-variance vol interpolation; smile-implied distribution (SABR fit, digitals, envelope mapping, recentring, horizon convolution) with quantile-based grid window; slope adjustment by convolution; digital and ATM-normal diagnostics; horizon decision logic; stepped/stripped repo path. Per-crossover vols (5.5.2) only as a stopgap if the smile fit lags.
4. **Phase 4, history and extensions**: basket rebuild, historical runner with realised vol, backtest scoring and reliability plot; Tier 2 outputs and the fragility dashboard (with its new sources, section 3); two-/three-factor PCA simulation with idiosyncratic noise; other contracts (ZT, ZF) if wanted. Far down the wishlist: infer slope vol from market futures prices.

## 11. Open questions

- How to collect CME settlements reliably? cmegroup.com refuses scripted connections (bot protection), and CME's public FTP server carries only the TCF tables of what's needed. Until a paid feed is chosen, futures settlement JSONs and the options bulletin are downloaded in a browser with the `ctd bookmarklet` (one click a day). Which feed, if any (DataMine, Databento, Barchart OnDemand)? Databento is already used for the futures history before 2026-10-14 (front two contracts, one-off; data.md §5.11), which makes it the natural candidate for daily collection too.
- Option settlements from the Section 42 PDF: tested on 2026-10-16 with pdfplumber and pypdf, and the text extracts cleanly (about 3,200 strike rows in 35 pages). Layout: a product and put/call header (e.g. "10Y NOTE CALL", or a weekly such as "HYO OPT WK THU"), then an expiry label ("DEC26"), then one row per strike: strike (1055 = 105.5), open, high, low, close, settlement, change, delta, exercises, volume, open interest, OI change, contract high and low, prices in 64ths. Each block ends in a TOTAL line. The header also states the trade date and FINAL. Check: the 100.5 ZN call in the November serial block (on December futures) settled at 4-61/64 with delta 1.000, against December futures at 105-14.5 (intrinsic 4.95); the December quarterly 100.5 call settled at 4-62/64. Open: write the parser (phase 1b, for the light model in 5.11), reading quarterly and serial blocks and skipping weeklies, and validating each block (strikes increasing, columns complete) because the layout can change without notice.
- How long does CME keep TCF files on its FTP server (December 2023 onwards as of October 2026)?
- Which beta window and decay best predicts realised basket moves (settle by backtest)?
- Realised-vol window for historical mode, and how it compares with implied vol once live snapshots accumulate?
- How to estimate betas between the par curve's published points (1, 2, 3, 5, 7, 10, 20 and 30 years) is worked through in [decisions.md](decisions.md). Starting point: regress at the published tenors and interpolate β linearly, which equals interpolating the curve. No basket needs extrapolation: ZN's bonds sit between the 5, 7 and 10-year points, ZB's between 10, 20 and 30, and UB's (25 to 30 years) between 20 and 30. Still open: whether pooled bond-level betas (possible now, with TreasuryDirect prices stored from 2016) beat node betas in the backtest, and whether ZB should use a reference other than the 20-year CMT.
- Smile-implied distribution when the option expiry is after the horizon (5.5.1 step 5). A contract keeps trading for about a month after its own options expire (quarterly options expire in late November; December futures trade to mid-December and deliver to month-end), and its CTD question matters most then. Its vol then comes from the next contract's options (5.5 step 3).
  - **When it happens:** positive carry (horizon = last delivery day) usually still has two expiries bracketing the horizon, e.g. the January serial (~24 December) and the February serial (late January) for a 31 December horizon, so convolution from the January serial works. Negative carry (horizon = first delivery day) does not: after the December options expire, the first usable expiry is the January serial, three weeks after a 1 December horizon. The ATM path is unaffected, since the √T fallback in 5.5 step 3 already scales down.
  - **Interim choice:** rescale the factor distribution to the horizon, `z_h = z_E × √(V(T_h)/V(T_E))`. This keeps the expiry's skew unchanged, so if anything it overstates skew at the shorter horizon.
  - **Alternative:** deconvolve, fitting a horizon distribution `φ_h` so that `φ_h` convolved with `N(0, V(T_E) − V(T_h))` matches the expiry distribution. It is consistent with step 5 but ill-posed (noise in the fitted wings is amplified), so it is worth trying only if backtests show the rescaling biases tail probabilities.
  - **Also needed either way:** the expiry's distribution is on the *next* contract's futures, so step 3 maps it through that contract's envelope and the betas to the expiring contract's factor (as for the ATM vol in 5.5 step 3). The approximation is weakest for ZB, whose two contracts' CTDs can differ most.
  - **Open:** confirm with history how often this case arises (negative-carry dates after option expiry), and whether rescaling and deconvolution differ materially there.
- How often are UB options too thin to use, and is ZB vol mapped through betas a good enough substitute?
- Which bond does the constant-CTD DV01 hold fixed: the CTD at the start of each contract's series, or today's CTD carried back? It sets what the gap to the probability-weighted line means.
- Chart 3 before the historical runner exists: start the series at the first live run, or bring forward a minimal historical runner (realised vol, rebuilt baskets) for ZN and ZB before the first milestone?
- What CME Pace of the Roll publishes and whether past rolls can be retrieved; month-level open interest already comes from the daily settlements.

Which further outputs to publish was settled in [outputs.md](outputs.md), which replaces the list of candidates that was here. Its "Dropped or reframed" table records what was dropped (basis-trade outputs) and what was reframed (market impact as gross duration transfer, gamma as the slope of the duration profile).
