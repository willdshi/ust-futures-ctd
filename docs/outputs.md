# Treasury Futures CTD Model — Output Specification

## Positioning

A **duration-drift monitor for Treasury futures users**: how stable is the duration you hold through futures, what would change it, and when.

- **Audience:** a broad rates audience and asset managers who use futures as duration substitutes or overlays. Not basis traders, who have better tools.
- **Core question:** how much does futures DV01 and its key-rate profile change as yields move, and how close is the next change?
- **Market-impact framing:** a CTD switch *transfers* duration between longs and shorts; it does not create it (unlike mortgage extension). Directional impact exists only to the extent rehedging is asymmetric, and the sign of that asymmetry is ambiguous. Market impact is therefore context, not the headline.

## Scope

- **In:** CTD probabilities, probability-weighted futures DV01 and KRDs, scenario profiles, time series.
- **Out:** futures fair value, curve fitting, idiosyncratic rich/cheap modelling, issue-specific repo, outputs aimed at basis traders.
- **Contracts:** ZN and ZB first (prone to switching). TN and UB added mainly as stable-duration comparisons.

## Conventions

| Item | Convention |
|---|---|
| DV01 units | $/bp per $100mm notional by default; per contract also available |
| Futures risk | Probability-weighted: Σ pᵢ × DV01ᵢ / CFᵢ (same for KRDs) |
| Comparison measure | CTD-label DV01 (what many vendor and internal systems report) |
| Factor shifts | Shown in both bp and percentiles of the move-to-delivery distribution (σ√T) |
| Scenario recompute | Full model recompute at each shifted state, with the same remaining vol. Never read off the CTD at the shifted yield. |
| Key-rate grid | 2, 5, 7, 10, 15, 20, 25, 30. Long-end resolution is needed so a ZB switch (about 15y to about 25y) is visible. Tent bumps to the Treasury par curve (linear between published tenors), scaled to each bond's DV01. Fixed ([decisions.md](decisions.md)). |
| Negative KRDs (published note) | Key-rate exposures are measured against the Treasury par curve: each bucket is how much of a par bond at that tenor would hedge the position. For low-coupon bonds, the hedge is more than 100% at the bond's own maturity and slightly short at earlier tenors, so short-tenor buckets can be negative, and effective maturity can exceed the bond's maturity. |
| Delivery timing | Last delivery day if carry is positive, first if negative (documented rule) |
| Parameter estimation | Daily EWMA or rolling vol and betas, to avoid artificial steps |

---

## Tier 1 — Core outputs

### Chart 1: Duration profile with key-rate shape

The headline chart. It separates **level** (how much DV01) from **shape** (where on the curve).

- **Top panel:** total probability-weighted DV01 against factor shift (about −100 to +100bp, dual-labelled in percentiles). Shows the switch staircase smoothed by vol. ±1σ and ±2σ marked as points on the curve.
- **Bottom panel (same x-axis):** stacked share or heatmap of each key-rate bucket's share of total DV01. A switch appears as a band bending toward longer buckets, for example ZB risk sliding from 20y into 30y.
- **Overlay:** faint CTD-label DV01 step line on the top panel.
- One chart per contract, as small multiples.

### Chart 2: Diverging key-rate change bars

The actionable drill-down for asset managers.

- Change in KRD versus today, per bucket, in $/bp per $100mm, at ±1σ and ±2σ (or the 5th, 25th, 75th and 95th percentiles).
- Positive and negative bars from zero. Example reading: "at +1σ your ZB position loses $X/bp at 20y and gains $Y/bp at 30y."
- Faint marker for the CTD-label change, so readers see when vendor numbers would jump and the model's wouldn't.
- Small multiples per contract.

### Chart 3: DV01 time series, with effective maturity as companion

**Primary panel: DV01 per $100mm over time, one line per contract.**
- Band: ±1σ scenario values.
- **Constant-CTD DV01** line alongside. The gap between it and the probability-weighted line is the part of the duration change caused by the basket, in units the audience already uses.
- **CTD-label DV01** line, which jumps at label flips.

Why DV01 is primary: it is the number people act on. But duration on its own mixes in changes unrelated to switches:
- Yield level: with the same CTD, duration falls as yields rise (ordinary convexity).
- Time: the CTD rolls down, so duration shortens steadily.
- Price and coupon effects on the CTD's duration.

**Companion panel: DV01-weighted effective maturity**, i.e. Σₖ KRDₖ × Tₖ / Σₖ KRDₖ. Default view for ZB and for cross-contract comparison.
- Answers "where on the curve" rather than "how much". Two exposures with the same DV01 can sit at 18y or 27y and hedge or track very differently.
- It is a cleaner switch signal than duration because it barely moves for the non-switch reasons above.
- Needs one sentence of explanation for less sophisticated readers, and depends on the key-rate grid and the par-curve tent bumps.

**How the effective-maturity line behaves:**
- Baseline: a steady downward drift of about one day per day as each bond's key-rate profile slides shorter. Tent bumps keep it smooth as bonds cross nodes.
- It rises only when DV01 shifts toward longer tenors, which happens through:
  1. **Probability moving to a longer bond** (the switch effect; below 6%, as yields rise).
  2. **Basket or contract changes:** a longer bond entering with meaningful probability, or the roll moving to a contract whose likely CTD is longer.
  3. **Yields falling with the CTD unchanged:** a bond's own key-rate weights tilt longer as distant cash flows gain relative present value. Rising yields do the reverse.
- In a selloff toward a crossover, effects 1 and 3 oppose each other. Near the crossover the switch effect should dominate; far from it, effect 3 is a small drift that tracks yields.
- For a pure basket signal, hold each bond's key-rate shape fixed at a reference yield, or plot a constant-CTD effective maturity and read the gap.

**Expected jumps:** the probability-weighted series is continuous in yields while there is time to delivery, so a switch shows as a smooth bend. Expect discrete moves only from:
1. Basket changes: a new issue entering or an old one dropping out.
2. The contract roll (December to March): a discrete step by construction, and one to highlight.
3. Near expiry: as σ√T shrinks, probabilities collapse toward 0 or 1, and daily yield moves near a crossover can look like jumps.
4. Parameter re-estimation, if betas or vol update in steps. Avoid with daily EWMA or rolling estimates.
5. The CTD-label comparison series, which is a staircase by design.

**Event flags:** tag each date with basket change, roll and re-estimation events so any step can be attributed immediately. This is the first version of attribution.

### Other Tier 1 outputs

- **Distance to switch:** shift needed for the next switch, in bp and σ (z-score), as a time series per contract, flagged when it falls below 1σ.
- **CTD probabilities:** the engine of the model, published as a supporting time series rather than the headline.
- **Probability-weighted versus CTD-label DV01:** the most distinctive output for asset managers, showing when their vendor numbers will jump.

---

## Tier 2 — Credibility and timeliness

- **Contract roll:** run December and March together and show the DV01 and KRD change at the roll with no yield move. Late-November roll is a natural first publication.
- **Cross-contract comparison:** which contract gives the most stable exposure at today's yields. TN and UB are typically stable; ZN and ZB are prone to switching.
- **Uncertainty bands:** rerun at vol ±10% and betas ±0.05.
- **Calibration backtest:** forecast CTD probabilities against the realised CTD at delivery (Brier score, reliability plot). This decides whether readers trust "30% chance of a switch."
- **Calendar overlay:** auctions adding issues, roll period, first notice day, delivery dates.
- **Daily attribution:** split DV01 changes into yields, time, vol/betas and basket. Sequential, with a fixed documented order (basket, then time, then vol/betas, then yields). Build after regular publication starts; event flags cover it until then.
- **Portfolio mix (later):** charts 1 and 2 for a user-entered overlay mix, for example 60% ZN and 40% UB.

## Fragility dashboard (context row, not a composite score)

1. **Asset-manager duration held via futures:** TFF asset-manager long × probability-weighted DV01 per contract, in $/bp, with net alongside. Trend over time shows buy-side reliance on synthetic duration.
2. **Deliverable float of the next CTD:** outstanding − SOMA − stripped, against front-month OI and asset-manager long OI. An upper bound on supply and a squeeze or specialness indicator.
3. **Rebalancing timing:** flag when a switch zone coincides with month-end or the roll, when asset-manager rebalancing would bunch up. An execution-cost issue, not a level move.
4. **"Not a convexity event" explainer:** transfer versus creation, hedged sides largely net, residual asymmetry of ambiguous sign.

## Dropped or reframed from the original plan

| Original idea | Status |
|---|---|
| CTD probabilities as the headline | Reframed: engine output; duration is the headline |
| ±1σ durations/KRDs | Folded into chart 1 (points on the profile) and chart 2 (diverging bars) |
| Impact on basis trade; hedge-ratio change per $100mm of CTD | Dropped: wrong audience |
| Impact on curve level; OI × ΔDV01 as selling pressure | Reframed as gross duration transfer by key rate; net direction only as a symmetric asymmetry scenario |
| Futures gamma | Kept implicitly: the slope of the chart 1 profile; flow concentration near crossovers |
| Effective maturity as a standalone core chart | Demoted to companion panel of chart 3 (default for ZB and cross-contract) |

## Data dependencies by output

| Output | Data |
|---|---|
| Charts 1–3, distance to switch, probabilities | Security reference (Fiscal Data auctions), TreasuryDirect daily prices, conversion factors (computed, checked against CME), SOFR, Treasury par curve, CME basket rules and calendar |
| Roll | Same, plus CME Pace of the Roll for month-level OI |
| Calibration | Realised CTD computed from own prices at delivery |
| Asset-manager duration via futures | CFTC TFF futures-only (`gpe5-46if`) |
| Deliverable float | MSPD outstanding and STRIPS, NY Fed SOMA holdings, buyback results, auction and reopening results |

**Optional: CME delivery reports.** Not part of the core build. CME posts only the current month's Treasury delivery reports (daily issues and stops, month to date), and cmegroup.com blocks scripts, so there is no history to collect. A report saved by hand during a delivery month can serve as an optional validation input: a check on delivery timing, or on the realised CTD for an ambiguous cycle if it identifies the delivered issue.

## First milestone

Tier 1 for ZN and ZB, plus the December/March roll comparison, ready before the late-November roll.
