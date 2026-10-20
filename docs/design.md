# CTD Model: Design

End-of-day model of cheapest-to-deliver (CTD) probabilities and futures key rate durations for CBOT Treasury futures, built from free public data. Includes a historical mode for building a time series of CTD probabilities and futures durations.

## 1. Purpose, goals and non-goals

### Purpose
Output **sensible CTD probabilities and futures durations/KRDs**, as a daily time series, plus **scenarios** (e.g. ±1σ shifts of the factor) showing how far yields must move for futures duration to change materially. The audience is anyone exposed to changing Treasury futures duration: basis traders, duration hedgers, and those watching the effect of CTD switches on the curve.

### Goals
- Focus on **ZN, ZB and UB**: the contracts whose baskets span the widest range of maturities, so a CTD switch moves futures duration the most (section 2). Build and validate on ZN and ZB first, then UB. The model code is contract-agnostic, so other contracts can be added later through reference data alone.
- For a given contract, estimate each deliverable bond's probability of being CTD at delivery.
- Locate the **crossover levels** (factor shifts at which the CTD changes hands) and group bonds into clusters with similar key rate profiles.
- Produce futures **DV01 and key rate DV01s**, both probability-weighted and per cluster.
- Produce **scenario** durations/KRDs at ±1σ (and a duration profile across shifts), recomputing probabilities at each shifted state (5.9).
- Run daily from end-of-day data, reproducibly, with every input snapshot stored.
- Build a **history** of CTD probabilities and futures durations from free historical data (section 7).

### Non-goals (v1)
- **Fair value of the futures contracts.** Not modelled, because the inputs needed to price the contract to the tick aren't available:
  - no CUSIP-specific repo (specialness of the CTD and near-CTDs);
  - no reliable CUSIP-specific pricing relative to the curve (free prices are lagged and rounded);
  - no view on slope/curvature dynamics beyond the one-factor betas.

  Consequently the following are also out of scope: implied CTD repo calibration, the end-of-month option, the wildcard option, and net basis/implied repo outputs. Market futures prices are still collected (section 3.2) and used only where needed (vol conversion, open interest). **Wishlist (far down):** use market futures prices, e.g. the model-to-market residual across contracts, to infer slope vol or other curve dynamics.
- Intraday or live pricing.
- Full multi-factor term-structure model (later extension, section 10).
- ZT, ZF and TN. Their baskets are narrow (about a year of maturity or less), so switches move duration little. Keep their facts in reference data (section 2) and **collect their market data from day one (section 3.2)**, but don't build or validate models for them in v1.
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
| ZF (5-year) | $100k | ≤ 5y 3m | ≥ 4y 2m from first day of delivery month | Down to whole month | Short |
| TN (Ultra 10-year) | $100k | ≤ 10y | 9y 5m to 10y | Down to quarter | Long |

The figures above are a working summary. **Verify each against the current CBOT rulebook chapter when encoding it**. They live in `reference/` as data (one record per contract, with an effective-from date because CME has changed grades before, e.g. ZB in 2011), never as constants in code.

- **Delivery calendar** (stored per contract month, not computed ad hoc). ZN, ZB and UB share it:
  - last trading day = 7th business day before the last business day of the month;
  - last delivery day = last business day of the month.

  The short contracts (ZT, ZF) use a different calendar: last trading day is the last business day of the month, and last delivery day is the 3rd business day of the following month.
- Conversion factor: price per $1 par at a 6% yield, per CME's formula, with remaining maturity rounded down to the quarter. **Computed with the formula in both live and historical mode.** CME's published table (TCF) is validation data, collected daily from CME's public FTP server (section 3.2), and the formula is tested against it.
- Invoice price = futures settlement × CF × face/100 + accrued interest at delivery date.
- **Basket changes**: rebuild each basket from the eligibility rules and Treasury security terms on each contract-month roll and after each auction in any basket's maturity range. New issues can join:
  - new 10-year notes for ZN;
  - new 20-year bonds for ZB;
  - new 30-year bonds for UB;
  - aging 30-year bonds move from UB to ZB once under 25 years.

  Check rebuilt baskets against CME's daily TCF files (section 3.2); the first file a bond appears in dates its addition to the basket. Reopenings don't change CUSIP, coupon, maturity or CF. Rerun crossovers whenever the basket changes.
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
| Basket and conversion factors | Rules + CF formula; CME's daily TCF files (public FTP) for validation | Yes | Rebuild from rules + formula; TCF files from December 2023 | Validate rebuilt baskets and CFs against the TCF files |
| Security terms (CUSIP, coupon, maturity, dated date) | TreasuryDirect / FiscalData | Yes | Yes | Include since-matured issues for history |
| Bond prices by CUSIP | TreasuryDirect daily prices | Yes (prior-day close) | Yes, from 30 May 2008 (until about September 2008, CUSIP and prices only); stored from 2016 | Single price, rounded, lagged; off-the-runs noisy; slow to pull, so cache |
| Futures settlements (all six Treasury contracts, all listed months) | CME settlements | Yes | **No** (paid DataMine) | Used only for vol conversion (5.5) and open interest; collection may be manual; respect terms of use |
| Futures option settlements by strike (section 3.1) | CME settlements | Yes | **No** (paid) | Discrete strikes; noisy far from the money; UB thinner than ZN/ZB |
| Deliveries by contract (delivered CUSIPs, if published) | CME delivery reports | Delivery months | **No** | Nice to have: tiebreaker for backtest cycles where the actual CTD is ambiguous from prices (section 8); confirm what CME publishes |
| Constant-maturity yields | Treasury par yield curve (CMT) and daily bill rates, FRED | Yes | Yes, decades | Smoothed curve, not bond-specific |
| GC funding | NY Fed SOFR (also TGCR, BGCR) | Yes | Since 2018 | Overnight only |
| 1-month and 3-month SOFR, 30-day fed funds futures | CME settlements | Yes | **No** | For stepped/stripped repo path |
| CTD-specific repo | **Not available free** | — | — | Not used: GC for all bonds (no fair value, section 1) |

Design rules:
- **Every raw file is stored as downloaded, keyed by as-of date**; the model reads only from that store. Re-running any past date gives the same answer.
- **Collect broadly, model narrowly.** Data that can't be backfilled for free is collected every business day from day one, for every product listed in 3.2, whether or not the model uses it yet (section 3.2).

### 3.1 Options chain required

Daily, for all six Treasury futures contracts, store the full CME option settlement file as downloaded (the model reads ZN, ZB and UB). The model needs these fields from it:

| Field | Use |
|---|---|
| As-of date, option product, expiry date | Keys; expiry drives the term-structure interpolation |
| Underlying futures contract and its settlement price | Moneyness; mapping vol to the right CTD |
| Put/call, strike, settlement premium | Implied vol, skew, digitals |
| Volume and open interest (if on the settlement page) | Liquidity tiebreaker only; the filters below are price-based |

Coverage:
- **Expiries**: every listed expiry (quarterly, serial and all weeklies) on every listed underlying month. The model chooses which to use; storing all of them is cheap, keeps past dates reproducible, and can't be done later.
- **Strikes**: the full chain, both puts and calls. The smile fit and digitals need strikes out to the furthest crossover and the grid window (section 5.6), not just near the money.

How the model uses the chain (section 5.5, 5.7):
- **ATM vol**: out-of-the-money puts and calls nearest the money, inverted with a normal (Bachelier) model on the futures price. Early-exercise value is ignored for out-of-the-money strikes (flag in diagnostics). Check put-call parity at the strike nearest the money.
- **Skew**: implied vol by strike per expiry, re-expressed in bp-of-yield moneyness using the futures DV01 of that expiry's underlying.
- **Smile fit**: normal SABR per expiry on the filtered chain; digitals and the factor distribution come from the fit (5.5.1).
- **Crossover-strike vol** (interim, 5.5.2): the smile read at the futures price equivalent to each crossover.
- **Raw digitals** (diagnostic): put-spread slope between adjacent strikes that straddle each crossover's futures price, compared with the SABR digital.
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
- CME futures settlements: all six Treasury contracts (ZT, ZF, ZN, TN, ZB, UB), all listed months, including calendar-spread settlements if published.
- CME option settlements: options on all six, every listed expiry, every strike, puts and calls.
- CME 1-month SOFR, 3-month SOFR and 30-day fed funds futures settlements (repo path, 5.3).
- TreasuryDirect daily prices: the whole file, every CUSIP, every day. Past dates can currently be looked up back to 30 May 2008, but don't rely on that lasting. History from 2016 is stored once with `ctd backfill --prices-from 2016-01-01`.

**Occasional: not needed daily.**
- CME delivery reports during delivery months, when convenient. Nice to have, not required: the actual CTD is computed from prices (section 8), and a report only settles the ambiguous cycles, and only if it lists delivered CUSIPs.

**Backfillable: pull daily anyway, and backfill once at setup.**
- CME Treasury conversion factor tables (TCF) from CME's public FTP server (`ftp.cmegroup.com/settle/TCF/`): a CSV and an xlsx for every business day, back to December 2023. Validation data for the CF formula and basket rebuilds; consecutive files show the day CME changed a basket. How long CME keeps them is unknown (section 11), hence the daily pull.
- Treasury nominal par yield curve (CMT) and daily bill rates, FRED series. Not Treasury's real yield curve or long-term rate tables: TIPS aren't deliverable and the long-term composites are averages the model doesn't use.
- NY Fed SOFR, TGCR and BGCR.
- FiscalData / TreasuryDirect security terms and auction results, including matured issues.

**Operations**
- `ctd fetch` runs on a schedule every business day after CME final settlements are published. It is idempotent: re-running a date never overwrites a stored file, it only fills what's missing.
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
  - widen to include every crossover with tail probability above `tol`, and the reported scenario range (duration profile, e.g. ±100 to ±150bp; ±1σ);
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
- Root-find the exact z where the argmin changes: crossovers `z_1 < z_2 < …`. Expect ZN: usually one major switch (6.5–7y cluster → 9.5–10y cluster); ZB: a staircase of two or three; UB: one or two, between the shortest and longest 30-year issues.
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
- **Key rate DV01s**: same weighting, with each bond's forward KRDs at T (cash-flow bucketing with triangular weights; curve-based KRDs later if needed).
- **Clusters**: group bonds with similar key rate profiles (same dominant key rate, DV01 within ~5%). Report expected (blended) KRDs and each cluster's KRDs.
- **Scenarios (±1σ)**: shift every forward yield by ±1σ × β_i, keep the remaining vol, and recompute crossovers, probabilities, DV01 and KRDs at the shifted state. Don't just read off the CTD at ±1σ, which jumps and overstates the change. Record whether the smile is treated as sticky strike or sticky moneyness.
- **Duration profile**: blended DV01 and KRDs as a function of the shift (e.g. −100 to +100bp); ±1σ are two points on it.
- Blended KRDs are local; they understate how fast weights change near a crossover (negative convexity).

### 5.10 End-of-month option: out of scope
Affects futures value, not durations or the probability of a major switch materially. Not modelled (section 1).

## 6. Outputs (daily, per contract)

- Basket table: CUSIP, coupon, maturity, CF, price, forward price, forward yield, β, carry, repo used, converted forward price.
- Crossover table: from-bond → to-bond, crossover z (bp), equivalent futures price, distance from forward, probability (base, slope-adjusted, option-implied).
- CTD probabilities per bond and per cluster.
- DV01 and key rate DV01s: blended and per cluster.
- Scenarios: DV01 and KRDs at ±1σ; duration profile across shifts.
- Diagnostics: vol source, strike and expiries used; horizon chosen and why; repo path used; beta window; residual SDs; warnings.
- Optional diagnostic: CTD amount outstanding vs futures open interest (squeeze risk). Not a model input.
- Chart: converted forward prices vs factor shift (the envelope), with the shift distribution overlaid.
- Further outputs under consideration: section 11.

## 7. Historical mode

Goal: time series of CTD probabilities, futures DV01 and KRDs for past contracts, from free data.

- **Baskets**: rebuild per past contract from the issue list (including since-matured issues) and eligibility rules; compute CFs with the formula. Validate against any published past tables. This is the main effort.
- **Prices**: past TreasuryDirect prices by CUSIP, stored from 2016 (available from May 2008). Before about September 2008 the files have no coupon or maturity columns; join on CUSIP to the security terms.
- **Repo**: SOFR (from 2018); GC only.
- **Vol**: realised EWMA vol of the reference CMT yield replaces implied vol.
- **No futures/option history** (paid), so historical mode drops option-implied probabilities. Probabilities are realised-vol based, not risk-neutral.
- Futures DV01/KRDs need no futures price: they are probability-weighted basket DV01s over conversion factors.
- Runtime is trivial; data collection is the constraint.
- Doubles as the backtest (section 8).

## 8. Validation

- **Unit tests**: accrued interest; price/yield round trip to 1e-10 with the single pricing function; CF formula vs CME table for ZN, ZB and UB; delivery calendars, and option expiry dates vs CME's published calendar; a bond crossing the 25-year ZB/UB boundary between contract months; forward price vs carry hand calculation including a coupon between today and delivery; settlement on a coupon date; end-of-month maturities; crossover root-finding on a synthetic two-bond basket with a known answer; term repo compounding; region-weighted DV01 vs finite-difference on a synthetic basket.
- **Independent checks**: a handful of bonds vs QuantLib (test dependency only) or TreasuryDirect published values.
- **Sanity**: on a flat 6% curve all converted prices ≈ 100; below 6% low-duration bonds are CTD, above 6% high-duration.
- **Backtest**: run historical mode over past cycles with large moves (2022–23; the 2026 long-end sell-off). Score probabilities against the actual CTD at delivery (Brier score). The actual CTD is computed from prices: on each delivery day, the bond with the smallest gross basis (cash price − futures × CF). The final futures price is fixed on the last trading day, but the CTD can still change over the last 7 delivery days. Flag a cycle as ambiguous when the two smallest bases are within price noise (TreasuryDirect prices are rounded and struck at a different time from the futures settlement). Exclude ambiguous cycles from scoring, or settle them from a CME delivery report if one was saved and lists CUSIPs. Check that the model shows the switches reported in 2026 (ZB moving along the basket in August and October). Score ZN, ZB and UB separately.
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
- Only ZN, ZB and UB are modelled. Other contracts have collected data but need reference data and validation before use.
- American exercise is ignored when inverting out-of-the-money option prices.
- Historical mode uses realised vol and GC repo only.

## 10. Roadmap

1. **Phase 1, deterministic core** (ZN, ZB): raw data store and fetchers, bond math with tests, CF formula (tested against saved CME tables), term GC repo (flat), forward prices, parallel-shift grid and crossovers (no probabilities). Check against published switch levels. **Before anything else, start the scheduled daily collection in section 3.2 (all six contracts, full options chains, SOFR and fed funds futures, TreasuryDirect prices), with manifests and gap alerts.** Reference data (grades, calendars, option products) for ZN, ZB and UB.
2. **Phase 2, one-factor model**: betas, vol calibration (single expiry, √T), probabilities, region-weighted DV01 and KRDs, ±1σ scenarios and duration profile, daily report. First on ZN and ZB, then UB once they pass the phase-2 checks.
3. **Phase 3, refinements**: total-variance vol interpolation; smile-implied distribution (SABR fit, digitals, envelope mapping, recentring, horizon convolution) with quantile-based grid window; slope adjustment by convolution; digital and ATM-normal diagnostics; horizon decision logic; stepped/stripped repo path. Per-crossover vols (5.5.2) only as a stopgap if the smile fit lags.
4. **Phase 4, history and extensions**: basket rebuild, historical runner with realised vol, backtest scoring; two-/three-factor PCA simulation with idiosyncratic noise; other contracts (ZT, ZF, TN) if wanted. Far down the wishlist: infer slope vol from market futures prices.

## 11. Open questions

- How to collect CME settlements reliably? cmegroup.com refuses scripted connections (bot protection), and CME's public FTP server carries only the TCF tables of what's needed. Until a paid feed is chosen, futures settlement JSONs and the options bulletin are downloaded in a browser with the `ctd bookmarklet` (one click a day). Which feed, if any (DataMine, Databento, Barchart OnDemand)?
- How long does CME keep TCF files on its FTP server (December 2023 onwards as of October 2026)?
- What exactly do CME's delivery reports publish (delivered CUSIPs and amounts, or only totals), and how many past days do their pages show? Only matters for settling ambiguous backtest cycles (section 8). (Futures and option settlements: 5 business days, confirmed.)
- Which beta window and decay best predicts realised basket moves (settle by backtest)?
- Realised-vol window for historical mode, and how it compares with implied vol once live snapshots accumulate?
- The Treasury par curve only has 1, 2, 3, 5, 7, 10, 20 and 30-year points. Should the 1-year-step betas (5.4) come from interpolating the curve, or from a fitted curve on bond prices? This matters most for ZB (only 20y and 30y in its range) and UB (only 30y in its range, so its betas are extrapolated).
- How often are UB options too thin to use, and is ZB vol mapped through betas a good enough substitute?
- Which weekly expiries are listed today for ZN, ZB and UB options (Monday to Friday weeklies vary by product)? Confirm before building the expiry calendar.

### Additional outputs worth considering (undecided)

**Distance to switch**
- Shift needed for the next switch, in basis points and in standard deviations. A z-score is the most readable single headline.
- Time series of both, with alerts when the distance drops below 1σ.

**Market impact** (probably the most distinctive output)
- Aggregate duration supply: open interest × futures DV01, in dollars per basis point, by key rate bucket, across ZN, TN, ZB and UB. That's how much duration the futures market holds and where on the curve it sits.
- Rebalancing need on a switch: open interest × change in DV01 at the switch, the same quantity as the Barclays estimate of $25 million per basis point. Express it as a 10-year or 30-year cash equivalent.
- By holder type: CFTC's weekly Traders in Financial Futures report (free) splits open interest between asset managers (mostly long futures as duration substitutes) and leveraged funds (mostly short, against basis trades). That tells you who has to rebalance, and in which direction.
- CME publishes daily volume and open interest for free.

**Basis-trade relevance**
- For basis traders, a switch means their long bond no longer matches what the futures track. Show the duration mismatch between the current CTD and the next one, and the hedge-ratio change per $100 million of the current CTD.

**Convexity**
- Futures gamma: the change in DV01 per basis point of yield move, which peaks near a crossover. Even a modest switch probability can produce outsized hedging flows when gamma is high.

**Contract roll**
- The December and March contracts can have different CTDs. Around the late-November roll, open interest moves to March and the market's futures duration can change without any yield move. Run both contracts and show the duration change at the roll.

**Cross-contract view**
- ZN, TN, ZB and UB together, since the stresses so far have been concentrated in the long end. A single key-rate chart across contracts shows where futures duration is concentrated.

**Attribution of daily changes**
- Split each day's change in futures duration into yield moves, time passing, vol changes and basket changes (new issues, the roll). This makes the time series explainable, which matters if others will read it.

**Calendar of known events**
- Auctions that add issues to the basket, the roll period, first notice day and delivery dates, overlaid on the time series.

**Uncertainty bands**
- Report probabilities under the sensitivity cases (vol ±10%, betas ±0.05), so readers can see how firm a figure like "40% chance of a switch" is.
