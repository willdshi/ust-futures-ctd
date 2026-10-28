# Treasury Futures CTD Model — Output Specification

What gets published and how it looks. `[NI]` marks anything specified here that isn't implemented yet; the matching work is in [roadmap.md](roadmap.md). How each number is computed is in [design.md](design.md).

## Positioning

A **duration-drift monitor for Treasury futures users**: how stable is the duration you hold through futures, what would change it, and when.

- **Audience:** a broad rates audience and asset managers who use futures as duration substitutes or overlays. Not basis traders, who have better tools.
- **Core question:** how much does futures DV01 and its key-rate profile change as yields move, and how close is the next change?
- **Market-impact framing:** a CTD switch *transfers* duration between longs and shorts; it does not create it (unlike mortgage extension). Directional impact exists only to the extent rehedging is asymmetric, and the sign of that asymmetry is ambiguous. Market impact is therefore context, not the headline.
- **The motivating example:** on 2026-10-14 ZBZ6's CTD flipped from the 2½% Feb-45 to the 4⅝% Nov-44. Its CTD-based DV01, the number vendor systems report, dropped from $138.5k to $122.0k per $100mm; the probability-weighted DV01 moved from $140.9k to $139.9k. Nothing about the position's real exposure changed by $16k overnight.

## Scope

- **In:** CTD probabilities, probability-weighted futures DV01 and KRDs, scenario profiles, time series.
- **Out:** futures fair value, curve fitting, idiosyncratic rich/cheap modelling, issue-specific repo, outputs aimed at basis traders.
- **Contracts:** ZN, TN, ZB and UB, all four with the same outputs. ZN and ZB switch most often; TN and UB usually less. ZT and ZF are not modelled.

## Conventions

| Item | Convention |
|---|---|
| DV01 units | $/bp per $100mm notional by default; per contract also available |
| Futures risk | Probability-weighted: Σ pᵢ × DV01ᵢ / CFᵢ (same for KRDs) |
| Comparison measure | CTD-based DV01 (what many vendor and internal systems report) |
| Futures duration | Shown in the summary next to each DV01, probability-weighted and CTD-based: DV01 per 100 face over the market futures settlement, in years, for today only ([design.md](design.md) §5.9). DV01 stays the headline: hedges are sized in it and the key rates add up to it; duration compares contracts at a glance (on 2026-10-22: ZNZ6 5.8y, ZBZ6 12.8y). No duration axis on the charts: along the shift the futures price changes, so DV01 and duration aren't one rescaling of each other |
| Factor shifts | Shown in both bp and percentiles of the move-to-delivery distribution (σ√T) |
| Scenario recompute | Full model recompute at each shifted state, with the same remaining vol. Never read off the CTD at the shifted yield. |
| Key-rate grid | 2, 5, 7, 10, 15, 20, 25, 30, fixed; tent bumps to the Treasury par curve ([design.md](design.md) §5.9) |
| Negative KRDs (published note) | Key-rate exposures are measured against the Treasury par curve: each bucket is how much of a par bond at that tenor would hedge the position. For low-coupon bonds, the hedge is more than 100% at the bond's own maturity and slightly short at earlier tenors, so short-tenor buckets can be negative, and effective maturity can exceed the bond's maturity. |
| Delivery timing | Published as the *implied delivery date*, a column of the summary table: the last delivery day if the basket's probability-weighted carry is positive, the first if negative ([design.md](design.md) §5.2). Footnote: the date is uncertain where bonds of opposite carry are close (ZN) |
| P(RCaD) | Probability that today's CTD remains CTD at the implied delivery date. Shown from both models: the ATM normal factor (to implied delivery, as in the charts) and the option digitals (at option expiry, the latest date they can measure) |
| Contract in the series | The contract whose quarterly options are the nearest not yet expired: roll at option expiry (December to March on 2026-11-20); in the week before, both run ([design.md](design.md) §7) |
| Option-implied, not traded (published caveat) | Every option-derived number (the digitals, the ATM vol and so the width) comes from CME settlement prices, which CME sets from its implied-vol skew for the expiry whether or not a strike traded. Call them option-implied, never market-implied. Each digital and the ATM vol show which of their strikes traded that day ("strikes traded": all, none, or which); with none, or beyond about 1.5σ, a digital is indicative. Options for 2026-10-16 to 10-23 come from the Section 42 bulletin, which leaves out strikes with no open interest ([design.md](design.md) §3.1; [data.md](data.md) §1). |
| Probabilities in charts | Normal factor with ATM vol and β = 1, so they can be recomputed at shifted states; the option-implied (light model) probabilities are shown alongside as a cross-check. No skew until the smile-implied distribution `[NI]` ([design.md](design.md) §5.9) |
| Parameter estimation | Daily EWMA or rolling vol and betas, to avoid artificial steps. Betas `[NI]` (β = 1 until then) |

### How well the option numbers are anchored

Sizes the "option-implied, not traded" caveat. Over 2026-09-01 to 10-23 (37 dates per contract), digitals by whether the strikes behind them traded that day:

| | digitals | all strikes traded | some | none | none and within 1σ | dates where neither ATM strike traded |
|---|---|---|---|---|---|---|
| ZBZ6 | 298 | 275 | 13 | 10 | 0 | 0 |
| ZNZ6 | 120 | 86 | 28 | 6 | 0 | 0 |
| UBZ6 | 91 | 3 | 38 | 50 | 25 | 20 |
| TNZ6 | 37 | 0 | 1 | 36 | 0 | 22 |

ZB's and ZN's digitals rest on strikes that traded (ZB on 2026-09-15: half its 68 out-of-the-money DEC26 strikes traded, every one near the money). UB's and TN's mostly don't, including half of UB's switches within 1σ, and on over half the dates neither strike behind their ATM vol traded either: there the width, and so the headline DV01, rests on CME's skew rather than that day's trades. Recompute from the saved results (each digital records its traded strikes) when publishing a longer series.

---

## Tier 1 — Core outputs

### Chart 1: Duration profile with key-rate shape

The headline chart. It separates **level** (how much DV01) from **shape** (where on the curve).

- **Top panel:** total probability-weighted DV01 against factor shift (about −100 to +100bp, wider in steps of 10bp when ±2σ falls beyond). Shows the switch staircase smoothed by vol, with the vol ±10% band. ±1σ and ±2σ marked as points on the curve, with guides through both panels.
- **Axes:**
  - The main x-axis is the shift in bp, labelled as what moves: "parallel shift in basket forward yields (bp)" while β = 1, and the reference yield ("20y yield change (bp)") once betas arrive `[NI]`.
  - Percentiles of the move-to-horizon distribution go on the secondary axis. They are the same in yield and futures-price space (the mapping is monotone), so only the distribution matters.
  - **No futures-price axis.** The futures price is the envelope, monotone in the shift but with a slope that changes at each switch, so it would squeeze and stretch the regions the chart is meant to show. Switch points appear as futures prices in the crossover table instead.
- **Bottom panel (same x-axis):** heatmap of each key-rate bucket's share of total DV01, one row per bucket.
  - End buckets under 0.5% of the DV01 at every shift are left out.
  - Positive shares in a blue ramp up from a neutral gray, negative shares in gray: full gray at −50%, full blue at +100% (shares run from about −25% to about 140%). One scale for every contract.
  - A switch appears as the dark cell moving between rows, for example ZB risk sliding from 15y through 20y into 25y as yields rise.
  - **Why a heatmap, not stacked bands:** eight ordered buckets need eight steps a reader can tell apart, and one hue holds about five. As stacked bands, 7y, 10y and 15y ran together, and negative shares stacked below zero couldn't be read. As a heatmap the row names the bucket, so color only carries the share.
  - **Rejected: blue ↔ red.** Chart 2 already uses it for rally ↔ sell-off.
- **Overlay:** faint CTD-based DV01 step line on the top panel.
- **Interactive page:** hovering names the CTD at the shift and the likeliest CTDs at delivery from there, and the heatmap gives each bucket's share. Selecting a shift (hover, click to pin, or a slider for touch screens) drives chart 2.
- One chart per contract, as small multiples.

### Chart 2: Diverging key-rate change bars

The actionable drill-down for asset managers.

- Change in KRD versus today, per bucket, in $/bp per $100mm, at ±1σ and ±2σ (blue rally, red sell-off). On the interactive page, also at any shift selected on chart 1.
- Positive and negative bars from zero. Example reading: "at +1σ your ZB position loses $X/bp at 20y and gains $Y/bp at 30y."
- Faint marker for the CTD-based change, so readers see when vendor numbers would jump and the model's wouldn't.
- End buckets under 0.5% of today's DV01 in every state are left out (ZN's 15y to 30y).
- Small multiples per contract.

### Chart 3: DV01 time series, with effective maturity as companion

**Primary panel: DV01 per $100mm over time,** one figure per contract, on its own axes.
- **±1σ scenario values.** The PNG draws them as two lines in one color, ▲ and ▽, one per state. The interactive page draws a band.
  - Distinct markers for the band's two edges `[NI]` (roadmap R.2): each edge should be marked by state (+1σ or −1σ), as the PNG's lines are, not by which is higher. Near a crossover both can sit above today's DV01 (ZNZ6, October 2026: the profile is U-shaped, convexity raising DV01 in a rally and the switch to the 2034 notes raising it in a sell-off), so "top" and "bottom" don't say which way yields moved.
- **CTD-based DV01** line, which jumps when the CTD changes. A CTD change is an open circle on it; on the interactive page the hover names the new CTD, its probability of remaining CTD and the nearest switch in σ. Circles rather than names on the plot, since a contract can have a dozen switches.
- **Constant-CTD DV01** line. The gap between it and the probability-weighted line is the part of the duration change caused by the basket, in units the audience already uses.
- Guides mark basket changes. Dragging across dates zooms, with both y-axes refitted to the window.

Why DV01 is primary: it is the number people act on. But duration on its own mixes in changes unrelated to switches:
- Yield level: with the same CTD, duration falls as yields rise (ordinary convexity).
- Time: the CTD rolls down, so duration shortens steadily.
- Price and coupon effects on the CTD's duration.

**Companion panel: DV01-weighted effective maturity**, i.e. Σₖ KRDₖ × Tₖ / Σₖ KRDₖ. Default view for ZB and for cross-contract comparison.
- Answers "where on the curve" rather than "how much". Two exposures with the same DV01 can sit at 18y or 27y and hedge or track very differently.
- It is a cleaner switch signal than duration because it moves much less for the non-switch reasons above: yield level moves it about 0.5 to 1y per 100bp with the same CTD (effect 3 below), against several years for a ZB switch.
- Needs one sentence of explanation for less sophisticated readers, and depends on the key-rate grid and the par-curve tent bumps.
- Effective maturity across contracts on one axis `[NI]`: only today's values sit side by side, in the summary table.

**How the effective-maturity line behaves:**
- Baseline: a steady downward drift of about one day per day as each bond's key-rate profile slides shorter. Tent bumps keep it smooth as bonds cross nodes.
- It rises only when DV01 shifts toward longer tenors, which happens through:
  1. **Probability moving to a longer bond** (the switch effect; below 6%, as yields rise).
  2. **Basket or contract changes:** a longer bond entering with meaningful probability, or the roll moving to a contract whose likely CTD is longer.
  3. **Yields rising with the CTD unchanged:** measured against the par curve, a bond below par sits beyond its maturity and one above par short of it (a par bond sits exactly on its maturity at any yield level). As yields rise, every fixed-coupon bond moves further below par, so its effective maturity lengthens; falling yields shorten it. About 1y per 100bp for a 2% 2050, 0.5y for a 4¾% 2045 (2026-10-21, horizon 31 December). A cash-flow-weighted maturity moves the other way, which is why this is easy to get backwards.
- In a selloff toward a crossover, effects 1 and 3 push the same way, so a rising line is not by itself evidence of a switch. Near the crossover the switch effect dominates; far from it, effect 3 is a small drift that tracks yields. In a rally both shorten.
- For a pure basket signal, hold each bond's key-rate shape fixed at a reference yield `[NI]` (needs model re-runs), or plot a constant-CTD effective maturity `[NI]` and read the gap.

**What can cause a step in the series:**
1. Basket changes: a new issue entering or an old one dropping out.
2. The contract roll (December to March): a discrete step by construction, and one to highlight. `[NI]`: the series is one contract, not the product series that rolls at option expiry.
3. Near expiry: as σ√T shrinks, probabilities collapse toward 0 or 1, and daily yield moves near a crossover can look like jumps.
4. Parameter re-estimation, if betas or vol update in steps. Avoid with daily EWMA or rolling estimates.
5. The CTD-based comparison series, which is a staircase by design.

**Event flags:** tag each date with basket change, roll and re-estimation events so any step can be attributed immediately. This is the first version of attribution. Basket changes and CTD changes are marked; roll and re-estimation flags `[NI]`.

### Other Tier 1 outputs

- **CTD probabilities over time** `[NI]` as a series. They exist for the as-of date (summary and probability tables), and the series rows already carry `p_ctd`. Candidate uses:
  - attributing a bend in chart 3 to the bond gaining probability;
  - showing the expected collapse toward 0 or 1 near expiry;
  - the normal-model and option-digital probabilities side by side as a check on the model before the calibration backtest.

  How to draw it is open.
- **Distance to switch:** shift needed for the next switch, in bp and σ, for today in the summary and switch tables (flagged below 1σ). As a time series `[NI]`, lower priority:
  - For the current day, chart 1 already answers it: the CTD-based staircase steps at each switch on a bp axis with percentiles above and ±1σ and ±2σ marked, and it also shows what a distance can't, each switch's consequence (the step height in DV01, the shift in key-rate shares).
  - Distance to *any* switch misleads when neighbouring bonds are near-twins: ZNZ6 on 2026-10-21 was 0.2σ from a switch between 4½% and 3⅞% Aug-33 ($0.6k DV01 apart), while the switch that matters, to 3⅞% Aug-34 (about $8k), was 1.2σ away. If built, measure distance to the next *material* switch (threshold: open-questions.md).
  - What only a time series adds is direction: whether a switch is approaching (yields drifting toward it, or the width shrinking as delivery nears) or has sat at the same distance for weeks. That matters mostly in hindsight, to explain chart 3 and for the backtest.
  - Cheapest form: a mark on chart 3 on dates when a material switch is within 1σ. If a chart is wanted, the CTD's forward yield over time with its ±1σ and ±2σ cone and each switch at its yield level (the CTD's `fwd_yield` plus the switch's `z_bp`) shows both the yield and the time effect.
- **Probability-weighted versus CTD-based DV01:** the most distinctive output for asset managers, showing when their vendor numbers will jump (summary table and charts 1 and 3).

---

## Tier 2 — Credibility and timeliness

- **Contract roll** `[NI]`: run December and March together and show the DV01 and KRD change at the roll with no yield move. Late-November roll is a natural first publication.
- **Uncertainty bands:** rerun at vol ±10% (the band on chart 1) and betas ±0.05 `[NI]`.
- **Calibration backtest** `[NI]`: forecast CTD probabilities against the realised CTD at delivery (Brier score, reliability plot). This decides whether readers trust "30% chance of a switch."
- **Calendar overlay** `[NI]`: auctions adding issues, roll period, first notice day, delivery dates.
- **Daily attribution** `[NI]`: split DV01 changes into yields, time, vol/betas and basket. Sequential, with a fixed documented order (basket, then time, then vol/betas, then yields). Build after regular publication starts; event flags cover it until then.
- **Charts 1 and 2 for a user-entered mix of contracts** `[NI]` (later).

## Fragility dashboard (context row, not a composite score) `[NI]`

1. **Asset-manager duration held via futures:** TFF asset-manager long × probability-weighted DV01 per contract, in $/bp, with net alongside. Trend over time shows buy-side reliance on synthetic duration.
2. **Deliverable float of the next CTD:** outstanding − SOMA − stripped, against front-month OI and asset-manager long OI. An upper bound on supply and a squeeze or specialness indicator.
3. **Rebalancing timing:** flag when a switch zone coincides with month-end or the roll, when asset-manager rebalancing would bunch up. An execution-cost issue, not a level move.

## Rendering

- **Pages:** static HTML pages per date. A summary (contracts, headline numbers, charts 1 to 3 for every contract) groups the charts by contract, each under its ticker linked to the contract's page; the contract page has its charts above the full analytics. The summary gives each contract's CTD with P(RCaD) from both models, the implied delivery date, and today's futures duration. ZT and ZF are omitted.
- **Charts in the browser:** drawn by plotly.js (pinned version, from a CDN) from JSON embedded in the page, so each page is one static file that needs no server (GitHub Pages). Charts 1 and 2 are linked. The pages need the CDN to draw their charts (offline viewing not needed).
  - **Only model outputs go in the JSON** (DV01s, key-rate DV01s, shares, probabilities by shift), no market prices.
  - **Rejected: Dash** (needs a running server); **Python plotly** (static export needs `kaleido`, often flaky on Windows); **Altair** (same export problem, poor shared-axis panels).
- **HTML by plain string formatting**, no template engine.
  - **Why:** two page types with a fixed layout don't need one, and it keeps a dependency out.
- **PNGs as files:** the same charts as matplotlib PNGs in `output/<asof>/png/<contract>-dv01-profile.png` (also `-krd-change`, `-dv01-series`), for the README, the writeup and print; not embedded in the pages.
  - **Why matplotlib:** already a dependency, covers every chart feature (shared-axis panels, a secondary percentile axis, the heatmap with negative shares), and the same result file always draws the same chart (no version stamp in the PNG).
- **Same colors in both:** the heatmap's stops are shared (`charts.SHARE_STOPS`), placed linearly since plotly maps z linearly.
- Written by `report/` from saved results only (`ctd report --asof D`); an older results schema is refused with a request to re-run.

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
| Charts 1–3, distance to switch, probabilities | Security terms (TreasuryDirect, FiscalData), TreasuryDirect daily prices, conversion factors (computed, checked against CME), SOFR and SR1 futures, Treasury par curve, CME basket rules and calendar, CME futures and option settlements (Databento; the bulletin as a cross-check) |
| Roll | Same, plus month-level open interest from the futures settlements; CME Pace of the Roll for comparison with past rolls (not collected) |
| Calibration | Realised CTD computed from own prices at delivery |
| Asset-manager duration via futures | CFTC TFF futures-only (`gpe5-46if`) |
| Deliverable float | MSPD outstanding and STRIPS, NY Fed SOMA holdings, buyback results, auction and reopening results |

**Optional: CME delivery reports.** Not part of the core build. CME posts only the current month's Treasury delivery reports (daily issues and stops, month to date), so there is no history to collect. A report saved by hand during a delivery month can serve as an optional validation input: a check on delivery timing, or on the realised CTD for an ambiguous cycle if it identifies the delivered issue.

## First milestone

Tier 1 for ZN, TN, ZB and UB, plus the December/March roll comparison, before the late-November roll ([roadmap.md](roadmap.md)).
