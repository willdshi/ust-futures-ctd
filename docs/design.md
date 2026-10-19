# CTD Model: Design

End-of-day model of cheapest-to-deliver (CTD) probabilities, futures fair value and key rate durations for CBOT Treasury futures, built from free public data. Includes a historical mode for building a time series of CTD probabilities and futures durations.

## 1. Goals and non-goals

### Goals
- Focus on **ZN, ZB and UB**: the contracts whose baskets span the widest range of maturities, so a CTD switch moves futures duration the most (section 2). Build and validate on ZN and ZB first, then UB. The model code is contract-agnostic, so other contracts can be added later through reference data alone.
- For a given contract, estimate each deliverable bond's probability of being CTD at delivery.
- Locate the **crossover levels** (factor shifts at which the CTD changes hands) and group bonds into clusters with similar key rate profiles.
- Produce futures **DV01 and key rate DV01s**, both probability-weighted and per cluster.
- Produce a model futures fair value and compare it with the market settlement price (live mode only).
- Run daily from end-of-day data, reproducibly, with every input snapshot stored.
- Build a **history** of CTD probabilities and futures durations from free historical data (section 7).

### Non-goals (v1)
- Intraday or live pricing.
- Pricing the wildcard option (treated as part of the model-to-market residual).
- Full multi-factor term-structure model (later extension, section 10).
- ZT, Z3N, ZF, TN and TWE. Their baskets are narrow (about a year of maturity or less), so switches move duration little. Keep their facts in reference data (section 2) and **collect their market data from day one (section 3.2)**, but don't build or validate models for them in v1.
- Cash-settled Treasury products (micro Treasury yield futures, any yield-based contracts) and non-CME venues. No delivery, so no CTD.

## 2. Contract facts the code must encode

All contracts: quarterly delivery months (Mar, Jun, Sep, Dec); first delivery day is the first business day of the contract month.

| Contract | Face | Original maturity | Remaining maturity (deliverable) | Basket span | CF maturity rounding | Reference CMT (5.4) |
|---|---|---|---|---|---|---|
| **ZN** (10-year) | $100k | ≤ 10y | 6y 6m to 10y from first day of delivery month | ~3.5y | Down to quarter | 7y |
| **ZB** (T-bond) | $100k | — | 15y to under 25y | ~10y | Down to quarter | 20y |
| **UB** (Ultra bond) | $100k | — | 25y and over | ~5y (25–30y) | Down to quarter | 30y |

Other contracts, not in v1 (kept so they can be added later through reference data only):

| Contract | Face | Original maturity | Remaining maturity (deliverable) | CF maturity rounding | Calendar family |
|---|---|---|---|---|---|
| ZT (2-year) | $200k | ≤ 5y 3m | ≥ 1y 9m from first day, ≤ 2y from last day of delivery month | Down to whole month | Short |
| Z3N (3-year) | $200k | ≤ 7y | ≥ 2y 9m from first day, ≤ 3y from last day of delivery month | Down to whole month | Short |
| ZF (5-year) | $100k | ≤ 5y 3m | ≥ 4y 2m from first day of delivery month | Down to whole month | Short |
| TN (Ultra 10-year) | $100k | ≤ 10y | 9y 5m to 10y | Down to quarter | Long |
| TWE (20-year) | $100k | 20y original issue | 19y 2m to under 19y 11m | Down to quarter (verify) | Long |

The figures above are a working summary. **Verify each against the current CBOT rulebook chapter when encoding it**. They live in `reference/` as data (one record per contract, with an effective-from date because CME has changed grades before, e.g. ZB in 2011), never as constants in code.

- **Delivery calendar** (stored per contract month, not computed ad hoc). ZN, ZB and UB share it:
  - last trading day = 7th business day before the last business day of the month;
  - last delivery day = last business day of the month.

  The short contracts (ZT, Z3N, ZF) use a different calendar: last trading day is the last business day of the month, and last delivery day is the 3rd business day of the following month.
- Conversion factor: price per $1 par at a 6% yield, per CME's formula, with remaining maturity rounded down to the quarter. **Live mode reads CME's published table**; the formula is implemented for historical mode and as a test against the table.
- Invoice price = futures settlement × CF × face/100 + accrued interest at delivery date.
- **Basket changes**: re-pull the basket and conversion factors from CME on each contract-month roll and after each auction in any basket's maturity range. New issues can join:
  - new 10-year notes for ZN;
  - new 20-year bonds for ZB;
  - new 30-year bonds for UB;
  - aging 30-year bonds move from UB to ZB once under 25 years.

  Treat CME's list as the source of truth. Reopenings don't change CUSIP, coupon, maturity or CF. Rerun crossovers whenever the basket changes.
- **Baskets are dated, not fixed per contract.** The basket used for a run is the one valid at the horizon date.
- **ZB/UB boundary.** A bond crosses from UB's basket to ZB's when its remaining maturity falls below 25 years. Basket rebuilds (historical mode) must apply the boundary at each contract's first delivery day, so the same bond can be in UB for one contract and ZB for the next.

### Options on futures (reference data per option product)
- ZN, ZB and UB each have listed options (quarterly, serial and weekly expiries). Store the product codes, and which futures contract each expiry settles into, in `reference/`.
- **Quarterly** options settle into the same-month futures contract. **Serial** options (non-quarterly months) settle into the next quarterly contract. **Weekly** options settle into the nearby quarterly contract as of their expiry.
- Expiry calendar per option product: quarterly and serial options stop trading on the last Friday that is at least 2 business days before the last business day of the month *preceding* the option month. Weeklies expire on their named weekday. Store the expiry dates; verify the rule against the rulebook.
- Exercise: American, physically settled into futures, with the premium paid upfront. Discount at SOFR to expiry when inverting prices.
- Strike interval and premium tick per product (stored, not hard-coded). The strike interval limits how finely the digital in 5.7 can resolve a crossover.

## 3. Data sources (all free, end of day)

| Data | Source | Live | History | Known weaknesses |
|---|---|---|---|---|
| Basket and conversion factors | CME tables | Yes | Rebuild from rules + formula | Validate rebuilt baskets against any published past tables |
| Security terms (CUSIP, coupon, maturity, dated date) | TreasuryDirect / FiscalData | Yes | Yes | Include since-matured issues for history |
| Bond prices by CUSIP | TreasuryDirect daily prices | Yes (prior-day close) | Probably (check depth of past-date lookup) | Single price, rounded, lagged; off-the-runs noisy; slow to pull, so cache |
| Futures settlements (all eight Treasury contracts, all listed months) | CME settlements | Yes | **No** (paid DataMine) | Collection may be manual; respect terms of use |
| Futures option settlements by strike (section 3.1) | CME settlements | Yes | **No** (paid) | Discrete strikes; noisy far from the money; UB thinner than ZN/ZB |
| Deliveries by contract (delivered CUSIPs, if published) | CME delivery reports | Delivery months | **No** | Ground truth for backtest scoring; confirm what CME publishes |
| Constant-maturity yields | Treasury par curve (CMT), FRED | Yes | Yes, decades | Smoothed curve, not bond-specific |
| GC funding | NY Fed SOFR (also TGCR, BGCR) | Yes | Since 2018 | Overnight only |
| 1-month and 3-month SOFR, 30-day fed funds futures | CME settlements | Yes | **No** | For stepped/stripped repo path |
| CTD-specific repo | **Not available free** | — | — | Backed out by calibration (5.8) in live mode |

Design rules:
- **Every raw file is stored as downloaded, keyed by as-of date**; the model reads only from that store. Re-running any past date gives the same answer.
- **Collect broadly, model narrowly.** Data that can't be backfilled for free is collected every business day from day one, for every product listed in 3.2, whether or not the model uses it yet (section 3.2).

### 3.1 Options chain required

Daily, for all eight Treasury futures contracts, store the full CME option settlement file as downloaded (the model reads ZN, ZB and UB). The model needs these fields from it:

| Field | Use |
|---|---|
| As-of date, option product, expiry date | Keys; expiry drives the term-structure interpolation |
| Underlying futures contract and its settlement price | Moneyness; mapping vol to the right CTD |
| Put/call, strike, settlement premium | Implied vol, skew, digitals |
| Volume and open interest (if on the settlement page) | Liquidity tiebreaker only; the filters below are price-based |

Coverage:
- **Expiries**: every listed expiry (quarterly, serial and all weeklies) on every listed underlying month. The model chooses which to use; storing all of them is cheap, keeps past dates reproducible, and can't be done later.
- **Strikes**: the full chain, both puts and calls. Skew and digitals need strikes out to the furthest crossover (±4S, section 5.6), not just near the money.

How the model uses the chain (section 5.5, 5.7):
- **ATM vol**: out-of-the-money puts and calls nearest the money, inverted with a normal (Bachelier) model on the futures price. Early-exercise value is ignored for out-of-the-money strikes (flag in diagnostics). Check put-call parity at the strike nearest the money.
- **Skew**: implied vol by strike per expiry, re-expressed in bp-of-yield moneyness using the futures DV01 of that expiry's underlying.
- **Crossover-strike vol**: the skew interpolated at the futures price equivalent to each crossover.
- **Digitals**: put-spread slope between adjacent strikes that straddle each crossover's futures price.
- **Term structure**: the two expiries that bracket the horizon (5.5 step 3). The later one is usually a serial or weekly on the *next* quarterly contract.

Filters and fallbacks:
- Drop strikes with a settlement at the minimum tick, deep in-the-money strikes, and prices that break monotonicity or convexity in strike.
- Skip an expiry with fewer than a minimum number of usable strikes (a parameter, initially 5).
- If no expiry is usable (most likely for UB, whose options are thinner than ZN's and ZB's), use the following, in order:
  1. Map vol from the neighbouring contract through betas (UB from ZB, ZB from UB).
  2. Use realised vol (as in historical mode).
- Record the source used in diagnostics.

### 3.2 Collection policy

A free source that only shows recent days is lost for good on any day it isn't pulled. So collection is wider than the model and runs every business day.

**Not backfillable for free: pull every business day, full files, unfiltered.**
- CME futures settlements: all eight Treasury contracts (ZT, Z3N, ZF, ZN, TN, TWE, ZB, UB), all listed months, including calendar-spread settlements if published.
- CME option settlements: options on all eight, every listed expiry, every strike, puts and calls.
- CME deliverable baskets and conversion factor tables for every listed contract month, pulled daily so changes after auctions are captured. CME doesn't keep past versions.
- CME delivery reports during delivery months (actual deliveries; backtest ground truth).
- CME 1-month SOFR, 3-month SOFR and 30-day fed funds futures settlements (repo path, 5.3).
- TreasuryDirect daily prices: the whole file, every CUSIP, every day. How far back past dates can be looked up is still an open question (section 11), so don't rely on it.

**Backfillable: pull daily anyway, and backfill once at setup.**
- Treasury par curve (CMT), FRED series.
- NY Fed SOFR, TGCR and BGCR.
- FiscalData / TreasuryDirect security terms and auction results, including matured issues.

**Operations**
- `ctd fetch` runs on a schedule every business day after CME final settlements are published. It is idempotent: re-running a date never overwrites a stored file, it only fills what's missing.
- Each date gets a manifest listing every expected file and its status. A completeness check flags missing products, and a gap triggers retry and an alert.
- Recovery window for a missed run: CME futures and option settlement pages show **5 trailing business days**. The windows for CF tables and delivery reports are still to be confirmed (section 11); treat them as zero until then. Beyond the window, record the gap rather than fill it from another source.
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
  risk/            # DV01, key rate DV01s, cluster profiles
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
  - accrued at the delivery date (invoice, carry);
  - forward KRDs measured from the horizon date.

### 5.2 Horizon
- Compute each likely CTD's daily carry: coupon accrual minus repo on dirty price.
- Positive carry: horizon = last delivery day. Negative: first delivery day.
- **One horizon for the whole basket**, not one per bond (the short commits to a date before knowing which bond wins).
- If carry is near zero, or slightly negative with a crossover near: run both dates and take whichever gives the lower expected converted price for the short. A special CTD repo lowers holding cost and pushes delivery later.

### 5.3 Term GC repo and forward prices
- Overnight rate: **SOFR** (closest proxy for DVP GC on basket bonds).
- Term rate to horizon, actual/360 compounding:
  `R_term = [Π_i (1 + r_i · d_i/360) − 1] × 360/D`
- Path for `r_i`, in increasing effort:
  1. **Flat** at today's SOFR (or 5-day average). Default.
  2. **Stepped** at FOMC dates using fed funds / 1-month SOFR futures. Use if a meeting falls before the horizon.
  3. **Strip of 1-month SOFR futures**. Use if the carry sign is close.
- **Year-end/month-end turn**: for December contracts add a turn adjustment with options 1 or 2 (option 3 includes it).
- Ignore term premium initially; implied CTD repo absorbs it.
- Sensitivity: 10bp repo error ≈ 0.013 points on a ZB bond over ~0.2 years (≈0.3bp of crossover); matters more for the carry-sign/horizon decision.
- Forward clean price at T for each bond from dirty price, term repo, and coupons before T. Term GC for all bonds by default; override for CTD/near-CTDs when a specific rate is known.
- Convert to forward yield `y_i^fwd`. Everything is centred on these.

### 5.4 Factor and betas
- Factor `x` = constant-maturity yield near the current CTD, per contract (section 2 table): **7-year for ZN, 20-year for ZB, 30-year for UB**.
- For each CMT point across the basket range (ZN ~6–11y, ZB ~14–26y, UB ~24–30y, 1-year steps), regress yield changes on the reference: `Δy(τ) = β(τ)·Δx + ε(τ)`.
  - 2–3 day or weekly changes; 6–12 month window or exponential weights (half-life ~3 months).
  - Shrink betas slightly toward 1.
  - Also estimate on **sell-off days only**; use those if materially different.
- Interpolate β at each bond's remaining maturity at T.
- Store residual SDs `σ_ε(τ)` and the residual SD of the spread between candidate bonds (used in 5.7; diagnostic for one-factor adequacy: under ~4bp over the horizon is fine, above ~6bp suggests a second factor).

### 5.5 Volatility
Live mode:
1. Futures option implied vol from the contract's own options chain (section 3.1), ATM to start.
2. Price vol → normal yield vol of each expiry's CTD: `σ_y ≈ σ_price × F / (100 × D_F)`, using the CTD duration of **that expiry's underlying contract**.
3. **Interpolate total variance to the horizon** between the bracketing expiries:
   `V(T) = σ_y² T`, linear in time between expiries; `σ_y(T_h) = √(V(T_h)/T_h)`.
   - Example for a December contract with a December horizon: December quarterly options on December futures expire in late November. January serial options, or a December weekly, on March futures expire in late December. Those two bracket the horizon.
   - Captures vol term structure and event variance (e.g. December FOMC).
   - When the later expiry's underlying is the next contract, adjust its vol for that contract's different CTD maturity via betas. This matters most for ZB, whose basket is widest.
   **Fallback**: square-root-of-time scaling from a single expiry, when the horizon is close to the first expiry or only one expiry is usable.
4. To factor units: `σ_x = σ_y / β_CTD`; width `S = σ_x √T_h`.
5. Iterate: after crossovers are found, re-read vol at the **crossover strike** (skew interpolated in bp-of-yield moneyness) and repeat 2–4 until stable (1–2 passes).

Historical mode: realised vol (EWMA of daily changes in the reference CMT yield) replaces implied vol (section 7).

### 5.6 Pricing grid
For z from −4S to +4S in 1bp steps:
```
y_i(z) = y_i^fwd + c_i + β_i · z
P_i(z) = clean price at T from y_i(z)
C_i(z) = P_i(z) / CF_i
```
`c_i` solved per bond so that `E[P_i(z)] = forward price` under z ~ N(0, S²) (convexity adjustment, ~1–2bp for ZB).

### 5.7 Envelope, crossovers and probabilities
- `F_model(z) = min_i C_i(z)`; record the argmin.
- Root-find the exact z where the argmin changes: crossovers `z_1 < z_2 < …`. Expect ZN: usually one major switch (6.5–7y cluster → 9.5–10y cluster); ZB: a staircase of two or three; UB: one or two, between the shortest and longest 30-year issues.
- Region probability: `π = Φ(z_{k+1}/S_k) − Φ(z_k/S_k)`.
- Slope-adjusted width per crossover between bonds S and L:
  `S_eff = √(S² + (m · σ_ε,spread)²)`, `m = D_L / (D_L − D_S)` (beta-adjusted; level measured at the short bond's yield). Use `S_eff` **for probabilities only**.
- Live-mode alternative: market-implied probability at each crossover from the put-strike slope of option settlements (digital), divided by the discount factor, then horizon-adjusted. Report alongside the model value.

### 5.8 Fair value and calibration (live mode)
- Model futures price = `E[F_model(z)]`.
- Compare with market settlement. Residual includes CTD repo specialness, end-of-month option, wildcard, price noise.
- Solve for the **CTD repo rate** that makes model = market; report as "implied CTD repo", a fitted parameter, not an observation. Expect jumps around reopenings (supply eases specialness).

### 5.9 Risk
- Futures DV01: bump z (and separately all yields in parallel) and difference `E[F_model]`.
- Key rate DV01s: `KRD01_F,k = Σ_i π_i · KRD01_i,k / CF_i`, using forward KRDs at T.
- Clusters: group bonds with similar key rate profiles (same dominant key rate, DV01 within ~5%). Report expected (blended) KRDs and each cluster's KRDs.
- Blended KRDs are local; they understate how fast weights change near a crossover (negative convexity).

### 5.10 End-of-month option (phase 3)
- After the last trading day the invoice price is fixed and the short chooses the bond over the remaining delivery days. That's 7 business days for ZN, ZB and UB. Price it as a short-dated switch option with the same envelope machinery; add to fair value.

## 6. Outputs (daily, per contract)

- Basket table: CUSIP, coupon, maturity, CF, price, forward price, forward yield, β, carry, repo used, converted forward price, net basis, implied repo.
- Crossover table: from-bond → to-bond, crossover z (bp), equivalent futures price, distance from forward, probability (base, slope-adjusted, option-implied).
- CTD probabilities per bond and per cluster.
- Fair value vs market, implied CTD repo (live mode).
- DV01 and key rate DV01s: blended and per cluster.
- Diagnostics: vol source, strike and expiries used; horizon chosen and why; repo path used; beta window; residual SDs; warnings.
- Optional diagnostic: CTD amount outstanding vs futures open interest (squeeze risk; explains extreme implied repo). Not a model input.
- Chart: converted forward prices vs factor shift (the envelope), with the shift distribution overlaid.

## 7. Historical mode

Goal: time series of CTD probabilities, futures DV01 and KRDs for past contracts, from free data.

- **Baskets**: rebuild per past contract from the issue list (including since-matured issues) and eligibility rules; compute CFs with the formula. Validate against any published past tables. This is the main effort.
- **Prices**: past TreasuryDirect prices by CUSIP; cache aggressively.
- **Repo**: SOFR (from 2018); GC only, no specialness.
- **Vol**: realised EWMA vol of the reference CMT yield replaces implied vol.
- **No futures/option history** (paid), so historical mode drops: fair value check, implied CTD repo, option-implied probabilities. Probabilities are realised-vol based, not risk-neutral.
- Futures DV01/KRDs need no futures price: they are probability-weighted basket DV01s over conversion factors.
- Runtime is trivial; data collection is the constraint.
- Doubles as the backtest (section 8).

## 8. Validation

- **Unit tests**: accrued interest; price/yield round trip to 1e-10 with the single pricing function; CF formula vs CME table for ZN, ZB and UB; delivery calendars, and option expiry dates vs CME's published calendar; a bond crossing the 25-year ZB/UB boundary between contract months; forward price vs carry hand calculation including a coupon between today and delivery; settlement on a coupon date; end-of-month maturities; crossover root-finding on a synthetic two-bond basket with a known answer; term repo compounding.
- **Independent checks**: a handful of bonds vs QuantLib (test dependency only) or TreasuryDirect published values.
- **Sanity**: on a flat 6% curve all converted prices ≈ 100; below 6% low-duration bonds are CTD, above 6% high-duration.
- **Backtest**: run historical mode over past cycles with large moves (2022–23; the 2026 long-end sell-off). Score probabilities against the actual CTD at delivery (Brier score). Check that the model shows the switches reported in 2026 (ZB moving along the basket in August and October). Score ZN, ZB and UB separately.
- **Sensitivity**: β ± 0.05; horizon first vs last delivery; vol ± 10%; crossover-strike vs ATM vol; interpolated vs √T vol; flat vs stripped repo; GC vs 50bp special CTD repo.
- **Cross-check**: dealer/Bloomberg CTD scenarios when available.

## 9. Known limitations

- One factor: independent slope moves only approximated (5.7); probabilities near closely spaced crossovers unreliable.
- Free bond prices are lagged and rounded; a few ticks of noise moves crossovers.
- No free CTD-specific repo; implied repo absorbs all other errors.
- Vol interpolation across contracts uses different underlyings (different CTDs, embedded switch options).
- Option-implied probabilities are risk-neutral, measured at option expiry, and on futures prices rather than bonds.
- UB options are thinner than ZN and ZB options; on some days UB vol will come from ZB through betas, or from realised vol.
- Only ZN, ZB and UB are modelled. Other contracts have collected data but need reference data and validation before use.
- American exercise is ignored when inverting out-of-the-money option prices.
- Historical mode uses realised vol and GC repo only.

## 10. Roadmap

1. **Phase 1, deterministic core** (ZN, ZB): raw data store and fetchers, bond math with tests, CF tables and formula, term GC repo (flat), forward prices, parallel-shift grid and crossovers (no probabilities). Check against published switch levels. **Before anything else, start the scheduled daily collection in section 3.2 (all eight contracts, full options chains, SOFR and fed funds futures, CF tables, TreasuryDirect prices), with manifests and gap alerts.** Reference data (grades, calendars, option products) for ZN, ZB and UB.
2. **Phase 2, one-factor model**: betas, vol calibration (single expiry, √T), probabilities, fair value, implied CTD repo, KRDs, daily report. First on ZN and ZB, then UB once they pass the phase-2 checks.
3. **Phase 3, refinements**: total-variance vol interpolation, crossover-strike vol iteration, slope-adjusted widths, option-implied digitals, horizon decision logic, stepped/stripped repo path, end-of-month option.
4. **Phase 4, history and extensions**: basket rebuild, historical runner with realised vol, backtest scoring; two-/three-factor PCA simulation with idiosyncratic noise; other contracts (ZT, Z3N, ZF, TN, TWE) if wanted.

## 11. Open questions

- How to collect CME settlements reliably (manual download vs vendor) within their terms of use?
- How many past days do CME's CF table and delivery report pages still show? (Futures and option settlements: 5 business days, confirmed.)
- What exactly do CME's delivery reports publish (delivered CUSIPs and amounts, or only totals)?
- How far back does TreasuryDirect's past-date price lookup go?
- Which beta window and decay best predicts realised basket moves (settle by backtest)?
- Realised-vol window for historical mode, and how it compares with implied vol once live snapshots accumulate?
- The Treasury par curve only has 1, 2, 3, 5, 7, 10, 20 and 30-year points. Should the 1-year-step betas (5.4) come from interpolating the curve, or from a fitted curve on bond prices? This matters most for ZB (only 20y and 30y in its range) and UB (only 30y in its range, so its betas are extrapolated).
- How often are UB options too thin to use, and is ZB vol mapped through betas a good enough substitute?
- Which weekly expiries are listed today for ZN, ZB and UB options (Monday to Friday weeklies vary by product)? Confirm before building the expiry calendar.