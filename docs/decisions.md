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

**Decision:** key rates at **2, 5, 7, 10, 15, 20, 25 and 30 years**, with cash flows bucketed by triangular (tent) weights between neighbouring nodes. The grid is fixed; changing it changes every published KRD and the effective-maturity series, so record any change here with its date.

**Why these nodes:**
- 15 and 25 years aren't par-curve points, but KRDs bucket cash flows and need no market yield at the node. Without them, a ZB switch (about 15y to about 25y) would be split across the 10, 20 and 30-year buckets and barely show.
- Tent weights keep KRDs and effective maturity smooth as a bond's cash flows roll past a node; a step scheme would add artificial jumps to the time series.

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
