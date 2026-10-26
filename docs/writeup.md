---
title: "Treasury Futures DV01 beyond the cheapest to deliver: how stable is duration?"
author: Will Shi
date: October 2026
geometry: margin=1in
numbersections: true
---

<!--
Build: pandoc docs/writeup.md -o docs/writeup.pdf --pdf-engine=xelatex --resource-path=docs
Numbers quoted are ZBZ6 on 2026-10-23 (light model) unless stated.
-->

# Summary {-}

Treasury futures risk is usually measured from today's cheapest-to-deliver bond, so the futures DV01 jumps whenever yields move far enough for another bond to become cheapest. The option market already prices the chance of those switches. This write-up weights each deliverable bond by its probability of being cheapest at delivery, which gives a futures DV01 and key rate DV01s that change smoothly as yields move. For the December 2026 bond future (ZBZ6) on 23 October 2026, the probability-weighted DV01 is \$137.0k per bp per \$100mm, against \$126.0k from the CTD alone. After a 49bp sell-off the CTD-based figure jumps to \$174.2k, while the probability-weighted one has risen smoothly to \$148.1k.

# The contract

CBOT Treasury futures (ZN, TN, ZB and UB in this write-up) are agreements to deliver $100,000 face of a Treasury security in the delivery month. The seller (the short) doesn't deliver one specific bond. Any bond in a *basket*, defined by its remaining maturity on the first day of the delivery month, can be delivered:

| Contract | Deliverable remaining maturity | Basket span |
|---|---|---|
| ZN (10-year) | 6.5 to 8 years (notes of original term up to 10 years) | about 1.5 years |
| TN (Ultra 10-year) | 9 years 5 months to 10 years | about 0.6 years |
| ZB (T-bond) | 15 to under 25 years | about 10 years |
| UB (Ultra bond) | 25 years and over | about 5 years |

The bonds in a basket have different coupons and maturities, so they are worth very different amounts. To make them comparable, each bond has a **conversion factor** (CF): its price per $1 face at a 6% yield. A short who delivers bond $i$ receives the invoice price

$$\text{invoice}_i = F \cdot \text{CF}_i + \text{accrued}_i,$$

where $F$ is the futures price. The short buys the bond at its forward price $P_i$ and receives $F \cdot \text{CF}_i$, so it delivers the bond with the lowest **converted price** $P_i / \text{CF}_i$: the **cheapest to deliver** (CTD). At delivery, the futures price converges to that minimum, and before delivery it trades close to it:

$$F \approx \min_i \frac{P_i}{\text{CF}_i}.$$

The future therefore behaves like the CTD scaled by its conversion factor, and so does its interest rate risk: the futures DV01 is approximately the CTD's forward DV01 divided by its CF. That holds only while the CTD stays the same bond.

# The quality option

Conversion factors price every bond at a 6% yield. If every bond in the basket yielded exactly 6%, every converted price would be 100 and no bond would be cheapest. Away from 6%, the factors stop equalising the bonds:

- **Yields above 6%**: high-duration bonds (long maturity, low coupon) lose the most value, and become cheapest to deliver.
- **Yields below 6%**: low-duration bonds become cheapest.

Coupons and the shape of the curve shift these boundaries, but the rule of thumb holds. So which bond is cheapest depends on the level of yields, and the short's right to choose is an option: the **quality option**. Figure 1 shows how it works. Each bond's converted forward price falls as yields rise, at a rate set by its duration. The futures price follows the lowest of them (the envelope), and each kink in the envelope is a **switch point** where the CTD changes.

<!-- TODO: Figure 1. Converted forward price against parallel yield shift for
3-4 ZBZ6 bonds, envelope highlighted, switch points marked.
![Converted forward prices of four ZBZ6 deliverables against a parallel shift in yields. The futures price follows the lower envelope; the CTD changes at each kink.](images/zbz6-envelope-2026-10-23.png) -->

The quality option matters most when:

- **The basket is wide.** ZB's basket spans 15 to 25 years of maturity, so its bonds' durations differ widely and a switch changes the futures DV01 a lot. TN's basket is under a year wide, and UB's switches are between 30-year bonds of similar duration, so both stay stable. ZN sits in between; its basket narrowed from 6.5–10 years to 6.5–8 years from the September 2023 contract.
- **Yields are near 6%.** Converted prices bunch together, so small moves reorder them and switch points sit close to the current yield level.

ZB at the end of October 2026 shows both effects. Its December contract (ZBZ6) has 59 deliverable bonds maturing between 2042 and 2051. With forward yields around 5.4%, the CTD is a mid-basket bond, the 4.625% of November 2044. The next switch, to a longer bond, is only 4bp of sell-off away. Five switches lie within 50bp on the sell-off side, each to a longer, lower-coupon bond, and two lie within 40bp on the rally side. The expected move in yields to delivery is about 46bp (one standard deviation, implied by options). The option market puts the chance of crossing the next switch alone at about 45%, and gives today's CTD only a 25% chance of still being cheapest at delivery.

Each switch changes the bond that the future tracks, and with it the futures DV01 and its spread across maturities. A risk number based on today's CTD alone jumps at each switch point.

# How futures risk is usually reported

<!-- TODO:
- Standard practice: futures DV01 = CTD DV01 / CF; futures KRDs = CTD KRDs / CF,
  at today's CTD. Default in many vendor risk systems and dealer runs.
- Simple, transparent, right while the CTD is stable (TN, usually UB).
- Fails at switches: DV01 jumps (ZBZ6 1-sigma sell-off example), key-rate
  exposure jumps between buckets; ignores the switch probability the market
  already prices.
- Option-adjusted vendor measures: mention only with a citation.
- Hand-off: replace "the CTD" with "each bond, weighted by its probability of being CTD". -->

# Approach

<!-- TODO:
1. Forward prices / CF at GC term repo (SOFR futures).
2. Switch points by parallel shift, as yield shifts and futures prices K_k.
3. Switch probabilities, two independent estimates:
   - Digitals from put/call spread settlements:
     P(F < K_k) ~ [Put(K_hi) - Put(K_lo)] / (K_hi - K_lo) / DF.
     Model-free, includes skew; noisy (64ths, about +/-3pp); at option expiry.
   - Normal model: sigma_y ~ sigma_price * F / (100 * D_F); S = sigma_y sqrt(T);
     Q_k = Phi(-|z_k| / S). Smooth, gives a density; no skew.
   - Agreement = skew matters little; the gap shows the wings' contribution.
4. Probability-weighted DV01 and key rate DV01s; recomputed at each shifted
   state for the duration profile.
Exclusions: no fair value, implied repo, end-of-month or wildcard options; GC funding. -->

# Results: ZB, December 2026

![ZBZ6 DV01 profile on 2026-10-23. Top: futures DV01 across parallel shifts in basket forward yields, probability-weighted (blue, with the band for vol ±10%) against CTD-based (grey). Bottom: the share of DV01 at each key rate.](images/zbz6-dv01-profile-heatmap-2026-10-23.png){width=90%}

![ZBZ6 key rate DV01 change from today at $\pm 1\sigma$ and $\pm 2\sigma$, 2026-10-23: probability-weighted (bars) against CTD-based (dashes).](images/zbz6-krd-change-2026-10-23.png){width=90%}

<!-- TODO:
- Walk through the two figures. Numbers ($k per bp per $100mm, prob-weighted /
  CTD-based): -2sigma (-92bp) 139.7 / 139.0; -1sigma (-46bp) 134.2 / 129.8;
  today 137.0 / 126.0; +1sigma (+46bp) 147.5 / 142.6; +2sigma (+92bp) 152.1 / 158.9.
  CTD-based jumps 142.6 -> 154.4 at +47bp and -> 174.2 at +49bp.
- Key rates: weight moves from 15y to 20-25y in a sell-off; CTD-based moves in jumps.
- Distance to next switch: +3.8bp (0.08 sigma) sell-off, -14.2bp rally; width 46bp.
- Table per switch point: K_k, digital, normal, gap.
- Optional: ZN or UB contrast. -->

# Validation

<!-- TODO: bond math vs QuantLib; CFs vs CME tables; the two probability
estimates agree; historical backtest not yet done. -->

# Further work

<!-- TODO, one short paragraph each:
- Betas: non-parallel moves; sell-off betas; shrinkage; daily re-estimation;
  20y sector reference; residual slope variance widens probabilities.
- SABR smile: normal SABR per expiry; digitals from the fitted put curve;
  monotone tails; convolution from expiry to delivery; wing caveat.
- Interest rate model: two-factor or term-structure model for slope risk;
  horizon at delivery; timing options and fair value.
- Bond-specific spreads (brief): rich/cheap issues and special repo move
  switch points; mean-reverting spreads, bond-level betas, CTD repo. -->

# Limitations

<!-- TODO: risk-neutral probabilities; lagged, rounded free prices; thin UB options. -->
