# Open questions

Questions not yet settled, with the options and evidence where they have been worked through. When one is settled, write the outcome into the section it governs (design.md, data.md or outputs.md) with its reasons, and delete the entry here. Progress on building things is in [roadmap.md](roadmap.md).

## Model

### Betas: which estimates beat node betas (design §5.4)

**Starting point (in design §5.4):** regress at the published tenors and interpolate β linearly in maturity.

**Alternatives to compare in the backtest:**
1. **Spline weights.** A natural cubic spline through the node betas (equivalent to spline-interpolating yields). With nodes 10 years apart, linear and spline weights usually differ by a few hundredths of beta, within the ±0.05 sensitivity range (design §8). Run as a sensitivity case.
2. **Pooled bond-level betas.**
   - Regress each basket bond's own yield changes (from its price) on the reference, pooled across the basket: fit β(τ) = a + b·τ (+ c·τ²), with τ updated daily as bonds age.
   - Needs no interpolation, and captures sector effects the par curve smooths away, such as the 20-year sector trading distinctly from old 30-year bonds.
   - Possible now: TreasuryDirect prices are stored daily from 2016. They are rounded and struck at a different time from the futures settlement, so individual bonds are noisy; pooling is what makes this usable.

**Also open:**
- **Window and decay.** Which estimation window and decay best predict realised basket moves?
- **Sell-off betas.** When are they materially different enough to use?
- **ZB's reference factor.** The 20-year CMT reflects a sector with its own idiosyncrasies. If its regression residuals look noisy, use the average of the 10 and 30-year yields, or the 30-year alone, and let the betas do the rest.

**How to settle:** backtest scoring (design §8).

### Distribution when the option expiry is after the horizon (design §5.5.1 step 5)

A contract trades for about a month after its own options expire, and its CTD question matters most then. Its vol then comes from the next contract's options (design §5.5 step 3).

- **When it happens:** positive carry (horizon = last delivery day) usually still has two expiries bracketing the horizon, e.g. the January and February serials for a 31 December horizon, so convolution works. Negative carry (horizon = first delivery day) doesn't: after the December options expire, the first usable expiry is the January serial, three weeks after a 1 December horizon. The ATM path is unaffected, since the √T fallback scales down.
- **Interim choice:** rescale the factor distribution to the horizon, `z_h = z_E × √(V(T_h)/V(T_E))`. It keeps the expiry's skew unchanged, so if anything it overstates skew at the shorter horizon.
- **Alternative:** deconvolve, fitting `φ_h` so that `φ_h` convolved with `N(0, V(T_E) − V(T_h))` matches the expiry distribution. Consistent with step 5 but ill-posed (noise in the fitted wings is amplified); worth trying only if backtests show the rescaling biases tail probabilities.
- **Needed either way:** the expiry's distribution is on the *next* contract's futures, so it is mapped through that contract's envelope and the betas to the expiring contract's factor. Weakest for ZB, whose two contracts' CTDs can differ most.
- **To find out:** how often this case arises (negative-carry dates after option expiry), and whether rescaling and deconvolution differ materially there.

### Recentring gap: what size means inconsistent inputs (design §5.11, §9)

The gap `F_market − E(0)` absorbs the delivery options (its level) and the timing difference between TreasuryDirect prices and the 2pm CT settlement (most of its daily change, about 1.3bp of yield common to all contracts).

- What size of gap, or of its daily change, should warn of inconsistent inputs?
- Should the model centre on yields consistent with the futures settlements instead, which would remove the timing offset?

### Option-implied percentile marks on chart 1, before the smile fit

The profile uses a normal factor (design §5.9), so its percentile axis is symmetric. An interim step:
- Add a second set of axis marks from the light model's digitals at c = 0: a digital at every listed strike, each strike mapped to z through the envelope (`z(K)` solving `E(z) − E(0) = K − F_market`), and the 5th, 25th, 75th and 95th percentiles of the resulting CDF marked.
- The gap to the normal marks shows the skew the charts leave out. It reuses `vol/digitals.py` and `model/envelope.py`, and labels the axis without feeding the shifted-state weights.
- The wings' rounding noise and upper bounds fall where the outer percentiles sit.

**Open:** whether it's worth building before phase 3.

### Distance to the next *material* switch ([outputs.md](outputs.md), Other Tier 1 outputs)

Distance to any switch misleads when neighbouring bonds are near-twins (ZNZ6 on 2026-10-21: 0.2σ from a switch worth $0.6k of DV01, 1.2σ from one worth about $8k).
- What DV01 jump makes a switch material: an absolute amount per $100mm, a share of the DV01, or a change in effective maturity?
- Is it worth a time series at all, or a mark on chart 3 on dates a material switch is within 1σ?

### Realised vol

- Which window for the comparison and fallback?
- How does realised compare with implied vol? Testable over 2016–2026 with the option backfill.

### UB options

- How often are UB options too thin to use?
- Is ZB vol mapped through betas a good enough substitute?

## Data and history

### Repo before May 2018 (design §5.3, §7)

There is no SR1 or SOFR before May 2018.
- **Option A:** flat repo.
- **Option B:** ZQ plus an assumed SOFR–fed funds spread. The spread is testable against SR1 on the overlap; ZQ's front eight months are in the derived futures table from 2016.

**Decide when** historical mode is built.

### ZN's run window (design §7)

ZN's next quarterly options are liquid from about four weeks before the expiry, three weeks earlier than the common start rule. A ZN-only earlier start (e.g. the Friday four weeks before) would lengthen its roll comparison. Not adopted for now: one rule for all four products is simpler.

### TreasuryDirect's price columns (design §5.1)

What do TreasuryDirect's buy, sell and end-of-day columns mean, and at what time is each struck? End of day is empirically the nearer snapshot to the futures settlement, but which way round the two times are isn't known.

### CME Pace of the Roll

- What does it publish?
- Can past rolls be retrieved?

Month-level open interest already comes from the daily settlements.
