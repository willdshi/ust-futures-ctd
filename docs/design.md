# CTD Model: Design

End-of-day model of cheapest-to-deliver (CTD) probabilities, futures fair value and key rate durations for CBOT Treasury futures, built from free public data.

## 1. Goals and non-goals

### Goals
- For a given contract (start with **ZB** and **ZN**), estimate each deliverable bond's probability of being CTD at delivery.
- Locate the **crossover levels** (factor shifts at which the CTD changes hands) and group bonds into clusters with similar key rate profiles.
- Produce futures **DV01 and key rate DV01s**, both probability-weighted and per cluster.
- Produce a model futures fair value and compare it with the market settlement price.
- Run daily from end-of-day data, reproducibly, with every input snapshot stored.

### Non-goals (v1)
- Intraday or live pricing.
- Pricing the wildcard option (treated as part of the model-to-market residual).
- Full multi-factor term-structure model. A second factor is a later extension (section 9).
- ZT, TN and the 2-, 3- and 5-year contracts. Their baskets are too narrow for switching to matter; the code should support them, but they're not a focus.

## 2. Contract facts the code must encode

| Contract | Deliverable remaining maturity | Notes |
|---|---|---|
| ZN | 6.5 to 10 years (from first day of delivery month) | Original-issue limits apply; check CME spec |
| ZB | 15 to under 25 years | 25+ years goes to UB |
| UB | 25 years and over | Later |

- Conversion factor: price per $1 par at a 6% yield, per CME's formula. Use **CME's published table** for each contract month and implement the formula only as a cross-check.
- Delivery calendar per contract month: first delivery day, last trading day (7 business days before month-end), last delivery day. Store per contract rather than computing ad hoc.
- Invoice price = futures settlement × CF + accrued interest at delivery date.

## 3. Data sources (all free, end of day)

| Data | Source | Frequency | Known weaknesses |
|---|---|---|---|
| Basket and conversion factors | CME conversion factor tables | Per contract month | Must re-pull after reopenings and new issues |
| Security terms (CUSIP, coupon, maturity, dated date, amount outstanding) | TreasuryDirect / FiscalData | As needed | — |
| Bond prices by CUSIP | TreasuryDirect daily Treasury securities prices | Daily, prior-day close | Single price, rounded, lagged one day; off-the-runs noisy |
| Futures settlements | CME settlements | Daily | Collection may be manual; respect terms of use |
| Futures option settlements by strike (puts and calls) | CME settlements | Daily | Discrete strikes; noisy far from the money |
| Constant-maturity yield history (betas) | Treasury par yield curve (CMT), FRED | Daily | Smoothed curve, not bond-specific |
| GC funding | NY Fed SOFR, TGCR, BGCR; OFR repo data | Daily | Overnight only; build a term rate to the horizon |
| CTD-specific repo | **Not available free** | — | Backed out by calibration (section 5.8) |

Design rule: **every raw file is stored as downloaded, keyed by as-of date**, and the model reads only from that store. Re-running any past date must give the same answer.

## 4. Architecture

```
ctd/
  data/            # fetchers + raw store (one module per source)
  reference/       # contract specs, delivery calendars, CF tables
  bonds/           # cash flows, accrued, price<->yield, forward price, KRDs
  curve/           # CMT history, beta estimation, residual stats
  vol/             # option implied vols, put-slope digitals, horizon scaling
  model/           # factor grid, envelope, crossovers, probabilities
  risk/            # DV01, key rate DV01s, cluster profiles
  report/          # daily output tables + charts
  cli.py           # `ctd run --contract ZBZ6 --asof 2026-10-16`
tests/
docs/design.md
```

- Python, numpy/scipy/pandas. Day counts and calendars either hand-written and tested, or from a library such as QuantLib; decide in phase 1.
- Pure functions in `bonds/`, `model/`, `risk/`; I/O only in `data/` and `report/`.
- Dates and conventions explicit everywhere: settlement date, delivery date, actual/actual accrual, semiannual compounding.

## 5. Model

### 5.1 Horizon
- Compute each likely CTD's daily carry: coupon accrual minus repo on dirty price.
- Positive carry: horizon = last delivery day. Negative: first delivery day.
- **One horizon for the whole basket**, not one per bond (the short commits to a date before knowing which bond wins).
- If carry is near zero, or slightly negative with a crossover near: run both dates and take whichever gives the lower expected converted price for the short.

### 5.2 Forward prices
- For each bond: forward clean price at horizon T from today's dirty price, term repo to T, and coupons paid before T.
- Repo: term GC for all bonds by default, with an override for CTD/near-CTD rates.
- Convert to forward yield `y_i^fwd`. Everything is centred on these.

### 5.3 Factor and betas
- Factor `x` = a constant-maturity yield near the current CTD: **20-year for ZB, 7-year for ZN**.
- For each CMT point across the basket range (ZN ~6–11y, ZB ~14–26y, 1-year steps), regress yield changes on the reference: `Δy(τ) = β(τ)·Δx + ε(τ)`.
  - 2–3 day or weekly changes; 6–12 month window or exponential weights (half-life ~3 months).
  - Shrink betas slightly toward 1.
  - Also estimate on **sell-off days only**; use those if materially different.
- Interpolate β at each bond's remaining maturity at T.
- Store residual SDs `σ_ε(τ)` and the residual SD of the spread between candidate bonds; used in 5.7 and as a diagnostic.

### 5.4 Volatility
1. Futures option implied vol (at-the-money to start).
2. Price vol → normal yield vol of CTD: `σ_y ≈ σ_price × F / (100 × D_F)`.
3. To factor units: `σ_x = σ_y / β_CTD`.
4. Scale from option expiry to horizon: `S = σ_x √T_horizon` (square-root-of-time; flag as an approximation).
5. Iterate: after crossovers are found, re-read vol at the **crossover strike** and repeat 2–4 until stable (1–2 passes).

### 5.5 Pricing grid
For z from −4S to +4S in 1bp steps:
```
y_i(z) = y_i^fwd + c_i + β_i · z
P_i(z) = clean price at T from y_i(z)
C_i(z) = P_i(z) / CF_i
```
`c_i` is solved per bond so that `E[P_i(z)] = forward price` under z ~ N(0, S²) (convexity adjustment, ~1–2bp for ZB).

### 5.6 Envelope and crossovers
- `F_model(z) = min_i C_i(z)`; record the argmin.
- Root-find the exact z where the argmin changes: crossovers `z_1 < z_2 < …`.
- Expect **ZN: usually one major switch** (6.5–7y cluster → 9.5–10y cluster). **ZB: a staircase of two or three.**

### 5.7 Probabilities
- Bond/region probability: `π = Φ(z_{k+1}/S_k) − Φ(z_k/S_k)`.
- Base case `S_k = S`. Slope-adjusted case for each crossover between bonds S and L:
  `S_eff = √(S² + (m · σ_ε,spread)²)`, with `m = D_L / (D_L − D_S)` (beta-adjusted).
  Use `S_eff` **for probabilities only**, not for futures price/DV01.
- Alternative: market-implied probability at each crossover from the put-strike slope of option settlements (digital), divided by the discount factor; then horizon-adjusted. Report alongside the model value.

### 5.8 Fair value and calibration
- Model futures price = `E[F_model(z)]` (expected lower envelope).
- Compare with market settlement. Residual includes: CTD repo specialness, end-of-month option, wildcard, price noise.
- Calibration knob: solve for the **CTD's repo rate** that makes model = market. Report it as "implied CTD repo"; treat it as a fitted parameter, not an observation. A large or unstable value signals bad inputs.

### 5.9 Risk
- Futures DV01: bump z (and separately all yields in parallel) and difference `E[F_model]`.
- Key rate DV01s: `KRD01_F,k = Σ_i π_i · KRD01_i,k / CF_i`, using **forward** key rate durations at T.
- Clusters: group bonds whose key rate profiles are similar (same dominant key rate, DV01 within ~5%). Report:
  - expected (probability-weighted) KRDs, for hedging today;
  - each cluster's KRDs, for jump risk if a switch happens.
- Note: blended KRDs are local; they understate how fast weights change near a crossover (negative convexity).

### 5.10 End-of-month option (phase 3)
- After the last trading day, invoice price is fixed and the short has ~5 business days to choose the bond.
- Price as a short-dated switch option with the same envelope machinery over that window. Add to fair value.

## 6. Outputs (daily, per contract)

- Basket table: CUSIP, coupon, maturity, CF, price, forward price, forward yield, β, carry, repo used, converted forward price, net basis, implied repo.
- Crossover table: from-bond → to-bond, crossover z (bp), equivalent futures price, distance from forward, probability (base, slope-adjusted, option-implied).
- CTD probabilities per bond and per cluster.
- Fair value vs market, implied CTD repo.
- DV01 and key rate DV01s: blended and per cluster.
- Diagnostics: vol used and strike, horizon chosen and why, beta window, residual SDs, warnings.
- Chart: converted forward prices vs factor shift (the envelope), with the shift distribution overlaid.

## 7. Validation

- **Unit tests**: accrued interest, price/yield round trips, CF formula vs CME table, forward price vs carry hand calculation, crossover root-finding on a synthetic two-bond basket with a known answer.
- **Sanity**: on a flat 6% curve all converted prices ≈ 100 and probabilities are spread; below 6% low-duration bonds are CTD, above 6% high-duration.
- **Backtest**: run on past contract cycles with large moves (2022–23; the 2026 long-end sell-off). Score probabilities against the actual CTD at delivery (Brier score). Compare base vs slope-adjusted vs option-implied.
- **Sensitivity**: β ± 0.05, horizon first vs last delivery, vol ± 10%, crossover-strike vs ATM vol, GC vs a 50bp special repo on the CTD. Record how much probabilities move.
- **Cross-check**: dealer/Bloomberg CTD scenarios when available (e.g. published switch levels for ZB).

## 8. Known limitations

- One factor: independent slope moves are only approximated (5.7); probabilities near closely spaced crossovers are unreliable.
- Free bond prices are lagged and rounded; a few ticks of noise moves crossovers.
- No free CTD-specific repo; implied repo absorbs all other errors.
- Square-root-of-time horizon scaling loses term structure of vol and skew.
- Option-implied probabilities are risk-neutral (include sell-off risk premium), measured at option expiry, and on futures prices rather than bonds.

## 9. Roadmap

1. **Phase 1, deterministic core**: data store, bond math, CF tables, forward prices, parallel-shift scenario grid and crossovers (no probabilities). Check against published switch levels.
2. **Phase 2, one-factor model**: betas, vol calibration, probabilities, fair value, implied CTD repo, KRDs, daily report.
3. **Phase 3, refinements**: crossover-strike vol iteration, slope-adjusted widths, option-implied digitals, horizon decision logic, end-of-month option.
4. **Phase 4, extensions**: two-/three-factor PCA simulation with idiosyncratic noise; UB contract; backtest dashboard.

## 10. Open questions

- Hand-rolled bond math vs QuantLib?
- How to collect CME settlements reliably (manual download vs vendor) within their terms of use?
- Term GC construction: SOFR compounded forward vs term SOFR vs TGCR average?
- Which beta window and decay best predicts realised basket moves (to be settled by backtest)?
- re-pull the basket and conversion factors from CME on each contract-month roll and after each auction in the basket’s maturity range