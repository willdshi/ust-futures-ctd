# UST Futures CTD

How stable is the duration you hold through Treasury futures, and how does it change as interest rates move? 

This project models the cheapest-to-deliver (CTD) bond for CBOT Treasury futures. From that it computes what a futures position's interest-rate risk really is: futures DV01, key rate DV01s and how both move as yields move. It runs end of day, from free public data only.

The impact of the quality option on futures duration is particularly important as rates approach 6% in a volatile interest rate environment. Impact is particularly acute for the ZB contract with a 15-25yr maturity delivery basket.

**[Sample report](https://willdshi.github.io/ust-futures-ctd/)** · **[Model writeup (PDF)](docs/writeup.pdf)**

![ZBZ6 DV01 profile on 2026-10-23: the probability-weighted futures DV01 rises smoothly across yield shifts while the CTD-based DV01 jumps at each switch, with the key-rate split below](docs/images/zbz6-dv01-profile-2026-10-23.png)

*ZBZ6 on 2026-10-23: futures DV01 across parallel yield shifts, probability-weighted (blue) against CTD-based (grey, jumping at each switch), and its split by key rate.*

## Why it matters

A Treasury futures contract tracks whichever bond in its delivery basket is cheapest to deliver. Most risk systems report the futures DV01 from today's CTD alone. When yields move far enough for a different bond to become cheapest, that DV01 jumps, sometimes by a third or more for ZB, where the basket spans 15 to 25 years of maturity.

The market already prices the chance of a switch, so the risk you hold changes smoothly, not in a step. This model publishes that smooth version:

- **CTD probabilities** for every bond in the basket, read from listed option settlements.
- **Probability-weighted futures DV01 and key rate DV01s**, next to the CTD-based figures most systems show.
- **A duration profile**: DV01 and its key-rate shape across yield shifts, with ±1σ and ±2σ marked, recomputing the switch probabilities at each shifted state.
- **Distance to the next switch**, in basis points and in standard deviations.

For example, on 2026-10-21 ZBZ6 (December T-bond futures) carried $137,000 of DV01 per $100mm notional. CTD-based it carried $124,000. After a 1σ sell-off, the model's DV01 rises to $147,800, while the CTD-based figure jumps to $172,100 as the CTD moves to a longer, low-coupon bond.

Intended use is for monitoring duration exposure, not for relative value trading. There is no futures fair value, no implied repo and no delivery-option valuation. See the write-up for a more detailed explanation.

## How it works

1. **Basket and forward prices.** Each deliverable bond is priced forward to the implied delivery date at term repo (from the one-month SOFR futures strip), and divided by its conversion factor.
2. **Switch points.** Yields are shifted in parallel; the yield and futures levels at which the cheapest bond changes are found by exact root-finding.
3. **Probabilities.** The probability of reaching each switch comes from two independent models: digitals from put and call spreads on the CME option settlements, and a normal distribution at the at-the-money implied vol.
4. **Risk.** Each bond's DV01 and key rate DV01s (tent bumps on the Treasury par curve at 2, 5, 7, 10, 15, 20, 25 and 30 years) are weighted by the probability that it is CTD, and recomputed at every shifted state for the duration profile.

All bond math (pricing, yields, accrued, conversion factors, forwards) is hand-written in one street-convention pricing function, and tested against QuantLib and CME's published conversion factor tables. The full specification is in [docs/design.md](docs/design.md). Outputs are specified in [docs/outputs.md](docs/outputs.md), and settled choices are recorded in [docs/decisions.md](docs/decisions.md).

## Data

Everything comes from free public sources, apart from a one-off paid backfill of futures and option settlement history:

| Data | Source |
|---|---|
| Bond prices and security terms | TreasuryDirect, Fiscal Data |
| Treasury par yield curve | U.S. Treasury |
| SOFR and other reference rates | New York Fed |
| Futures and option settlements | CME Group (downloaded daily in a browser) |
| Conversion factor tables | CME Group public FTP server |
| Settlement history, 2016 to October 2026 | Databento (one-off backfill) |

Every file is stored exactly as downloaded, keyed by its as-of date, and the model reads only from that store. Re-running a past date therefore gives the same answer. The store's layout and each source's quirks are described in [docs/data.md](docs/data.md).

**The data itself is not included in this repository.** Market data from CME, Databento and others is licensed and can't be redistributed. The code and the report pages are published; to run the model yourself, you'd collect your own data store with `ctd fetch`.

## Status

Working now, for the December 2026 futures contracts:
- daily data collection for six Treasury futures contracts and their options, with gap alerts
- the light model: switch points and CTD probabilities from option digitals
- futures DV01, key rate DV01s and the duration profile
- the single-date HTML report (duration profile and key-rate change charts, with tables)
- derived Parquet tables over ten years of history

Next: the March 2027 contracts and the December/March roll comparison, total-variance vol interpolation, then the daily time series and a historical backtest. The roadmap is in [design.md §10](docs/design.md).

## Running it

The Python package and command-line tool are both called `ctd`. Python 3.13, with the conda environment in `environment.yml`:

```
conda env create -f environment.yml
conda activate ctd
pip install -e . --no-deps

ctd fetch --asof 2026-10-21              # snapshot every source into ./data
ctd run --contract ZBZ6 --asof 2026-10-21    # light model, prints and saves results
ctd report --asof 2026-10-21             # single-date HTML page in ./output
pytest -m "not network and not slow"     # tests that need no downloads
```

## Disclaimer

This is a personal research project. It is not investment advice, comes with no warranty, and its outputs should not be relied on for trading or risk management.

## License

MIT, see [LICENSE](LICENSE). The licence covers the code and documentation in this repository, not the market data the model reads.
