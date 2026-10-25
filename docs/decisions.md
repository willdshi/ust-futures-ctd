# Decisions

Choices about how the project runs and how the model is built, with the options considered and the reasoning. Each entry has a status; when a decision is made or revisited, record the outcome and date under it. Open modelling questions not yet worked through stay in [design.md](design.md) §11.

## Scheduled fetch when the PC is asleep or hibernating

**Status:** undecided, low priority (raised 2026-10-21).

**Now:** the Windows scheduled task `ctd-daily-fetch` (registered by `scripts/register_daily_fetch.ps1`) runs `ctd fetch --catch-up` at 19:00 on weekdays.
- If the PC is asleep or hibernating at 19:00, the run is missed, but "run as soon as possible after a missed start" is on, so it runs at the next wake.
- `--catch-up` retries the as-of date and the 4 business days before it.
- It runs only while the user is logged in.

**Risk:** small. Almost every automated source can be fetched later for a past date (see [data.md](data.md) §2.5):
- TreasuryDirect prices and security terms, FiscalData, the par curve, FRED, NY Fed and CME's TCF files are recoverable for any past date.
- Yahoo bars come in 10-day windows, and older days stay available while a contract is listed (`ctd backfill`).
- CME settlements and the bulletin don't depend on the schedule; they need the bookmarklet click.

So hibernation delays collection rather than losing data, unless the PC is off for more than the 5-business-day catch-up window.

**Options:**

| Option | Effect | Cost |
|---|---|---|
| 1. Let the task wake the PC (Task Scheduler "Wake the computer to run this task") | Runs on time from sleep, and usually from hibernate | Needs "Allow wake timers" on in the power plan. Doesn't work from shutdown; laptops on battery often ignore wake timers |
| 2. Add a second trigger, at logon or e.g. 08:00 | A missed evening is picked up as soon as the PC is used | None; repeat runs skip anything already collected |
| 3. Widen `--catch-up` from 5 to 10 business days | A week away fills itself in; matches Yahoo's 10-day window | Slightly longer runs after an absence |
| 4. Run on an always-on machine (mini PC, NAS, small cloud server) | Guaranteed nightly runs | Move and back up the store; overkill while CME needs a manual click |

**Recommendation:** options 1–3 together. They cover hibernation, a missed evening and a week away, and need only:
- a change to `scripts/register_daily_fetch.ps1`;
- a one-line change to `CATCH_UP_DAYS` in `src/ctd/cli.py`;
- a check of the power plan's wake-timer setting (`powercfg`).

**After a longer absence, by hand:** run `ctd fetch --asof <date>` for each missed day, or `ctd backfill`.

## Key-rate grid for KRDs (design §5.9)

**Status:** adopted (2026-10-22), from [outputs.md](outputs.md) Conventions.

**Decision:** key rates at **2, 5, 7, 10, 15, 20, 25 and 30 years**, each a triangular (tent) bump to the par curve between neighbouring nodes (method in the next entry; until 2026-10-24 the tents bucketed cash flows). The grid is fixed; changing it changes every published KRD and the effective-maturity series, so record any change here with its date.

**Why these nodes:**
- 15 and 25 years aren't published par-curve points; their par yields are interpolated (next entry). Without them, a ZB switch (about 15y to about 25y) would be split across the 10, 20 and 30-year buckets and barely show.
- Tent bumps keep KRDs and effective maturity smooth as a bond rolls past a node; a step scheme would add artificial jumps to the time series.

## How KRDs are computed (design §5.9)

**Status:** adopted (2026-10-24), replacing cash-flow bucketing ("curve-based later if needed").

**Decision:** par-curve key-rate bumps, scaled to the pricing function's DV01.
1. **Curve:** the Treasury par curve stored for the as-of date, par yields interpolated **linearly** between the published tenors onto a semiannual grid, and discount factors bootstrapped from it (each grid point a par bond paying semiannually; log discount factors interpolated linearly between grid points).
2. **Bumps:** for each node, add 1bp × its tent weight to the par yields, re-bootstrap and reprice the bond's cash flows after the horizon (times measured from the horizon; today's curve, not a forward curve). The bond's KRD at that node is the price fall.
3. **Scaling:** the bumps give only the shape (each node's share). The shares are scaled to the bond's DV01 at its forward yield from `ctd.bonds.pricing`, so one pricing function sets every duration number (§5.1) and the KRDs sum to the DV01 series exactly. The curve need not reprice an off-the-run bond; a 10bp yield difference moves duration about 0.02y.

**Why par bumps, not cash-flow bucketing:**
- A par-curve KRD is the hedge in par bonds at each tenor, which is how the audience hedges, and what vendor KRDs report. Cash-flow bucketing describes where a bond's coupons fall (a STRIPS hedge).
- The two agree on total DV01 but not on shape, and disagree most on the ZB switch, where the CTD is a high-coupon bond near par and the sell-off contenders are deep-discount low coupons. Flat curve at forward yields on 2026-10-21, from the 31 Dec horizon: the 5% May-45 CTD has effective maturity 15.5y bucketed and 18.6y bumped; the 1⅜% Aug-50 21.6y and 27.9y. A switch between them moves effective maturity +6.1y bucketed and +9.3y bumped. ZN barely differs (4½% Aug-33: 6.3y and 6.7y).

**Why linear interpolation is enough:** on the 2026-10-21 par curve (humped: 20y 5.47%, 30y 5.42%), linear, PCHIP and a natural cubic spline agree to within 0.07y in duration, 0.06y in effective maturity and 0.6 points in any bucket's share, across the ZB contenders and the ZN CTD. The tolerance is 0.1y. KRDs depend on where cash flows sit relative to the nodes, not on fine curve shape.

**Consequence, explained in the published notes ([outputs.md](outputs.md) Conventions):** a low-coupon bond equals a par bond less a stream of coupons, so its hedge is more than 100% at its own maturity and short at earlier tenors. Its short-tenor KRDs are negative (the 2¼% Aug-46: −7% at 10y, +117% at 20y), and its effective maturity can exceed its maturity (21.7y for 19.6y left). Chart 1's bucket-share panel must allow negative shares.

## Estimating betas for the deliverable basket (design §5.4)

**Status:** option 1 adopted as the starting point (2026-10-21). Run option 2 as a sensitivity case. Option 3 can be estimated now, since TreasuryDirect prices are stored daily from 2016; compare all three in the backtest.

**Question:** each basket bond needs a beta to the contract's reference yield (7-year CMT for ZN, 10-year for TN, 20-year for ZB, 30-year for UB). But Treasury's par curve only publishes 1, 2, 3, 5, 7, 10, 20 and 30-year points, and the bonds sit between them.

**The key fact:** with any interpolation that is linear in the node yields (linear, or a standard cubic spline), the beta at an intermediate maturity is the same weighted combination of the betas at the nodes. Regression is linear, so "interpolate yields, then regress" gives the same answer as "regress at the nodes, then interpolate the betas". Betas only ever need estimating at the published tenors; the interpolation choice just sets the weights between them.

**Options:**

1. **Node betas, linearly interpolated (start here).**
   - Regress each published tenor's yield changes on the reference. The 5, 7, 10, 20 and 30-year points cover all four baskets.
   - Interpolate β linearly in maturity to each bond. That's identical to linear interpolation of the curve.
   - Simple, transparent and stable.
   - For ZB, everything between 15 and 25 years comes from the 10, 20 and 30-year betas. For UB, bonds of 25 to 30 years sit between the 20 and 30-year nodes. That's interpolation, not extrapolation, for every basket.
2. **Node betas with a smoother curve shape.**
   - A natural cubic spline through the node betas, equivalent to spline-interpolating yields.
   - Gives curvature between nodes. With nodes 10 years apart, linear and spline weights usually differ by a few hundredths of beta at most, within the ±0.05 sensitivity range already in design §8.
   - Avoid monotone schemes such as PCHIP: they aren't linear in the node values, so the equivalence above breaks.
3. **Betas from the bonds themselves (best once data allows).**
   - Regress each basket bond's own yield changes, computed from its price, on the reference.
   - Individual bonds are noisy (rounded prices, ageing issues), so pool them: fit β(τ) = a + b·τ (+ c·τ²) across all basket bonds jointly, with maturity τ updated daily as bonds age.
   - Needs no interpolation, and captures sector effects the par curve smooths away, such as the 20-year sector trading distinctly from neighbouring old 30-year bonds.
   - Needs bond price history. TreasuryDirect daily prices are now stored for every business day since 2016-01-04 ([data.md](data.md) §5.1), so this can be estimated now. The earlier plan to wait for about six months of daily collection no longer applies, though those prices are rounded and struck at a different time from the futures settlement.

**How much it matters:** CTD switches depend on beta *differences* between candidate bonds. A crossover's sensitivity to a beta error is roughly its distance from the forward times the beta difference: for ZB, a 0.03 beta error on a 30bp crossover moves it by about 1bp. The interpolation choice matters less than the estimation window and whether sell-off-only betas are used (design §5.4).

**Related: the ZB reference factor.** The 20-year CMT reflects the 20-year sector, which has historically traded with its own idiosyncrasies. If its regression residuals look noisy, consider using the average of the 10 and 30-year yields, or the 30-year alone, as ZB's reference, and let the betas do the rest.

## Which TreasuryDirect price the model uses (design §5.1)

Each FedInvest file has buy, sell and end-of-day columns; end of day is filled in about a day later (data.md §5.1).

**Decision:** use end of day wherever it exists: all history, and every live date once the next evening's catch-up has completed its file. Only for a date still provisional (a same-evening run), fall back to the buy/sell midpoint (sell where there is no buy) and mark the result provisional.

**To confirm:** that end of day is the snapshot closest to the 2pm CT futures settlement (phase 1b open question), and TreasuryDirect's own definition of the three columns.

## Delivery date for the light model's forward prices (design §5.11)

The light model has no horizon logic (§5.2 runs both dates when carry is near zero), so it needs a fixed rule.

**Decision:** take forwards to the last delivery day if the CTD's carry is positive, the first delivery day if negative. Carry is measured directly: the CTD (cheapest converted forward at the last delivery day) has positive carry when its forward clean price at the last delivery day is below the one at the first. One date for the whole basket, as in §5.2. Settled 2026-10-22, replacing a phase 1b open question.

## Derived tables: format and columns (design §4)

**Decision** (settled 2026-10-23):
- **Parquet, not Feather.** The tables are written once and read many times, filtered by product and date. Parquet's row-group statistics let those reads skip data, its dictionary encoding and zstd make it several times smaller (product, label, right and source repeat on every row), and every tool reads it. Feather (Arrow IPC) reads faster with no filtering and suits scratch files, not a store read selectively for years.
- **Partitioned by product and year, with a per-source staging stage**, so the daily build rewrites one small partition and the slow Databento option backfill is read once.
- **No option delta.** CBOT Treasury options are American and CME's deltas come from its own model; a Black-76 delta from the settlement-implied vol is close enough for anything the model does, and consistent with it. Databento has no delta, so the column would be null before 2026-10-16 anyway. The bulletin PDFs keep CME's, for a check if ever wanted.
- **No futures volume.** CME's page has a same-day estimate, Databento the final cleared volume: different quantities, so one column with a precedence rule would mix them. Nothing in the model uses it; both stay in the raw store.

## Probabilities in the published charts, first milestone (design §5.6, §5.11)

**Status:** adopted (2026-10-24).

**Decision:** charts 1 and 2 and the distance to switch use a normal factor, `z ~ N(c, σ√T)` with β = 1 and σ from the ATM implied vol (phase 1c, design §10). The light model's option digitals are published alongside as a cross-check, not fed into the charts.

**Why:** the charts need probabilities at shifted states (each centre `c` from −100 to +100bp, ±1σ and ±2σ). The light model's digitals are today's option prices and can't be moved to another state; the normal factor can, using the same envelope. Its cost is no skew, so at `c = 0` it won't match the digitals. The gap is reported, and the smile-implied distribution (phase 3) is the fix if it is material.

## Chart rendering (design §6, outputs.md)

**Status:** adopted (2026-10-24).

**Decision:** matplotlib PNGs, embedded (base64) in one self-contained HTML page per as-of date under the gitignored `/output/`, written by `report/` from saved results. Plain string formatting for the HTML; no template engine.

**Why:**
- matplotlib is already a dependency and covers every chart feature: two panels on a shared x-axis, a secondary x-axis in percentiles (`secondary_xaxis` with bp↔percentile functions), a staircase overlay, diverging bars in small multiples, and the bucket-share panel with negative shares (positives stacked above zero, negatives below, or a heatmap).
- Static PNGs are what a rates note, email or post takes, and the same result file always draws the same chart (reproducibility).
- Plotly's static export needs `kaleido` (often flaky on Windows) and makes the dual bp/percentile axis awkward; interactivity isn't what readers need. Altair has the same export problem and handles shared-axis panels poorly. An interactive view can be added later for exploration.

## When December options expire (design §5.11, §10)

**Status:** adopted (2026-10-24), replacing a phase 1b open question.

**Decision:** roll at option expiry. Each contract's series runs on the contract whose quarterly options are the nearest not yet expired: ZBZ6 and ZNZ6 through 2026-11-19, ZBH7 and ZNH7 (with MAR27 options) from the December options' expiry, 2026-11-20. The light model already stops a contract once its options have expired. The March contracts are also run alongside from now, for the roll comparison (outputs.md Tier 2). Phase 1c follows the same rule.

**Given up:** the December contract after 2026-11-20, which still trades to mid-December and delivers to month-end, when its CTD question matters most. Covering it needs vol from the next expiry (§5.5 step 3; the expiry-after-horizon issue in §11) and is left for phase 2.

## Holiday calendar for 2016–2025 (data.md §2.5)

**Decision** (settled 2026-10-24): derive past holidays from the stored data, not from CME or a calendar library.
- CME publishes no structured archive of past holidays: each year's schedule, an online Trading Calendar for current dates, and old notices and press releases. Assembling ten years from those would be by hand, and cmegroup.com blocks scripts.
- A calendar library (pandas_market_calendars, exchange_calendars) encodes holidays as rules, which is where special closures go wrong: CME settled on the 2018-12-05 day of mourning and on the 2021 and 2023 Good Fridays. It would also be a new dependency.
- The data records what happened. `scripts/derive_holidays.py` marks a CME closure where none of the 15 Databento backfills has a settlement and a bond-market closure where TreasuryDirect has no prices; rule-based names only label the rows, and each row says what it rests on. Weekdays with no settlements that aren't holidays are gaps, confirmed by Yahoo volume or TreasuryDirect prices, and `ctd derive` lists every product's missing trading days, so skipped dates in history need no diagnosis.
- Known difference: TreasuryDirect published on Good Friday 2024 and 2025, when SIFMA usually recommends closing, so the `sifma` calendar has those two open.
