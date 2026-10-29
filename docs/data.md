# Data

What the collector gathers, where it comes from, how it's stored, how the datasets fit together, and the settled choices about data. [design.md](design.md) §3 says *why* each dataset is needed; this file is the working reference for *what is actually there*.

## 1. Overview

Every business day, scheduled tasks snapshot each source into a local raw store under the as-of date (§4). CME futures and option settlements come from a daily Databento pull (`databento_daily`, §5.14), the record from 2026-10-26. CME's own settlement pages and Daily Bulletin have no free download feed; they can still be saved from cmegroup.com with the `ctd bookmarklet` and picked up by `ctd ingest`, as an optional cross-check and the only source of SR3 and ZQ.

| Source id | What | From | How | Schedule | Stored from |
|---|---|---|---|---|---|
| `td_prices` | End-of-day prices, every Treasury CUSIP | TreasuryDirect FedInvest | auto | daily | 2016-01-04 |
| `td_securities` | Security terms, every auctioned security | TreasuryDirect securities search | auto | daily | full history in each daily file |
| `fiscaldata_auctions` | Auction results, every auction since Oct 1979 | FiscalData API | auto | daily | full history in each daily file |
| `par_curve` | Nominal par yield curve and bill rates | Treasury (home.treasury.gov) | auto | daily | current year daily; 1990+ backfilled |
| `fred` | CMT yields, SOFR, effective fed funds | FRED | auto | daily | full history in each daily file |
| `nyfed_rates` | SOFR, TGCR, BGCR, EFFR | NY Fed Markets API | auto | daily | trailing 2 weeks daily; 2018-04-02+ backfilled |
| `cme_tcf` | Conversion factors and deliverable baskets | CME public FTP | auto | daily | 2023-12-11 |
| `yahoo_fut` | Daily bars, six Treasury futures | Yahoo Finance chart endpoint | auto | daily | 10 days per pull; listed contracts and front month from 2000 backfilled |
| `databento_daily` | Futures statistics (Treasury front two, SR1 front seven) and standard Treasury option statistics and definitions | Databento (paid) | auto | daily | 2026-10-26 |
| `cme_fut` | Futures settlements: ZT, ZF, ZN, TN, ZB, UB | cmegroup.com | bookmarklet | occasional (cross-check; daily to 2026-10-26) | 2026-10-14 |
| `cme_stir` | Futures settlements: SR1, SR3, ZQ | cmegroup.com | bookmarklet | occasional (only source of SR3 and ZQ after 2026-10-21) | 2026-10-14 |
| `cme_bulletin` | Daily Bulletin Section 42: options on the six Treasury futures | cmegroup.com | bookmarklet | occasional (cross-check; daily to 2026-10-26) | 2026-10-16 |
| `cme_opt` | Per-product option settlement files | cmegroup.com | auto if CME allowed | occasional | none |
| `databento_fut_backfill` | Futures settlements and open interest, front two contracts of the nine CME futures | Databento (paid) | script | backfill | 2016-01-01 → 2026-10-21 (SR1, SR3 from 2018-04-27) |
| `databento_opt_backfill` | Option settlements and open interest by strike, standard expiries on the six Treasury futures | Databento (paid) | script | backfill | 2016-01-01 → 2026-10-19 |
| `databento_stir_backfill` | SR1 and ZQ, 3rd to 8th months | Databento (paid) | script | backfill | 2016-01-01 → 2026-10-22 (SR1 from 2018) |

Backfill-only source ids (`par_curve_backfill`, `nyfed_rates_backfill`, `yahoo_fut_backfill`, `databento_fut_backfill`, `databento_opt_backfill`, `databento_stir_backfill`) hold the one-off history pulls; see §4. The three Databento backfills are written by standalone one-off scripts rather than `ctd backfill`. The scripts are not in the repository; each request is recorded in §5.11 to §5.13 and in each file's meta sidecar.

The six Treasury futures in scope are ZT, ZF, ZN, TN, ZB and UB. The model reads ZN, TN, ZB and UB, all four alike (design §1); ZT and ZF are collected so they can be added later. What the model publishes is in [outputs.md](outputs.md).

### Which source covers which dates

The derived tables (§9) pick one source per date; the others are cross-checks on the dates they overlap.

| Data | Source by date |
|---|---|
| Treasury futures | Databento backfill to 2026-10-13; CME pages (`cme_fut`) 2026-10-14 to 10-23; `databento_daily` from 2026-10-26 |
| SR1 | Databento backfill (front eight months) to 2026-10-13; `cme_stir` 2026-10-14 to 10-23; `databento_daily` (front seven) from 2026-10-26 |
| SR3, ZQ | Databento backfill (ZQ front eight, SR3 front two) to 2026-10-13; `cme_stir` from 2026-10-14, on bookmarklet days only |
| Treasury options | Databento backfill to 2026-10-15; the Section 42 bulletin 2026-10-16 to 10-23; `databento_daily` from 2026-10-26 |

The bulletin stretch prints only strikes with open interest or volume (§5.9), so its chains are smaller than Databento's on either side. Buying `databento_daily` for 2026-10-20 to 10-23 would close it (about $1; [roadmap.md](roadmap.md) 1e.8). Its measured effect is in design §3.1.

### History starts in 2016

Historical mode, backtests and basket rebuilds go back to **January 2016 (the March 2016 contract month) and no further**. Treasury futures rules changed several times before that, and those changes aren't encoded or handled.

- Some stored data goes back further: Yahoo's front-month series (2000), the par yield curve (1990), FRED series, FiscalData auctions (1979) and TreasuryDirect security terms. Keep it as collected, but don't use observations before 2016.
- TreasuryDirect prices are stored from 2016-01-04 to match; earlier dates (back to May 2008) aren't backfilled.
- Deliverable-grade records (`src/ctd/reference/data/contract_grades.toml`) start with the March 2016 contract month. Looking up an earlier month raises an error rather than applying an unchecked rule.
- Rule changes from 2016 on are encoded as dated records, e.g. ZN's 8-year cap from the September 2023 contract month.

## 2. The raw store

### 2.1 Layout

The store lives in `/data/` at the repo root (gitignored; override with `CTD_DATA_ROOT`).

```
data/
  raw/<asof>/<source>/<unit>/<name>.gz          the file exactly as downloaded, gzip-compressed
  raw/<asof>/<source>/<unit>/<name>.meta.json   where it came from (2.2)
  raw/<asof>/manifest.json                      what was expected and collected that day (2.3)
  inbox/<asof>/<source>/...                     manual-drop folder (2.4)
  inbox/_ingested/...                           originals after ingest
  gaps.log                                      append-only log of every gap reported
  morning.log                                   output of the scheduled morning task (§4)
  cme_bookmarklet.html                          page to install the bookmarklet (`ctd bookmarklet`)
  derived/                                      Parquet tables built from raw/ by `ctd derive` (§9); a cache
  results/                                      model output, e.g. results/light/ZBZ6/2026-10-21.json
```

- **`<asof>`** is the business day the data describes, as `YYYY-MM-DD`. For history-type sources (§3) it's the day the file was pulled.
- **`<unit>`** splits a source into independently tracked pieces: a product (`ZN`), a series (`DGS10`), a security type (`Bond`), a table, or a file format (`csv`/`xlsx`). A source-level manual drop that can't be matched to a unit goes under `_manual`.
- **`<name>`** is chosen by the fetcher, usually the remote file name with the date added (e.g. `securityprice_2026-10-19.csv`, `TCF_20261019.csv`). Files from the bookmarklet keep the short names ingest gives them (`ZN.json`, `Section42.pdf`), since the date and source are already in the path.

### 2.2 File rules and metadata

- **Exactly as downloaded.** Bytes are stored unchanged, gzip-compressed at rest (`mtime=0`, so the same bytes always give the same `.gz`). Read them back with `RawStore.read` (§7).
- **Never overwritten.** Writes use exclusive create; a re-run skips anything already stored. Re-running a fetch is always safe.
  - **One exception:** TreasuryDirect price files pulled the same evening are provisional and get replaced by the completed file a day later (§5.1). It applies only to a source that can be pulled again for any past date and is marked `provisional` in its source spec; every other source, including all CME data, is never overwritten.
- **Validated before storing.** A fetcher rejects an empty or obviously wrong response (an HTML error page instead of CSV, a non-PDF bulletin) so it can't block the correct file later.

Each file has a `.meta.json` sidecar:

| Field | Meaning |
|---|---|
| `asof`, `source`, `unit`, `name` | where it sits in the store |
| `bytes`, `sha256` | size and SHA-256 of the original, uncompressed bytes |
| `stored_at` | when it was written to the store (UTC) |
| `origin` | `auto` (fetched) or `manual` (inbox or bookmarklet) |
| `url`, `method`, `params`, `http_status`, `content_type`, `downloaded_at` | automatic fetches: the request and response |
| `cost_usd` | Databento pulls: the quoted cost |
| `original_path`, `original_mtime` | manual files: where the file was dropped and when it was saved |
| `renamed_from`, `moved_from` | present on the few files reorganised by hand |

### 2.3 Manifests and statuses

`raw/<asof>/manifest.json` lists every source expected that day, with a status per unit, the files collected and any error. It's the collector's bookkeeping (not raw data) and is rewritten on each run.

**Lock.** Every access holds `raw/<asof>/manifest.json.lock`, an operating-system lock released when the process exits, so it can't go stale (`manifest.locked`).
- A read (`manifest.load`: the derive gate, `ctd check`, a fetch looking up what's stored) locks and releases straight after.
- A write (`manifest.update`) locks before reading and releases after writing, so an entry another process records in between can't be lost. Fetching itself happens outside the lock, so tasks on the same date still download in parallel.
- A lock is tried every second for up to 60 seconds; then `ctd fetch` reports the date as a gap (`source=manifest`; its files are stored and the next run records them) and the derive gate looks again a minute later.
- Writes go to a temporary file swapped in whole, so a crash never leaves a truncated manifest.
- **Why:** four processes adding 25 entries each kept all 100 with the lock and 18 without it.

| Status | Meaning | A gap? |
|---|---|---|
| `ok` | collected (`origin` says how) | no |
| `not_expected` | weekend or holiday on the source's calendar, or nothing published that day (e.g. a past holiday that returned an empty file) | no |
| `manual` | a manual file was dropped at source level; coverage of the units isn't verified | no (warning) |
| `missing` | daily source not attempted yet, or not yet available (Databento before its window is queryable) | yes |
| `manual_needed` | manual file not dropped yet (a daily manual source; none since the CME sources became occasional) | yes |
| `failed` | fetch attempted and failed; retried next run | yes |

Occasional sources are never reported as gaps; manifests written while the CME sources were daily are read by their current schedule (`registry.occasional`). `ctd check` lists gaps and warnings across stored dates and exits 1 if there are any.

### 2.4 Manual files: bookmarklet, inbox, Downloads

The bookmarklet is optional: a free cross-check on Databento, and the only source of SR3 and ZQ.

- **Bookmarklet.** Run from a cmegroup.com tab, it saves the nine futures settlement JSONs and the Section 42 PDF to the browser's Downloads folder as `ctd_<asof>_<source>_<name>`, e.g. `ctd_2026-10-19_cme_fut_ZN.json`. It skips settlements not yet marked Final.
- **When to click:** the settlement pages show five trailing business days, but the bulletin link serves only the latest edition, and its final edition for D arrives late on D+1 (still marked preliminary at 11:20 Eastern on 2026-10-27). So a click for D belongs late on D+1, before D+2's edition replaces it.
- **Ingest** (`ctd ingest`, also the first step of `ctd fetch`) moves those files from Downloads (`CTD_DOWNLOADS` overrides the folder) into `inbox/<asof>/<source>/<name>`, dropping the prefix and any ` (1)` Chrome adds to repeat downloads. It then copies each inbox file into the store and moves the original to `inbox/_ingested/`.
- **Matching a file to a unit:** `inbox/<asof>/<source>/<unit>/<file>` always works. A file directly under the source folder is matched by name (`ZN.json`, `ZN_anything.json`, any case), or goes to the only unit if the source has one. Anything else is stored under `_manual`.
- **Conflicts:** a file whose name is already stored with different bytes stays in the inbox (or in Downloads) and is reported; nothing is overwritten. An identical repeat is just cleared away.
- **Content checks:** a source can check a manual file before it's stored. The Daily Bulletin's is the only one so far: ingest reads the bulletin number, trade date and `FINAL` from page 1 and rejects a bulletin printed for a different date, or not yet final. A rejected file stays in the inbox with the reason.

### 2.5 Calendars and recovery windows

Two business calendars are kept in `src/ctd/reference/data/holidays.csv`: `cme` (CME interest rate settlements) and `sifma` (cash Treasuries; adds Columbus Day and Veterans Day).

- **2016–2025 are derived from the data** by `scripts/derive_holidays.py`.
  - A CME closure is a weekday with no settlements in any of the 15 Databento backfills (nine futures, six option products).
  - A bond-market closure is a weekday with no TreasuryDirect prices or no Treasury par curve (the derived `par_curve` table).
  - Rule-based holiday names label the rows; the data decides them, and each row's `evidence` column says what it rests on (`verified` = `data`). Result: 110 closures, 91 CME and 110 bond market.
  - The data also settles the special cases: CME settled on the Good Fridays of 2021 and 2023 (payrolls) and on the days of mourning 2018-12-05 and 2025-01-09; the bond market closed on 2018-12-05.
  - Re-run the script after a rebuild of the Databento tables; it rewrites only 2016–2025.
  - **Why from the data:** CME publishes no structured archive of past holidays: only each year's schedule, an online Trading Calendar for current dates, and old notices and press releases. Assembling ten years from those would be by hand.
  - **Rejected: a calendar library** (pandas_market_calendars, exchange_calendars). They encode holidays as rules, which is where special closures go wrong (CME settled on the 2018 day of mourning and on the 2021 and 2023 Good Fridays), and would be a new dependency.
- **Good Friday:** TreasuryDirect follows the Federal Reserve and publishes prices on every Good Friday, so it can't tell when the bond market closed. Treasury's par curve can: it is missing exactly on the Good Fridays SIFMA recommended a full close (2024-03-29, 2025-04-18), which the `sifma` calendar therefore closes, and present on the early-close ones (2021, 2023, 2026), which stay open. The NY Fed publishes no SOFR, TGCR or BGCR on any Good Friday, even an early-close one (EFFR it does).
- **2026–27** are hand-entered rows, unverified against the official calendars (`verified` = `n`, except Veterans Day, Thanksgiving and Christmas 2026).
- **The list must reach the year ahead.** Delivery and option expiry dates are computed from the `cme` calendar and raise for a month past the list's last year (design §2).
- A weekday with no settlements anywhere that isn't a holiday is a gap in the feed, not a closure: the script lists them (8 in 2016–2025, each confirmed by Yahoo volume or TreasuryDirect prices), and `ctd derive` lists every product's missing trading days (§9).
- Before 2016, holidays are recognised from the data only: TreasuryDirect returns an empty file, and more than 5 business days later that's recorded as `not_expected`.

A source's recovery window is how many business days after the as-of date it can still be downloaded for that date:

| Source | Window | Consequence |
|---|---|---|
| `cme_fut`, `cme_stir`, `cme_opt` | 4 (CME shows 5 trailing business days) | after that, a missing day is lost (only SR3 and ZQ have no other source) |
| `cme_bulletin` | current bulletin only | CME's link serves only the latest edition (§2.4, §5.9) |
| `databento_daily` | unlimited | any past date can be bought again |
| everything else | unlimited | can be re-fetched for a past date |

## 3. Kinds of source

- **Dated:** the request names the date, so a file covers that date only (TreasuryDirect prices, CME settlements, TCF, NY Fed range, Yahoo window, Databento daily window).
- **History:** each pull returns everything published so far (FiscalData, TreasuryDirect securities, FRED, the par curve year file, the Databento backfills). A file stored under a past as-of date can contain data published later. **Code reading these must filter to dates on or before the as-of date**, or past runs won't reproduce.

## 4. Operations

One scheduled task, `ctd-morning`, collects the previous business day D and derives it. It is registered by `scripts/register_morning_tasks.ps1` and runs `scripts/morning.py` at 09:15 Eastern on weekdays, logging to `data/morning.log`. Its steps run one after another, each its own process; a failed step doesn't stop the later ones, and the task exits 1 if any failed.

| Task | Command |
|---|---|
| 1. Collection | `ctd fetch --catch-up --notify`: every daily source for D, Databento included (queryable from 09:00 Eastern, §5.14). TreasuryDirect's file then has its end-of-day prices (§5.1). `--catch-up` also retries the 4 business days before D. |
| 2. SOFR | `scripts/morning_sofr.py`: only `nyfed_rates`, under today's as-of date, and only once D's SOFR is published, so a file without it can't make a later fetch skip it. Other sources are left out of that manifest, not recorded as missing. |
| 3. Derive | `scripts/morning_derive.py`: `ctd derive --notify` if D's data is stored, otherwise an alert; gated on the data, below. |
| Alerts | `--notify` shows a Windows notification for gaps on dates before the newest one in the run (they survived a retry) and for manual files ingest refused. The newest date's gaps aren't alerted: the next morning's run retries them. The derive step alerts when it skips. |
| CME files (optional) | Click the bookmarklet on a cmegroup.com tab late on D+1 (§2.4), then `ctd ingest` (or leave it for the next morning's run). |
| Check | `ctd check [--from D] [--to D]` |
| One date / one source | `ctd fetch --asof D [--source ID ...]` |
| One-off history | `ctd backfill [--asof D] [--prices-from D]`: par curve years, NY Fed since 2018, every TCF file on CME's FTP, Yahoo histories, and (with `--prices-from`) TreasuryDirect prices by date |
| Rebuild the bookmarklet | `ctd bookmarklet` (after editing `cme_products.toml`) |

Run any command as `& "$env:USERPROFILE\miniconda3\envs\ctd\python.exe" -m ctd.cli <command>`.

### When the morning derive runs

`scripts/morning_derive.py` gates on the **stored data**, not on the earlier steps' exit codes.
- D is the previous `cme` business day. It checks D's manifest for `databento_daily` `ok`, `td_prices` `ok` and not provisional, and `par_curve` `ok`, and that D's SOFR is stored (only when D and today are both `sifma` business days; it's stored under today's as-of date).
- If all are there it runs `ctd derive --notify`.
- Otherwise it doesn't derive: it logs what's missing, raises a desktop alert (`ctd.data.alert`) and exits 1. The derive is rerun by hand (the script with `--asof D`, or `ctd derive`) once the data is in. There's no automatic retry: a missing source usually needs attention first.
- It checks once (`--timeout-minutes 0`, the default): the collection steps are over by the time it runs, so waiting can't bring anything new. A larger `--timeout-minutes` checks again every minute until then, for use by hand.
- On a day that isn't a `cme` business day it does nothing.
- **Why not gate on exit codes:** they can't be trusted. On 2026-10-27 a task reported 0 without running its command, and a derive gated on the tasks ran without D's Databento data.
- **Why one task, steps in order:** separate tasks collide when they start together. After a missed 09:00 start on 2026-10-28 all four morning tasks then in use started at once; both `ctd fetch` runs swept the Downloads folder into the inbox together, one deleted a duplicate download while the other was reading it, and the Databento fetch crashed before pulling D (`collect_downloads` now skips a file another sweep has taken). Two tasks appending to one log also lose the second one's output. Collection had been split only because the main fetch used to run in the evening, before Databento's data was available.

### When the PC is asleep or off

- If the PC is asleep at the scheduled time, the task wakes it (`-WakeToRun`: Task Scheduler's "Wake the computer to run this task"). Windows sets the wake timer 30 seconds before the start; `powercfg /waketimers` lists it. This needs "Allow wake timers" enabled in the power plan (`powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE`). It doesn't work from shutdown, waking from hibernation depends on the hardware, and laptops on battery often ignore wake timers. The task runs only while the user is logged in.
- The power plan on AC sleeps after 30 minutes idle and hibernates 3 hours later, so after an idle night the wake is from hibernation.
- `scripts/morning.py` holds the PC awake while it runs (`SetThreadExecutionState`). After an unattended timer wake, Windows sleeps again after the unattended sleep timeout (2 minutes by default), and a run takes far longer: 18 minutes on 2026-10-29 for one day (1.5 minutes for the public sources, 9 for Databento, 8 for the derive).
- "Run as soon as possible after a missed start" is also on, for when the PC can't be woken. It fires about 15 minutes after wake.
- **Why wake the PC:** on 2026-10-29 the PC was hibernating (sleep 01:09, hibernate 04:09) through the 09:15 start. The missed run started at 10:06, 16 minutes after the PC woke at 09:50, and finished at 10:24.
- Almost every source can be fetched later for a past date (§2.5), so hibernation delays collection rather than losing it, unless the PC is off for more than the 5-business-day catch-up window. The bookmarklet sources don't depend on the schedule.
- **Planned** ([roadmap.md](roadmap.md) 1f.6):
  - add a second trigger at logon, so a missed morning is picked up when the PC is next used;
  - widen `--catch-up` from 5 to 10 business days (`CATCH_UP_DAYS` in `src/ctd/cli.py`), so a week away fills itself in.
- **Rejected for now: an always-on machine** (mini PC, NAS, small cloud server). It guarantees runs but means moving and backing up the store.
- **After a longer absence, by hand:** `ctd fetch --asof <date>` for each missed day, or `ctd backfill`.

## 5. Sources in detail

### 5.1 `td_prices`: TreasuryDirect FedInvest prices

- **What:** one price file per business day covering every marketable Treasury (bills, notes, bonds, TIPS, FRNs), about 460 securities. Rounded clean prices (design §5.1) in two snapshots: buy and sell, and a later end-of-day price.
- **How:** a three-step form flow, each step handing out a CSRF token: GET the date form, POST the date, POST for the CSV. Calendar `sifma`.
- **Date alignment:** the as-of date is the price date requested from FedInvest, and the file holds that day's prices: `raw/2026-10-21/` has the prices for 2026-10-21, the same trade date as the CME settlements stored there (checked by hand on the FedInvest site, 2026-10-22). No one-day shift is needed when pairing them with futures.
- **End of day comes later.** A file pulled the same evening has buy and sell but an empty end-of-day column for every note and bond; a pull a day or more later has all three. End of day is a later snapshot, not the buy/sell midpoint: on 2026-10-16 the 4½% August 2039 bond was 93-19 buy, 93-16 sell, 93-14 end of day. Every stored file before 2026-10-19 was pulled late, so history has end of day throughout. The model uses end of day (design §5.1).
- **Replaced once complete: the one exception to never overwriting (§2.2).** A same-evening file is marked provisional (manifest `"provisional": [file]`). The `--catch-up` run pulls the date again and replaces the file once end-of-day prices are in. A provisional or unreadable download never replaces anything. The meta sidecar keeps the hash, size and timestamps of each version replaced under `"replaced"`. This is safe only because TreasuryDirect serves any past date again. Since the daily fetch moved to 09:00 the next morning, files are rarely provisional.
- **New issues are in CME's basket before they're priced.** CME lists a new note in its TCF the day after its auction (§5.7), but TreasuryDirect has no price for it until it's issued, a few days later. Between the two, a run warns that a basket bond has no TreasuryDirect price (ZNZ6 on 2026-09-25 to 09-29: the 5% Sep-33, 91282CRM5, auctioned 09-24, issued 09-30). Expect it after every auction that adds to a basket; once priced, the new issue usually converts above the CTD.
- **File:** `td_prices/securityprice/securityprice_<asof>.csv`. No header row. Columns:

| # | Column | Example |
|---|---|---|
| 0 | CUSIP | `912810UX4` |
| 1 | Security type | `MARKET BASED BILL` / `NOTE` / `BOND` / `FRN`, `TIPS` |
| 2 | Coupon, decimal | `0.05125` (= 5.125%) |
| 3 | Maturity | `08/15/2046` (MM/DD/YYYY) |
| 4 | Call date | usually blank |
| 5 | Buy | `0.000000` |
| 6 | Sell | `99.989444` |
| 7 | End of day | `0.000000` |

`0.000000` means no price was provided in that column. Bills usually have no buy price, and the end-of-day column is sometimes empty too, so check which column holds a price before using it.

- **History:** past dates can be requested back to **30 May 2008**, but history is only used from 2016 (§1). Until about September 2008 only CUSIP and prices are filled in (type, coupon and maturity are blank); join to security terms on CUSIP. Stored from 2016-01-04; 108 dates from then to 2026-10 had no prices (holidays). The derived `bond_prices` table holds every row of every file (§9).

### 5.2 `td_securities`: TreasuryDirect securities search

- **What:** the terms of every auctioned security, one JSON array per type.
- **How:** `GET https://www.treasurydirect.gov/TA_WS/securities/search?format=json&type=<type>`.
- **Units/files:** `Bill`, `Note`, `Bond`, `CMB`, `TIPS`, `FRN` → `securities_<type>.json`. About 80 MB raw a day (bills alone 55 MB), about 11 MB compressed.
- **Fields:** camelCase strings, e.g. `cusip`, `securityType`, `securityTerm`, `interestRate` (percent, `"5.125"`), `issueDate`, `maturityDate` (`2046-08-15T00:00:00`), `datedDate`, `announcedAsCusip`, `corpusCusip`, plus auction details. One object per auction, so reopenings repeat a CUSIP: `securityTerm` is the term left at that auction (`9-Year 10-Month`), `originalSecurityTerm` the original (`10-Year`). The derived `securities` table reduces them to one row per CUSIP with the first auction's terms, and `security_auctions` keeps one row per auction (§9). `competitiveAuctionCloseDate` is the auction date. A note can be reopened under a shorter term: 146 note CUSIPs have, e.g. 7-year notes reopened as 5-year notes when the maturity and coupon match (91282CGQ8 in February 2025).

### 5.3 `fiscaldata_auctions`: FiscalData auctions

- **What:** Treasury securities auction data, every auction since **31 October 1979** (about 11,000 rows: bills, notes incl. TIPS and FRNs, bonds).
- **How:** `GET https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?format=json&page[size]=10000&page[number]=N`.
- **Files:** `auctions_query_p001.json`, `p002.json`, ... Each holds `data` (rows) and `meta` (`total-count`, `total-pages`).
- **Fields:** 114 per row, all strings, missing values as the string `"null"`. Key ones: `cusip`, `security_type`, `security_term`, `auction_date`, `issue_date`, `maturity_date`, `dated_date`, `first_int_payment_date`, `int_rate` (percent), `reopening` (`Yes`/`No`), `original_issue_date` (filled on reopenings only), `currently_outstanding`, `floating_rate`, `inflation_index_security`.
- **Quirks:**
  - one row per auction, so take one row per CUSIP for security terms;
  - FRNs have no `int_rate`;
  - **includes announced auctions not yet held** (dates after the pull), so filter on `auction_date` ≤ as-of;
  - nothing issued before October 1979, which doesn't matter: every bond deliverable into any of the six contracts since 2008 was issued later.

### 5.4 `par_curve`: Treasury par yield curve and bill rates

- **What:** two of Treasury's daily interest rate tables, one CSV per year:
  - `daily_treasury_yield_curve` (from 1990): `Date, "1 Mo", "1.5 Month", "2 Mo", "3 Mo", "4 Mo", "6 Mo", "1 Yr", "2 Yr", "3 Yr", "5 Yr", "7 Yr", "10 Yr", "20 Yr", "30 Yr"`
  - `daily_treasury_bill_rates` (from 2002): bank discount and coupon-equivalent rates for 4, 6, 8, 13, 17, 26 and 52-week bills.
- **How:** `GET https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/<year>/all?type=<table>&...`. Each yearly file takes about 20 s to arrive.
- **Files:** `<table>_<year>.csv`. Dates are `MM/DD/YYYY`, newest first, yields in percent. The daily pull fetches the current year; `par_curve_backfill` (stored under 2026-10-19) has every earlier year.
- **Derived table:** `par_curve` (§9).
- **Not collected:** the real yield curve and the long-term rate tables (TIPS aren't deliverable; the long-term composites are averages the model doesn't use). Some early pulls still include them.

### 5.5 `fred`: FRED series

- **What:** 13 series, each as its full history: `DGS1MO`, `DGS3MO`, `DGS6MO`, `DGS1`, `DGS2`, `DGS3`, `DGS5`, `DGS7`, `DGS10`, `DGS20`, `DGS30` (CMT yields), `SOFR`, `DFF` (effective fed funds, every calendar day).
- **How:** `GET https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>`. FRED stalls on some user agents (e.g. ones containing "collector"); the collector's is accepted.
- **Files:** `<series>.csv`, columns `observation_date,<series>`, ISO dates, blank where there's no value.
- **Note:** every series duplicates data already collected from its publisher (Treasury, NY Fed); the derived `par_curve` and `rates` tables use FRED as the cross-check, never the source. Kept as a cross-check, and for CMT history before 1990.

### 5.6 `nyfed_rates`: NY Fed reference rates

- **What:** SOFR, TGCR, BGCR (secured) and EFFR (unsecured).
- **How:** `GET https://markets.newyorkfed.org/api/rates/<secured|unsecured>/<rate>/search.json?startDate=...&endDate=...`.
- **Files:** `<rate>_<start>_<end>.json`. The daily pull covers the two weeks ending on the as-of date. A rate for day D is published the next morning, so a run for D takes D's rate from D+1's file (design §3.3); the morning SOFR task stores it (§4). `nyfed_rates_backfill` covers 2018-04-02 onwards.
- **Derived table:** `rates` (§9). `revisionIndicator` is empty on every record stored, and a few early records have `NA` percentiles. No SOFR, TGCR or BGCR is published on Good Friday.
- **Fields** (`refRates[]`): `effectiveDate`, `type`, `percentRate`, `percentPercentile1/25/75/99`, `volumeInBillions`, `revisionIndicator`.

### 5.7 `cme_tcf`: CME Treasury conversion factor tables

- **What:** CME's table of every deliverable CUSIP and its conversion factor, for every listed contract month of every Treasury future. Validation data: the model computes CFs with the formula and rebuilds baskets from the rules (design §2).
- **How:** anonymous FTP, `ftp://ftp.cmegroup.com/settle/TCF/TCF_YYYYMMDD.csv` and `.xlsx`. The CSV is posted around 06:30 on the date in its name, the xlsx around 19:00. The 09:00 fetch the next business day finds both out (at 19:00 the xlsx sometimes wasn't yet: FTP error 550).
- **Could be dropped without issue (kept):** nothing depends on it. The light model reads its basket and CFs from the CSV as a shortcut (design §5.11), but the derived `baskets` table gives the same CUSIPs and CFs for every contract month in every stored file, so it could read that table instead. The xlsx isn't read at all. The files stay as validation of the rules (`ctd derive` fails on a disagreement) and as the record of the day CME lists a new issue.
- **Units/files:** `csv/TCF_<yyyymmdd>.csv`, `xlsx/TCF_<yyyymmdd>.xlsx`, keyed by the date in CME's file name.
- **CSV columns:** `Exch, Period, PFCode, CUSIP, Invoice_Conversion_Factor, Create_Time`, e.g. `CBT,202612,17,912810QU5,0.7182,2026-10-19 11:30:22`. `Period` is the contract month (`YYYYMM`); `PFCode` is CME's clearing code (§6.2). There's no coupon or maturity; join on CUSIP.
- **History:** CSV from 2023-12-11 and xlsx from 2024-03-25; everything on the server is stored. CME also posts files on some of its holidays and on one Saturday (2023-12-09); those 8 weren't stored. The file includes Z3N and TWE, which this project doesn't model. ZN rows reflect the 8-year cap CME applies from the September 2023 contract month (6.58–7.96 years remaining in every month stored); earlier ZN baskets, under the old 10-year cap, aren't covered.
- **Check of the basket rules:** the derived `baskets` table is compared with every stored file (§9): every contract month's CUSIPs and CFs match. CME adds a new issue the morning after its auction (in May 2025 a few days later), before TreasuryDirect prices it (§5.1), and applies the original-term limit per tranche: a 7-year note reopened as a 5-year is listed for ZT and ZF from the reopening (912828Z78, 91282CGQ8). No CUSIP ever leaves a contract month's list.
- **Not known:** how long CME keeps old files. The first one falling about three years back suggests a rolling window, which is why the pull is daily.

### 5.8 `cme_fut` and `cme_stir`: CME futures settlements

- **What:** CME's settlement page data for each product: every listed month, with open, high, low, last, change, settlement, volume and open interest. `cme_fut` holds ZT, ZF, ZN, TN, ZB, UB; `cme_stir` holds SR1, SR3, ZQ.
- **Role:** the record for futures from 2026-10-14 to 10-23; from 2026-10-26 a cross-check on `databento_daily`, and the only source of SR3 and ZQ (design §3.2).
- **How:** the bookmarklet requests `https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/<product_id>/FUT?strategy=DEFAULT&tradeDate=MM/DD/YYYY&pageSize=500` from your browser. Product IDs are in `src/ctd/reference/data/cme_products.toml` (ZT 303, ZF 329, ZN 316, TN 7978, ZB 307, UB 3141, SR1 8463, SR3 8462, ZQ 305), each confirmed against a downloaded file.
- **Files:** `<product>/<product>.json`.
- **Open interest by month** is in every file, so the contract roll ([outputs.md](outputs.md), Tier 2) can be tracked from these pages too; CME's Pace of the Roll would only add the comparison with past rolls.
- **`openInterest` is the previous business day's**, not the trade date's: the page for D equals Databento's open interest for D−1 on every product and day from 2026-10-14 to 10-21 (ZN: 5,781,282 on the 10-15 page is the 10-14 figure). The derived futures table moves it back a day, so a date's open interest arrives with the next day's page. `cme_settlements.FuturesSettle` calls it `prior_open_interest`.
- **`volume` is CME's same-day estimate**, a few percent below the final cleared volume Databento has (ZN on 10-14: 3,772,817 on CME's page, 3,984,228 cleared). Kept as `est_volume`; the derived table has no volume (§9).
- **JSON:** top level `tradeDate` (`10/19/2026`), `reportType` (`Final` once settled; the bookmarklet only saves Final), `updateTime`, `dsHeader` (product name, e.g. `10-Year T-Note Future`), `empty`, and `settlements[]` with `month` (`DEC 26`), `open`, `high`, `low`, `last`, `change`, `settle`, `volume` (with commas), `openInterest`.
- **Price notation** (strings):

| Product | Example | Means |
|---|---|---|
| ZB, UB | `105'13` | 105 + 13/32 |
| ZN, TN | `105'145` | 105 + 14.5/32 (third digit in halves: 0, 5) |
| ZF | `103'312` | 103 + 31.25/32 (third digit in quarters: 0, 2, 5, 7) |
| ZT | `101'296` | 101 + 29.625/32 (third digit in eighths: 0, 1, 2, 3, 5, 6, 7, 8 = 0, ⅛, ¼, ⅜, ½, ⅝, ¾, ⅞) |
| SR1, SR3, ZQ | `96.1100` | decimal |

The third digit is the same code for every product (2 = ¼ and 7 = ¾ for ZF too); `cme_settlements.parse_price` reads all of it.

### 5.9 `cme_bulletin`: Daily Bulletin Section 42 (options)

- **What:** "10YR NOTE, 5YR NOTE, 2YR NOTE AND 30YR BOND OPTIONS", the bulletin section covering options on ZT, ZF, ZN, TN, ZB and UB, every listed expiry (quarterly, serial, weeklies). An option is printed only if it has open interest or volume that day, so many strikes away from the money are missing (UB DEC26 on 2026-10-16: 34 options, against 140 in Databento on 09-15; design §3.1). About 35 pages and 3,200 strike rows a day.
- **Role:** the record for options from 2026-10-16 to 10-23; from 2026-10-26 a cross-check on `databento_daily`, and the only collected source of weekly options.
- **How:** the bookmarklet uses the Section 42 link on CME's Daily Bulletin page (fallback URL in `cme_products.toml`). **CME's link always serves the latest bulletin**, and the final edition for D arrives late on D+1 (§2.4). A bulletin for an earlier date can't be downloaded this way. Ingest checks the trade date printed on page 1 against the as-of date and rejects a mismatch.
- **Files:** `Section42/Section42.pdf`.
- **Layout** (extracts cleanly with pdfplumber or pypdf):
  - The page header gives the bulletin number, trade date and `FINAL` (`PG42 BULLETIN # 201@ ... Mon, Oct 19, 2026`).
  - Each block has a product and put/call header (`10Y NOTE CALL`, or a weekly such as `HYO OPT WK THU`), an expiry label (`DEC26`), one row per strike, then a `TOTAL` line.
  - Strike rows: strike (`1055` = 105.5), open, high, low, close, settlement, change, delta, exercises, volume, open interest, OI change, contract high, contract low.
  - Strike and premium codes differ by product: strikes in quarter-point codes for ZN, ZF, ZB and UB (`1047` = 104.75) and eighths for ZT (`1013` = 101.375); premiums in 64ths for ZN, ZB and UB (`461` = 4-61/64) and halves of 64ths for ZT and ZF (`6035` = 6-03.5). `CAB` is a cabinet settlement, below one tick.
  - Page 1 prints CME's last trade dates per expiry, which `ctd derive` checks against the expiry rule (§9; not for TN).
- **Parser** (`cme_bulletin.parse_options`): reads the standard blocks for ZT, ZF, ZN, ZB and UB and checks each block's volume and open interest against its `TOTAL` line; weeklies stay in the stored PDF but the model doesn't use them (design §2).
- **TN options** are in the bulletin's "ADDITIONAL" section, in one block per expiry (`TN OPT`, then `NOV26 TN OPT (FUTURES SETT. .00)`, `DEC26 (FUTURES SETT. .00)`, ...), with calls and puts mixed and no right marked:
  - premiums are points and 64ths after a dot (`.218` = 2-18/64), the change's sign is stuck to the settlement (`.27-`), and deltas are unsigned;
  - a strike's call and put come in either order (call first in NOV26, put first in DEC26 on 2026-10-21);
  - the parser tells them apart by put-call parity: at a strike with both priced, the futures price is the strike plus or minus their gap, and one value fits the whole chain (or another chain on the same futures, for one with no such strike); below it the dearer row is the call. A lone row is in the money if its delta is over a half;
  - every TN row on 2026-10-16 and 10-19 (247) matches Databento's right, settlement and open interest;
  - TN rows take their expiry from the expiry rule (`refdata.option_expiry`, design §2), since page 1 doesn't list TN.
- **Check:** the 2026-10-16 bulletin has the 100.5 ZN calls at 4-61/64 with delta 1.000 for the November serial (`NOV26`, on December futures, expiring 2026-10-23) and 4-62/64 with delta .972 for the December quarterly (`DEC26`), against December futures at 105-14.5. Databento matches both.

### 5.10 `yahoo_fut`: Yahoo Finance daily bars

- **What:** daily OHLCV bars for the six Treasury futures, a cross-check on CME settlements. On the dates checked, each contract's close equals CME's settlement.
- **How:** `GET https://query1.finance.yahoo.com/v8/finance/chart/<ticker>?interval=1d&period1=..&period2=..`, the endpoint the yfinance library uses, called with a plain request (no browser impersonation); the JSON is stored as received. It's an unofficial endpoint with personal-use terms.
- **Tickers:** contracts as `<product><month code><yy>.CBT` (`ZNZ26.CBT`, month codes H, M, U, Z), and the continuous front month as `<product>=F` (`ZN=F`). Each run tries the next four quarterly contracts and skips any Yahoo doesn't carry (it lacked June 2027 for ZT, ZF, ZN and TN).
- **Files:** daily `<ticker>_<start>_<asof>.json`, covering the 10 days ending on the as-of date (overlapping windows keep files small and cover a missed day). Backfill `<ticker>_history_<asof>.json` under `yahoo_fut_backfill/` on 2026-10-19.
- **JSON:** `chart.result[0]` with `meta` (exchange, currency, `firstTradeDate`, ...), `timestamp[]` (epoch seconds, the session date at 00:00 New York time), and `indicators.quote[0]` with `open`, `high`, `low`, `close`, `volume` arrays (`null` where missing).
- **History stored:**

| Series | From |
|---|---|
| `ZT=F` | 2000-06-02 |
| `ZF=F`, `ZN=F`, `ZB=F` | 2000-09-21 |
| `UB=F` | 2010-01-11 |
| `TN=F` | 2010-10-22 |
| Dec 2026 contracts | March 2026 (listing) |
| Mar 2027 contracts | June 2026 |
| ZB, UB Jun 2027 | 2026-09-22 |

- **Quirks:**
  - Yahoo drops a contract once it expires, so per-contract history exists only for currently listed contracts;
  - the `=F` series stays on the expiring contract until its last trading day (about three weeks after trading moves to the next contract) and isn't adjusted at the roll: never splice it into one price series;
  - volume occasionally repeats the previous day's;
  - a bar for the current session is live until the close; the fetch's default as-of date avoids capturing one;
  - SR1, SR3 and long-dated ZQ have no usable Yahoo data, so they aren't collected.

### 5.11 `databento_fut_backfill`: historical futures settlements (paid, one-off)

- **What:** daily settlement price, open interest and cleared volume for the front two contracts of ZT, ZF, ZN, TN, ZB, UB, SR1, SR3 and ZQ, 2016-01-01 to 2026-10-21. Historical mode reads it for open interest, the roll, and the futures price in vol conversion (design §7).
- **How:** a one-off script (`databento_fut_backfill.py`, not in the repository), on dataset `GLBX.MDP3` with symbols `<product>.c.0` and `<product>.c.1` (`stype_in=continuous`, calendar roll), in three steps: `quote` (free cost estimate), `submit` (one batch job per product, which spends credit; job ids are kept in `data/databento_jobs.json` so nothing is submitted twice) and `collect` (stores finished jobs and the symbology; re-run until nothing is pending). Every step skips what's already stored. It needs `DATABENTO_API_KEY`; the `databento` package is a project dependency, also used to read the stored files. It's not registered in `sources.py`, so `ctd fetch` and `ctd check` don't know about it.
- **Why batch jobs:** a streaming request (`timeseries.get_range`) took 27 minutes for ZT statistics, and ZT's `definition` request had sent 40 KB after an hour, because the server scans the whole ten years either way. ZT statistics was stored from that streaming run; the other products go through batch jobs, and `definition` was dropped in favour of the free symbology lookup.
- **Contents:**
  - `statistics`: one record per published statistic, keyed by `instrument_id`. `stat_type` says which (3 settlement price, 9 open interest, 6 cleared volume, ...), and `ts_ref` gives the trading date it refers to, stamped at midnight UTC: **take its UTC date**; converting to Chicago time first puts every record a day early. Open interest for day D is published the next morning, so the last day has settlements but no open interest; a late-evening figure is often revised the next morning, and the revision (the last published) is what CME's page shows.
  - Settlement `stat_flags` is CME's SettlPriceType bit field: bit 0 set is final (3 = final actual; 2 and 4 are intraday preliminaries from about 14:00 CT, the final comes about 18:00 CT). Each product has 150 finals with no `ts_ref`, sent on Sunday at 11:00 CT: repeats of Friday's final, skipped. On four dates a stray final carries another day's price (TN 2016-02-23, two contracts; UB 2020-03-16, published on the 17th at the 17th's price, 12 points away; ZQ 2016-08-02); the reader keeps the last final published in the date's settlement window (§5.12; `databento.final_settlements`), which equals the preliminary in all four, and notes it.
  - **Instrument ids are reused** (an id is a futures contract for a year, later an option or a spread), so an id is mapped to its symbol on each trading date with the raw-symbol lookup's date ranges, never once for the whole file.
  - Reader: `ctd.data.databento.read_futures`, feeding the derived futures table (§9). For SR1 and ZQ it reads this pull and `databento_stir_backfill` together (§5.13).
  - Symbology (`symbology.resolve`, free): continuous symbol to `instrument_id` by date, then `instrument_id` to contract symbol (`ZTZ6`) by date. Expiries come from the delivery rule (design §2), not from Databento.
- **Files** under `raw/2026-10-22/databento_fut_backfill/<product>/`, with `<end>` exclusive:
  - `<product>_statistics_2016-01-01_2026-10-22.dbn.zst`: the DBN file exactly as received (the batch output file; ZT's is the streamed response). Read with `databento.DBNStore.from_bytes(store.read(...))`. Its header also holds the continuous-symbol to `instrument_id` mapping.
  - `<product>_symbology_continuous_2016-01-01_2026-10-22.json` and `<product>_symbology_raw_symbol_2016-01-01_2026-10-22.json`: the two lookups, as the client's parsed responses re-serialised as JSON, not the HTTP bytes.
  - The meta sidecar records the request (`params`), the client version and, for statistics, `cost_usd` and the batch `job_id`.
- **Check:** ZT on 2026-10-21 matches `cme_fut` exactly (December 101.816406 = 101'261, March 101.644531 = 101'206). Building the derived futures table compares every product on the overlap (2026-10-14 to 10-21): every settlement, contract code and open interest agrees, CME's open interest moved back a day.
- **Coverage:** `c.0` stays on a contract until it expires, so `c.0` and `c.1` cover the expiring contract plus the next one. For SR1, SR3 and ZQ, the front two are the two nearest expiries, serials included.
  - **No final on the last trading day.** A pull holds a record if its id was one of the requested symbols when the record was sent, and the final settlement sent on the evening of a contract's last trading day comes after `c.0` has moved to the next contract (for ZNU6, `c.0` is ZNH7 from 2026-09-22). So no pull holds it: every Treasury contract that expired from March 2016 to September 2026 (43 per product) has no final dated its last trading day. Its settlement that day comes at about 12:01 CT, when the expiring contract stops trading, flagged preliminary (in 2016 also at later times, at the same price). The reader takes a Treasury contract's last preliminary on its last date where it has no final (`databento.last_day_settlements`), and notes it.
    - **Why:** the preliminary is the contract's final price: for all 258 contracts it equals Yahoo's front-month close that day (§5.10), which equals the Databento final on every other day checked (ZN, TN, ZB and UB, 2016 to 2026-10-19) but four (2024-11-26 TN, 2025-02-03 ZB, 2025-08-01 ZN and ZB). Not for SR1, SR3 and ZQ, whose final settlement is set after the last trading day from the month's rates.
    - On 44 of the 172 ZN, TN, ZB and UB last trading days, the evening's finals for the contract after next also come through `c.1`, so the table has three rows that day.
  - **No third Treasury contract.** The model needs option volatility no more than 3 months out, and those options are on the front two futures (every chain within 60 days of expiry has its futures price). Deferred option months, on the third contract, lack a futures price before 2026-10-14; the quality table checks them against the other chains on the same futures instead (§9).
  - **SR1 and ZQ are the exception:** the repo strip needs about the front six months for a horizon up to five months out, so their 3rd to 8th months were bought separately (§5.13).
- **History-type file:** it holds every date up to the pull, so code reading it for a past as-of date must filter to trading dates on or before it (§3).

### 5.12 `databento_opt_backfill`: historical option settlements (paid, one-off)

- **What:** every standard (quarterly and serial) option on ZT, ZF, ZN, TN, ZB and UB futures, 2016-01-01 to 2026-10-19: definitions (symbol, strike, expiry, underlying) and statistics (settlement price, open interest, volume). Historical mode reads it for option-implied probabilities and vol (design §7).
- **How:** a one-off script (`databento_opt_backfill.py`, not in the repository), dataset `GLBX.MDP3`, parent symbols `OZT.OPT`, `OZF.OPT`, `OZN.OPT`, `OTN.OPT`, `OZB.OPT`, `OUB.OPT` (`stype_in=parent`; weeklies are separate Globex products and aren't requested), schemas `definition` and `statistics`. Same steps as §5.11 (`quote`, `submit`, `collect`, plus `inspect`); job ids in `data/databento_opt_jobs.json`.
- **Files** under `raw/2026-10-22/databento_opt_backfill/<product>/`, `<end>` exclusive: `<product>_definition_2016-01-01_2026-10-20.dbn.zst` and `<product>_statistics_2016-01-01_2026-10-20.dbn.zst`, about 7.6 GB stored in all (ZN statistics 2.1 GB, ZB 2.0 GB). ZN also has a small test pull for 2026-10-16 to 10-20.
- **Reading:**
  - The files are too big to load whole (ZB's definitions alone ran out of memory); read in chunks (`DBNStore.to_ndarray(count=...)`; `from_bytes` keeps the compressed bytes and decompresses as it goes) and filter as you go.
  - Keep instrument classes `C` and `P` (the others are user-defined spreads with no underlying).
  - Symbols are `OZNZ6 C1005`: option month code (`Z6` = DEC26, not the futures month), right, strike code; `strike_price` is the decimal strike and settlement prices are decimal.
  - Settlement is `stat_type` 3 (the final one comes after the preliminary), cleared volume 6, open interest 9; `ts_ref` is the trading date (its UTC date, as in §5.11).
  - `expiration` in the definitions is the last trading moment as a UTC timestamp (16:00 CT): convert it to Chicago time before taking the date.
  - Open interest for day D is published the next morning, so 2026-10-19 has settlements but no open interest.
  - Reader: `ctd.data.databento.read_options` (ZT: 1.8 million rows in 15 s, 2.3 GB peak), feeding the derived options table (§9).
- **Definitions** are re-sent every day for every instrument (for ZN about 1,500 calls and puts and 13,000 spreads a day), and a strike listed during the day is defined then. Instrument ids are reused, so each settlement is matched to the contract its id stood for on that date: the latest definition sent by the end of the trading date, within a week of that contract's last re-send. Settlements that match no call or put are skipped (ZT: 12,068): mostly 0.0 or absurd values, plus reference settlements dated the day before a new strike's first definition.
- **Settlement flags:** finals are 3 ("actual") or 1. **Neither says whether the option traded:** 92–99% of finals each year since 2017 are 3, traded or not (every ZN DEC26 final on 2026-10-16, 190 of them with no volume), and the 1s follow a monthly cycle (2016: 32% are 1). Whether an option traded that day is its cleared volume (design §3.1).
  - On 3,700 to 6,400 date/instrument pairs per product (0.2 to 0.3%) the finals disagree: the previous evening's final tagged with the next date (ZT on 2016-01-06), or a wrong batch corrected later the same evening (ZT on 2016-08-22: every option at 0.0005 at 18:19 CT, corrected at 22:35).
  - The reader (`databento.final_settlements`, also used for futures) keeps the final equal to the date's preliminary (about 80% of these pairs); failing that, the last one published in the settlement window, 11:00 CT on the date to 11:00 CT the next weekday; failing that (0 to 8 per product), the last one.
  - The preliminary comes first because the window doesn't know holidays: ZN on Friday 2017-05-26 has a stray 0.0 on Sunday and the real final on Memorial Day evening. Where there is no preliminary, the window's pick is also the last one published (checked on ZN and ZB).
- **Cabinets** are 0.001, except ZT's 0.0005 ($1 a contract on $200,000 face), **from 2017-05-19 on, for all six products. Before that they are 0.0** (384,583 rows; every one out of the money against its own chain's at-the-money strike), and the reader stores them as cabinets. From 2017-05-19 a 0.0 is a placeholder (36,586 rows: never any open interest, mostly deferred months, some deep in the money) and is skipped.
- **No volume or open interest is 0.** Databento publishes neither for an option with no trades and no open interest (the strikes the bulletin leaves out: all null on 2026-10-16), and the two are always missing together. The reader stores 0, except after the last date each was published (the pull's last date, 2026-10-19, whose figures came the next morning): null.
- **Gaps in the feed:** some dates have only part of the chain, and the build notes every date with under half the usual count (8 to 16 per product).
  - Common to most products: 2021-12-24, 2024-11-26, 2025-01-09, 2025-01-13 (under 10% of the chain), 2025-08-01, and near-empty 2020-02-27, 2020-06-30 and 2022-04-15 (Good Friday).
  - Some trading days are missing entirely: 8 from every Databento backfill (2016-03-18, 2020-02-27, 2020-06-30, 2022-01-21, 2022-03-08, 2024-11-25, 2025-06-17, 2025-06-20) and a few more from single products. `ctd derive` lists each product's missing trading days against the `cme` calendar (`missing_days` in `_build.json`): 5 to 13 per product.
  - Holidays such as 2025-07-04 carry a handful of rows. They stay gaps (design §3.2); the few settlements dated on a weekend (ZB: 8, e.g. 2024-02-18; ZN: 2) are dropped.
- **Sunday finals for a Friday:** CME republishes Friday's finals on Sunday at about 11:00 CT, and for some options that is the only final (on a typical Friday 12% of ZN and ZB options, 26% of TN's). Usually they are right, but on some Fridays they aren't:
  - TN on 2018-08-24, every option Sunday-only, has its at-the-money straddle 65% richer than Thursday's and Monday's with the futures unchanged (also 2017-11-24, 2020-11-20);
  - ZB, UB and TN deferred months break put-call parity against the futures on 10 to 25 Fridays (ZB on 2020-03-20: ZBU0 options imply 175.56, its futures settled 173.53, both finals only from Sunday).

  The raw records don't tell a good Sunday final from a stale one, so the reader keeps them, and the derived `options_quality` table flags the chains whose prices give them away (§9).
- **Audit (2016 to 2026-10-15, all six products):**
  - no duplicate keys;
  - every expiry (837 option months, FEB16 on, all six products, Databento and bulletin) equals the CBOT rule (`reference.options.rule_expiry`) on the `cme` calendar, which also confirms the holidays derived for 2016–2025 (§2.5);
  - put-call parity near the money holds to 0.006 to 0.008 points (ZT, ZF, ZN; standard deviation) and 0.03 to 0.08 (TN, ZB, UB, with the Friday outliers above);
  - strike-order violations of a tick or two and a few hundred deep in-the-money prices below intrinsic per product (TN more: 13,117 strike-order violations, mostly on those Fridays);
  - an option month has no settlement on its own expiry day, and deferred months aren't settled every day early in their life.
- **Overlap with the bulletin** (built into the derived options table, 2026-10-16 and 10-19, all six products): every bulletin row is in Databento, and none of the 3,527 differs in expiry, underlying month, settlement, cabinet, volume or open interest (compared where both have a value: Databento publishes no volume or open interest where the bulletin prints 0). So Databento's cleared volume is the bulletin's volume, and ZT's cabinet is 0.0005. Databento also settles strikes the bulletin leaves out, about 860 ZN and 550 ZB options a day.
- **History-type file:** filter to trading dates on or before the as-of date (§3).

### 5.13 `databento_stir_backfill`: SR1 and ZQ months 3 to 8 (paid, one-off)

- **What:** daily settlement price, open interest and cleared volume for the 3rd to 8th listed months of SR1 (from its listing in April 2018) and ZQ (from 2016), through 2026-10-22. With the front two from §5.11, that's the front eight months: enough for the repo strip to a horizon up to five months out (design §5.3). ZQ is for before May 2018, when there is no SR1 or SOFR, and for testing ZQ against SR1 where both exist. Pulled 2026-10-26 for $0.08.
- **How:** a one-off script (`databento_stir_backfill.py`, not in the repository, so the request is recorded here and in each file's meta sidecar), with the same three steps as §5.11 (`quote`, `submit`, `collect`; each skips what's stored). It needs `DATABENTO_API_KEY`, set as a Windows user variable; shells started before it was set don't see it.
  - **Statistics:** one batch job per product (`batch.submit_job`): dataset `GLBX.MDP3`, schema `statistics`, symbols `<product>.c.2` to `<product>.c.7` (`stype_in=continuous`, calendar roll; `stype_out=instrument_id`), start 2016-01-01, end 2026-10-24 (exclusive), one zstd DBN file (`split_duration=none`). Jobs `GLBX-20261026-63FNL9XRXN` (SR1) and `GLBX-20261026-7TDXXRTAN3` (ZQ), ids in `data/databento_stir_jobs.json`. Each file is stored byte for byte, its sha256 checked against the job's file listing. The job records carry no cost (`cost_usd` is null in the job ids file and the sidecars).
  - **Symbology** (free, `symbology.resolve`, same date range): the six continuous symbols to instrument ids by date, then every id returned to its contract symbol by date. Stored as the client's parsed responses re-serialised as JSON.
- **Files** under `raw/2026-10-26/databento_stir_backfill/<product>/`, `<end>` exclusive (the last trading date in them is 2026-10-22: Friday's finals weren't published yet): `<product>_c2-c7_statistics_2016-01-01_2026-10-24.dbn.zst`, `<product>_c2-c7_symbology_raw_symbol_2016-01-01_2026-10-24.json` and `<product>_c2-c7_symbology_continuous_2016-01-01_2026-10-24.json`.
- **One source with §5.11.** The derived futures table picks one source per date and product, so `read_futures` reads both pulls as `databento_fut_backfill` and the rows carry that label. The month tells which pull a row came from.
- **A pull holds a record if its id was one of the requested symbols when the record was published**, not on the trading date it refers to. Near a roll, one date's records are split between the pulls: SR1Q8's final for Friday 2018-06-29 was sent on Sunday 07-01, after its id moved from `c.2` to `c.1`, so it's in §5.11's pull, with that day's preliminaries in this one; open interest, published the next morning, crosses the same way. So the reader joins both pulls' records and the two raw-symbol lookups (`merge_symbology`, which raises if they ever give an id two symbols at once) before picking finals. Joined, every row the front-two pull gave before is unchanged.
- **Placeholders:** a final of 0.0 dated while its id was still another instrument, before the contract was listed (SR1M9 on 2018-11-16, its id then a CAD option; 4 in SR1, none in ZQ), is skipped and noted. Any other final on an id that isn't the product's futures that day still raises.
- **Coverage:** eight months on almost every business day; seven on about 370 SR1 dates (most in 2018 and 2019, when fewer months were listed; the rest month-ends) and on about 50 ZQ dates (month-ends). The feed gaps are those of §5.11 and §5.12: no rows on 2020-06-30, 2022-01-21, 2022-03-08, 2024-11-25, 2025-06-17 and 2025-06-20 (also 2016-03-18 and 2020-02-27 for ZQ; 2025-01-13 for SR1), and only one or two months on 2024-11-26, 2025-01-09, 2025-08-01 (and 2025-01-13 for ZQ). They stay gaps (design §3.2).
- **In the derived layer:** only the `continuous` lookup isn't read; it's kept as received, and records which id was which `c.k` when.
- **Check:** in the derived futures table, every month on 2026-10-14 to 10-22 agrees with `cme_stir` (settlement, contract code and open interest).
- **Used by the model:** runs read SR1 from the derived futures table (design §4), so the repo strip covers past dates back to May 2018. ZQ isn't used yet (design §7).

### 5.14 `databento_daily`: daily CME futures and options (paid)

- **What:** the record for CME futures and option settlements from 2026-10-26 (design §3.2). Units:
  - futures `ZT`, `ZF`, `ZN`, `TN`, `ZB`, `UB` (front two contracts, `<P>.c.0` and `c.1`) and `SR1` (`c.0` to `c.6`), `stype_in=continuous`;
  - options `OZT`, `OZF`, `OZN`, `OTN`, `OZB`, `OUB` (`O<P>.OPT`, `stype_in=parent`; weeklies are separate Globex products and aren't included).
  - No SR3 or ZQ (design §3.2). Fetcher: `ctd.data.databento_daily`; needs `DATABENTO_API_KEY`.
- **Window:** 00:00 Chicago time on D to 00:00 on the next `cme` business day, so each record is in exactly one file. Friday's window runs to Monday and holds the Sunday finals; a date's revised open interest (about 09:05 CT the next day) is in the next date's file.
- **When it's available.** Without a CME licence, Databento's historical API stops at a rolling cutoff about 8 hours behind real time (requests past it return `422 dataset_unavailable_range`, "requires a subscription and/or license"). Measured on ZBZ6, 2026-10-20 to 10-26 (Chicago time):

| Record for trade date D | Sent | Queryable from |
|---|---|---|
| Preliminary settlement (`stat_flags` 2) | 14:00 D | 22:00 D |
| Final settlement (3), Monday to Thursday | about 18:15 D | about 02:15 D+1 |
| Final settlement, Friday | Sunday 06:37 (none on Friday evening) | Sunday about 14:40 |
| Open interest and cleared volume, first figure | 20:15 to 21:30 D | by about 05:30 D+1 |
| Open interest, revised (what CME's page shows) | about 09:05 D+1 | about 17:05 D+1 |

  A day's window ends at 00:00 Chicago time, which is queryable at exactly 09:00 Eastern (both cities change clocks together), hence the 09:15 task.
- **Fetch rules:**
  - The fetch requests nothing until `metadata.get_dataset_range` passes the window's end and `get_dataset_condition` lists each of the window's dates (Friday to Sunday for a Friday) as `available` or `degraded`; a `degraded` date is stored with a note on the unit's manifest entry (`notes`).
  - A pull with no final settlement or open interest on any futures contract, or no option finals, isn't stored.
  - Each such case is a gap retried by the next run (§4).
- **Files** under `raw/<D>/databento_daily/<unit>/`:
  - `<unit>_statistics_<D>.dbn.zst`: the DBN stream as received;
  - `<unit>_symbology_raw_symbol_<D>.json`: the free id-to-symbol lookup for D, the client's parsed response;
  - option units add `<unit>_definition_<D>.dbn.zst`: the whole window's definitions on the unit's first date, then only the calls and puts whose (instrument id, raw symbol) pair no earlier definitions file holds, requested by id (ids are reused, so the pair is the key). A day with no new strikes has none.
  - Each sidecar records the request and its quoted `cost_usd`.
- **Cost** (free quotes, one session, 2026-10-23):
  - option statistics (six products, all months) 15 MB, $0.014;
  - full option definitions 72 MB, $0.113, almost all user-defined spreads;
  - futures statistics, nine products' full parents, 2 MB, $0.002, against $0.0001 for the narrow pull above.

  So statistics plus definitions for new instruments only cost about $4 a year, against about $35 with full definitions daily. Futures need no definitions (symbology and `reference/`, as in the backfill). The first pull, 2026-10-26, cost $0.037 for all 13 units.
- **Reading:** `databento.read_daily_futures` and `read_daily_options` (one date and unit: the date's records from its own file and the next business day's, the revised open interest coming from the latter), into the derived futures and options tables, where it wins from 2026-10-26 (§9).
  - The futures pull asks for the same continuous symbols as the backfill, so a contract's last trading day has no final here either, and the reader takes its preliminary (§5.11, Coverage). The completeness check passes that day on the next two contracts' finals.
- **Gotcha:** `timeseries.get_range` with a date-only `start` and no `end` stops at the end of that day, not at the latest data. Always pass `end`.

### 5.15 Occasional and legacy

- **`cme_opt`:** CME's per-product option settlement files (an expiry list plus one JSON per option series). Only used if automated CME access ever works.
- **`cme_cf`** (2026-10-16 only): the conversion factor spreadsheet downloaded by hand before the FTP source existed. The source no longer exists; the FTP file for that date is under `cme_tcf`.

## 6. Identifiers and joins

### 6.1 Securities: CUSIP

CUSIP is the key for every bond-level dataset. All identifiers were checked on 2026-10-20: every one is 9 characters with a valid check digit, with no case or whitespace problems.

| Dataset | Field | Distinct CUSIPs (2026-10-20) |
|---|---|---|
| FiscalData auctions | `cusip` | 5,099 |
| TreasuryDirect securities | `cusip` | 5,099 (the same set) |
| TreasuryDirect prices (2016 →) | column 0 | 2,098, all found in both of the above |
| CME TCF (2023 →) | `CUSIP` | 364, all found in both of the above |

Coupon and maturity agree for every shared CUSIP. The usual route:

```
TCF (contract month, CUSIP, CF) ─┐
TreasuryDirect prices (CUSIP, price) ─┼── CUSIP ──► FiscalData / TreasuryDirect securities (coupon, maturity, dated date, first coupon)
```

When joining:
- FiscalData and TreasuryDirect securities have one row per **auction**; reduce to one row per CUSIP (reopenings keep CUSIP, coupon and maturity).
- Coupons are decimal in the prices file (`0.05125`) and percent elsewhere (`5.125`).
- The par curve, FRED and NY Fed data have no security identifiers; they're keyed by date and tenor or rate name.

### 6.2 Contracts

Each source names a futures contract differently. ZN December 2026:

| Source | Contract | Month |
|---|---|---|
| Reference data / CLI | `ZN` | `ZNZ6` |
| TCF | `PFCode` `21` | `Period` `202612` |
| CME settlement JSON | product ID `316`, `dsHeader` `10-Year T-Note Future` | `month` `DEC 26` |
| Section 42 bulletin | header `10Y NOTE CALL` / `PUT` | expiry `DEC26` |
| Databento | `ZN.c.0` (continuous), `ZNZ6` (raw symbol); options `OZN.OPT`, `OZNZ6 C1005` | in the symbol |
| Yahoo | `ZNZ26.CBT` (contract), `ZN=F` (front month) | in the ticker |

TCF clearing codes, inferred from the maturities of each code's deliverables:

| PFCode | `26` | `25` | `21` | `TN` | `17` | `UBE` | `3YR` | `TWE` |
|---|---|---|---|---|---|---|---|---|
| Contract | ZT | ZF | ZN | TN | ZB | UB | Z3N (not modelled) | TWE (not modelled) |

They're stored as `clearing_code` in `src/ctd/reference/data/cme_products.toml`, next to each contract's product ID, so every CME source maps to one contract record.

### 6.3 Dates and times

| Source | Format |
|---|---|
| Store paths, manifests, FiscalData, FRED, NY Fed | `YYYY-MM-DD` |
| TreasuryDirect prices, par curve, CME `tradeDate` | `MM/DD/YYYY` |
| TreasuryDirect securities | `YYYY-MM-DDT00:00:00` |
| TCF `Period` | `YYYYMM`; file names `YYYYMMDD` |
| CME settlement month | `DEC 26`; bulletin `DEC26` |
| Databento `ts_ref` | midnight UTC of the trading date; take the UTC date (§5.11) |
| Yahoo | epoch seconds (session date, 00:00 New York) |
| Metadata timestamps (`stored_at`, `downloaded_at`) | UTC, `YYYY-MM-DDTHH:MM:SSZ` |

## 7. Reading the data

The model reads only from the store, never from the network (design §3). Runs read the derived tables (§9); the raw store is read through `RawStore`:

```python
from datetime import date
from ctd.data.store import RawStore
from ctd.data import manifest

store = RawStore("data")
asof = date(2026, 10, 19)
store.units(asof, "td_securities")                       # ['Bill', 'Bond', 'CMB', 'FRN', 'Note', 'TIPS']
store.names(asof, "cme_tcf", "csv")                      # ['TCF_20261019.csv']
raw = store.read(asof, "cme_tcf", "csv", "TCF_20261019.csv")   # original bytes (decompressed)
meta = store.meta(asof, "cme_tcf", "csv", "TCF_20261019.csv")  # sidecar dict
manifest.load(store, asof)["sources"]["cme_tcf"]["status"]       # 'ok'
```

For a reproducible run on a past date (design §3.3):
- read only data dated on or before it;
- filter history-type files (FiscalData, TreasuryDirect securities, FRED, par curve, the Databento backfills) to observations on or before it;
- for FiscalData, keep only auctions held by then.

## 8. Known issues and open items

- **ZN grade before September 2023** can't be validated against TCF files, which start in December 2023 (§5.7).
- **Missing bulletins for 2026-10-14 and 2026-10-15.** They were downloaded after 10-19's was published, so CME served 10-19's; those copies were deleted. Options for those dates come from the Databento backfill, which runs to 10-19. Ingest now rejects a bulletin printed for another date.
- **Options for 2026-10-20 to 10-23** come from the bulletin only, which omits strikes with no open interest or volume (§1, Which source covers which dates).
- **SR3 and ZQ** are collected only on bookmarklet days after 2026-10-21; Databento can backfill them if needed.
- **Holiday calendar:** 2016–2025 derived from the data (§2.5); 2026–27 hand-entered and mostly unverified; before 2016 inferred from empty TreasuryDirect files.
- **TCF holiday files:** 8 files dated on CME holidays or a weekend weren't stored.
- **TCF retention** on CME's FTP is unknown.
- **FRED** duplicates Treasury and NY Fed data; kept for now.
- **Yahoo** is an unofficial endpoint and may change or stop without notice.
- **Not collected yet:** the sources [outputs.md](outputs.md) needs for the fragility dashboard and the roll view:
  - CFTC Traders in Financial Futures, futures only (Socrata dataset `gpe5-46if`): weekly asset-manager and leveraged-fund positions;
  - Monthly Statement of the Public Debt (FiscalData): amount outstanding and stripped by CUSIP;
  - NY Fed SOMA holdings by CUSIP (weekly);
  - Treasury buyback results;
  - CME Pace of the Roll (open-questions.md).

  All but Pace of the Roll have free history, so they can be added and backfilled when the dashboard is built (design §3.2).

## 9. Derived tables

Parquet tables built from the raw store by `ctd derive`, one per kind of data, in one schema whatever the source. The rules (precedence, staging, incremental builds, format) are in design §4; this section is the catalogue. Read them with `DerivedStore.read(table, products, start, end)`.

- **Precedence by date** is in §1, Which source covers which dates. Each build compares the sources where they overlap (`overlap` in `_build.json`, disagreements printed).
- **Missing trading days:** each build lists every product's days on the `cme` calendar between its first and last date with no rows (`missing_days` in `_build.json`), so a skipped date needs no diagnosis.
- **History-type sources** (Treasury's par-curve year files, FRED, and the NY Fed's overlapping windows) take each value from the latest pull, and each build notes any value a newer pull changes.
  - **Why:** keeping each value as known on each as-of date would match the reproducibility rule more strictly, but nothing has been revised: across the stored pulls (to 2026-10-25), 175,990 repeated FRED values and 5,684 par-curve values are unchanged, and the NY Fed's revision flag is empty on all 8,852 records since 2018. The build's revision notes would show a change. If revisions start, revisit.

| Table | One row per | Columns and notes |
|---|---|---|
| `options` | date, product, option month (`label`), right, strike | `expiry` (last trading day, as the source states it), `underlying_month`, `settle` (null for a cabinet), `cabinet`, `volume`, `open_interest`, `source`. Databento also settles strikes the bulletin leaves out (about twice as many rows a day). Every build checks each option month's `expiry` against the expiry rule (design §2) and fails on a disagreement; months past the holiday list are listed, not checked. |
| `futures` | date, product, contract month | `contract` (`ZNZ6`), `settle`, `open_interest` (at the close of `asof`), `source`, for the six Treasury futures and SR1, SR3, ZQ. Treasury futures: front two contracts; SR1 and ZQ: front eight months in history (§5.13). Every build checks that each expired ZN, TN, ZB and UB contract's last row is on its last trading day (the delivery rule, design §2) and fails on a disagreement. |
| `options_quality` | option chain (date, product, option month) | Checks, each a column and, on failure, a name in `issues`. Skip a chain where `ok` is false. Detail below. |
| `bond_prices` | date, CUSIP | Every security type in the TreasuryDirect file, 2016 on (partitioned by `type` and year): `coupon`, `maturity`, `call_date`, all three prices as published (`buy`, `sell`, `eod`; null where TreasuryDirect gives 0), and `provisional`. Which price a step uses is its own choice (design §5.1); the table reproduces `td_prices.read` exactly. Missing days are checked on the `sifma` calendar, which for 2016–2025 was derived from these same files, so the check bites only from 2026. |
| `securities` | CUSIP | The first auction's `original_term` (`10-Year` for a reopened note, which ZN's original-maturity rule needs), `dated_date`, `original_issue_date`, plus `coupon`, `maturity`, `last_issue_date`, `auctions` and the callable, TIPS and floating flags. A single file, rebuilt when a newer pull of the terms is stored (terms don't change once issued, so a newer pull only adds CUSIPs). Every priced CUSIP is in it, with the same coupon and maturity. |
| `security_auctions` | auction | Per-tranche terms, for original-term limits applied per tranche (design §2). |
| `par_curve` | date (1990 on) | A column per tenor (`y_1m` … `y_30y`, decimals), from Treasury's year files; FRED's CMT series are a second source that never wins (they agree on all 97,450 shared values). |
| `rates` | date, rate (SOFR, TGCR, BGCR, EFFR; 2018 on) | Rate, percentiles, volume, and EFFR's target range, from the NY Fed; FRED's SOFR and fed funds as the cross-check. Missing days checked on the `sifma` calendar. |
| `baskets` | contract month, CUSIP (all six contracts, quarterly from March 2016) | Rebuilt from the grade records and the security terms, with the CF from the formula and `eligible_from` (the auction that makes a bond deliverable); the basket on a date is the rows with `eligible_from` before it. Every build checks it against every stored TCF file: membership and CF agree for all 89 contract months CME lists, except four new issues CME listed a few days late in May 2025 (`cme_late`). A disagreement fails `ctd derive`. Rebuilt when the securities, grades, product records or TCF files change. |

**Columns left out on purpose:**
- **No option delta.** CBOT Treasury options are American and CME's deltas come from its own model; a Black-76 delta from the settlement-implied vol is close enough for anything the model does, and consistent with it. Databento has no delta, so the column would be null before 2026-10-16 anyway. The bulletin PDFs keep CME's for a check.
- **No futures volume.** CME's page has a same-day estimate, Databento the final cleared volume: different quantities, so one column with a precedence rule would mix them. Nothing in the model uses it; both stay in the raw store.

**`options_quality` checks** (`data/derived/quality.py`), built from the options and futures tables whenever either changes:
- `stale`: the at-the-money straddle scaled by √(days to expiry) jumping away from neighbouring days that agree with each other (a real volatility move persists and isn't flagged);
- `parity`: near-the-money call minus put against futures minus strike, beyond 4/32;
- `forward`: the futures price a chain implies by parity, against the other chains on the same futures that day, beyond 4/32 (needs no futures settlement, so it covers the deferred months the futures backfill lacks);
- `order`: calls rising or puts falling with strike at two or more strikes.

They catch the stale Sunday republications of Friday finals (§5.12): every TN chain on 2017-11-24, 2018-08-24 and 2020-11-20, and the deferred ZB and UB chains breaking parity. Flagged: 0.1% of chains for ZN, ZF and ZT, 0.4% ZB, 1.6% UB, 3.8% TN, mostly Fridays. TN's next chain was flagged on 6 of its 42 run-window start Fridays, which can cost a contract's first day (design §7).
