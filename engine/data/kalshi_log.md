# Kalshi Week 2 2026 prop-ladder pull — fetch log

Pulled 2026-09-15 via WebFetch only. Endpoint:
`https://api.elections.kalshi.com/trade-api/v2/markets?event_ticker=<EVENT>&status=open&limit=35[&cursor=...]`

## Two deviations from the brief (both forced by the live API)

**1. `limit=200` does not work through WebFetch.** WebFetch converts the response to
markdown and truncates it. At `limit=200` the JSON was cut off mid-object after ~45
markets, silently losing the rest. Verified by asking the fetch to report whether the
content ended inside an incomplete object: it did. `limit=35` returns complete JSON, so
every event was paged at `limit=35` following the top-level `cursor` until `cursor` was
empty. This is why each row below may list several URLs.

**2. There are no integer-cent fields in this API version.** The brief assumed
`yes_bid`/`yes_ask`/`last_price`/`volume`/`open_interest` as integers 0-100. A full key
dump of a market object returned **only** these:

```
last_price_dollars, no_ask_dollars, no_bid_dollars, notional_value_dollars,
open_interest_fp, previous_price_dollars, previous_yes_ask_dollars,
previous_yes_bid_dollars, volume_24h_fp, volume_fp, yes_ask_dollars,
yes_ask_size_fp, yes_bid_dollars, yes_bid_size_fp, ...
```

No `yes_bid`, no `volume`, no `open_interest`. So the CSV columns are populated as:

| CSV column | source JSON field | format |
|---|---|---|
| `yes_bid` | `yes_bid_dollars` | dollar string, e.g. `0.0100` = 1 cent |
| `yes_ask` | `yes_ask_dollars` | dollar string |
| `last_price` | `last_price_dollars` | dollar string |
| `volume` | `volume_fp` | fixed-point string, e.g. `25.88` |
| `open_interest` | `open_interest_fp` | fixed-point string |

**Values are copied verbatim; nothing was computed or converted.** Downstream code that
expects 0-100 integers must multiply the price columns by 100.

## A note on the MARKETCOUNT figures below

The verbatim prompt asks the fetch model to self-report `MARKETCOUNT`. That self-count is
unreliable — on several pages it reported `36` for a page capped at `limit=35`, which is
impossible. The authoritative number is the count of market lines actually enumerated and
parsed. Both are given; where they disagree it is a miscount by the summarizer, not
missing data, and the enumerated tickers were checked for duplicates (none found).

---

## Series ticker resolution

| Stat | Ticker used | Notes |
|---|---|---|
| Receptions | `KXNFLREC` | "Pro Football Player Receptions" |
| Receiving yards | `KXNFLRECYDS` | |
| **Rushing yards** | **`KXNFLRSHYDS`** | "Pro Football Rushing Yards", scope `Rushing`. See below. |
| Passing yards | `KXNFLPASSYDS` | |
| Passing TDs | `KXNFLPASSTDS` | |
| Anytime TD | **`KXNFLTD`** | "Pro Football Touchdowns". `-1` strike = anytime TD. |

### Rushing yards — found
The brief's three guesses were all wrong:
- `KXNFLRUSHYDS` → **404** (series does not exist)
- `KXNFLRUSHING` → event query returned empty
- `KXNFLRUSHYD` → event query returned empty
- `KXNFLRUSH` → **404**

The real ticker is **`KXNFLRSHYDS`** (RSH, no `U`). Confirmed via
`/trade-api/v2/series/KXNFLRSHYDS`: title "Pro Football Rushing Yards",
`product_metadata.scope = "Rushing"`. It has a full Week-2 ladder for DET@BUF.

Related series that also exist, for reference: `KXNFLRRYDS` (Rush + Receiving Yards,
has DET@BUF markets), `KXNFLRSHATT` (Rushing Attempts), `KXNFLLONGRSH` (Longest Rush).

### Anytime TD — `KXNFLGAMETD` is the wrong ticker
`KXNFLGAMETD` exists as a series but its **only** event is `KXNFLGAMETD-26FEB08SEANE`
(the Super Bowl). `KXNFLGAMETD-26SEP17DETBUF` returned 0 markets. The weekly
anytime-TD series is `KXNFLTD`.

---

## Per (game, series) results

### DET @ BUF — Thursday, event suffix `26SEP17DETBUF`

| Series | URLs | MARKETCOUNT reported | Rows written | Agree? |
|---|---|---|---|---|
| KXNFLREC | 3 pages (base + 2 cursors) | 34 + 36 + 10 = 80 | 80 | yes |
| KXNFLRECYDS | 3 pages | 36 + 35 + 27 = 98 | 96 | **no — see below** |
| KXNFLRSHYDS | 2 pages | 36 + 2 = 38 | 37 | **no — see below** |
| KXNFLPASSYDS | 1 page | 18 | 18 | yes |
| KXNFLPASSTDS | 1 page | 10 | 10 | yes |
| KXNFLTD | 2 pages | 36 + 8 = 44 | 43 | **no — see below** |

**Disagreements, stated explicitly:**
- `KXNFLRECYDS` reported 98 total, 96 rows written. Page 1 reported `MARKETCOUNT=36`
  against `limit=35` (impossible) and page 3 reported 27 where 26 lines were enumerated.
  Actual pages: 35 + 35 + 26 = 96.
- `KXNFLRSHYDS` reported 38 total, 37 rows written. Page 1 reported 36 against
  `limit=35`. Actual: 35 + 2 = 37.
- `KXNFLTD` reported 44 total, 43 rows written. Page 1 reported 36 against `limit=35`.
  Actual: 35 + 8 = 43.

In all three cases the overcount is the summarizer's arithmetic on a page that is
hard-capped at 35 by the `limit` parameter. No tickers are missing: each series' final
page returned `CURSOR=EMPTY`, and every strike in each player's ladder is contiguous.

URLs, DET@BUF (cursors abbreviated):
```
.../markets?event_ticker=KXNFLREC-26SEP17DETBUF&status=open&limit=35
.../markets?event_ticker=KXNFLREC-26SEP17DETBUF&status=open&limit=35&cursor=CgwIlrSi1QYQ-Lr0gAISI0tYTkZMUkVDLTI2U0VQMTdERVRCVUYtREVUSkdJQkJTMC03
.../markets?event_ticker=KXNFLREC-26SEP17DETBUF&status=open&limit=35&cursor=CgwIlrSi1QYQ-Lr0gAISI0tYTkZMUkVDLTI2U0VQMTdERVRCVUYtQlVGRE1PT1JFMi0y
.../markets?event_ticker=KXNFLRECYDS-26SEP17DETBUF&status=open&limit=35
.../markets?event_ticker=KXNFLRECYDS-26SEP17DETBUF&status=open&limit=35&cursor=CgwIvpmi1QYQiKaDigESK0tYTkZMUkVDWURTLTI2U0VQMTdERVRCVUYtQlVGREtJTkNBSUQ4Ni0xMjA
.../markets?event_ticker=KXNFLRECYDS-26SEP17DETBUF&status=open&limit=35&cursor=CgwI_vuh1QYQuMXr7QESKktYTkZMUkVDWURTLTI2U0VQMTdERVRCVUYtREVUSldJTExJQU1TMS01MA
.../markets?event_ticker=KXNFLRSHYDS-26SEP17DETBUF&status=open&limit=35
.../markets?event_ticker=KXNFLRSHYDS-26SEP17DETBUF&status=open&limit=35&cursor=CgsI__uh1QYQyPn_CxIoS1hORkxSU0hZRFMtMjZTRVAxN0RFVEJVRi1ERVRKR0lCQlMwLTEyMA
.../markets?event_ticker=KXNFLPASSYDS-26SEP17DETBUF&status=open&limit=35
.../markets?event_ticker=KXNFLPASSTDS-26SEP17DETBUF&status=open&limit=35
.../markets?event_ticker=KXNFLTD-26SEP17DETBUF&status=open&limit=35
.../markets?event_ticker=KXNFLTD-26SEP17DETBUF&status=open&limit=35&cursor=CgsIicef1QYQiP31BxIiS1hORkxURC0yNlNFUDE3REVUQlVGLURFVEpHSUJCUzAtMQ
```

### Sunday games — `KXNFLTD` only

All returned `CURSOR=EMPTY` on a single page; reported MARKETCOUNT equals rows written
in every case.

| Event | URL suffix | MARKETCOUNT | Rows | Agree? |
|---|---|---|---|---|
| GB @ NYJ | `KXNFLTD-26SEP20GBNYJ` | 5 | 5 | yes |
| CAR @ ATL | `KXNFLTD-26SEP20CARATL` | 6 | 6 | yes |
| MIN @ CHI | `KXNFLTD-26SEP20MINCHI` | 8 | 8 | yes |
| PHI @ TEN | `KXNFLTD-26SEP20PHITEN` | 7 | 7 | yes |
| PIT @ NE | `KXNFLTD-26SEP20PITNE` | 6 | 6 | yes |
| NO @ BAL * | `KXNFLTD-26SEP20NOBAL` | 6 | 6 | yes |
| CLE @ TB * | `KXNFLTD-26SEP20CLETB` | 5 | 5 | yes |
| CIN @ HOU * | `KXNFLTD-26SEP20CINHOU` | 8 | 8 | yes |

\* Not on the requested slate. These are real Week-2 events that exist on Kalshi and were
included because they complete the Sunday anytime-TD picture.

---

## Empty results (real information, not fetch failures)

### The Sunday slate has not been listed yet for the yardage/reception series

`KXNFLREC`, `KXNFLRECYDS`, `KXNFLRSHYDS`, `KXNFLPASSYDS` and `KXNFLPASSTDS` have **no
`26SEP20` events at all**. Verified against the full event index for each series
(`/trade-api/v2/events?series_ticker=<S>&limit=30`): the newest event in every one of
those five series is `26SEP17DETBUF`. Everything before it is Week 1 (`26SEP13`/`26SEP14`)
or earlier. Kalshi lists the full player-prop suite for a Sunday game only a day or two
before kickoff; today is Tuesday 2026-09-15.

These 45 event tickers therefore returned `MARKETCOUNT=0`:

```
KXNFLREC / KXNFLRECYDS / KXNFLRSHYDS / KXNFLPASSYDS / KXNFLPASSTDS
  x  26SEP20GBNYJ, 26SEP20SEAARI, 26SEP20CARATL, 26SEP20MINCHI, 26SEP20NYGLAR,
     26SEP20PHITEN, 26SEP20MIASF, 26SEP20WASDAL, 26SEP20PITNE
```

(Each of the nine was probed directly on `KXNFLPASSTDS` and returned
`MARKETCOUNT=0 / CURSOR=EMPTY`; the event-index check above covers the other four series.)

### Four requested games have no Week-2 event on Kalshi in ANY series

- `26SEP20SEAARI` (Seattle at Arizona)
- `26SEP20NYGLAR` (NY Giants at LA Rams)
- `26SEP20MIASF` (Miami at San Francisco)
- `26SEP20WASDAL` (Washington at Dallas)

The complete `KXNFLTD` event index (31 events, `CURSOR=EMPTY`, so not truncated) contains
eight `26SEP20` games and none of these four. Alternates were probed and all returned
empty:

```
KXNFLTD-26SEP20NYGLA    (Kalshi abbreviates LA Rams as "LA" in KXNFLWINS-LA)  -> EMPTY
KXNFLTD-26SEP21SEAARI   (Monday)                                              -> EMPTY
KXNFLTD-26SEP21MIASF    (Monday)                                              -> EMPTY
KXNFLTD-26SEP21WASDAL   (Monday)                                              -> EMPTY
```

No `26SEP21` event exists in the `KXNFLTD` index either. Most likely these are the
late-window / SNF / MNF games and simply have not been created yet.

### Series probes that 404'd
```
/trade-api/v2/series/KXNFLRUSHYDS   -> 404
/trade-api/v2/series/KXNFLRUSH      -> 404
/trade-api/v2/series/KXNFLRUSHYARDS -> 404
/trade-api/v2/series/KXNFLRYDS      -> 404
/trade-api/v2/series/KXNFLATD       -> 404
/trade-api/v2/series/KXNFLPLAYERTD  -> 404
/trade-api/v2/series/KXNFLTDSCORER  -> 404
```

No WebFetch call failed for transport reasons. Every 404 and every empty array is a real
answer from the API.

---

## Ladder consistency check

335 rows, 0 duplicate tickers. Every player ladder was sorted by strike and checked for
monotonicity.

**Hard inversions (a higher strike's BID above a lower strike's ASK — a locked
arbitrage): none.**

**Soft inversions (a higher strike quoted above a lower strike on the same side): 22.**
All are in DET@BUF and all sit inside a wide bid/ask, so none is tradeable. The pattern is
consistent: the lower strike is untraded with a very wide spread, so its *bid* sits below
the tighter, actively-traded higher strike's bid. Notable cases:

```
DJ Moore receiving yards
  ...-BUFDMOORE2-110 | DJ Moore: 110+ receiving yards | bid 0.0300 ask 0.1200
  ...-BUFDMOORE2-120 | DJ Moore: 120+ receiving yards | bid 0.1000 ask 0.1100
  -> 120+ bid (0.1000) is above 110+ bid (0.0300); 110+ ask 0.1200 still covers it.

Sam LaPorta receiving yards
  ...-DETSLAPORTA87-90  | Sam LaPorta: 90+ receiving yards  | bid 0.0500 ask 0.1200
  ...-DETSLAPORTA87-100 | Sam LaPorta: 100+ receiving yards | bid 0.0800 ask 0.0900

Jared Goff passing yards
  ...-DETJGOFF16-325 | Jared Goff: 325+ passing yards | bid 0.0900 ask 0.2300
  ...-DETJGOFF16-350 | Jared Goff: 350+ passing yards | bid 0.1200 ask 0.1300

James Cook III rushing yards
  ...-BUFJCOOK4-50 | James Cook III: 50+ rushing yards | bid 0.6800 ask 0.8200
  ...-BUFJCOOK4-60 | James Cook III: 60+ rushing yards | bid 0.6900 ask 0.7300

Amon-Ra St. Brown receptions
  ...-DETASTBROWN14-4 | Amon-Ra St. Brown: 4+ receptions | bid 0.7900 ask 0.9000
  ...-DETASTBROWN14-5 | Amon-Ra St. Brown: 5+ receptions | bid 0.8000 ask 0.8500

Jameson Williams receptions
  ...-DETJWILLIAMS1-7 | Jameson Williams: 7+ receptions | bid 0.0200 ask 0.1200
  ...-DETJWILLIAMS1-8 | Jameson Williams: 8+ receptions | bid 0.0500 ask 0.0800
```

Remaining soft inversions of the same shape: Joshua Palmer REC 4/5, Khalil Shakir REC 8/9,
DJ Moore REC 8/9, Dalton Kincaid REC 8/9 and 9/10, Isaac TeSlaa RECYDS 40/50, DJ Moore
RECYDS 130/140, Dalton Kincaid RECYDS 110/120 and 120/130, Khalil Shakir RECYDS 90/100,
Sam LaPorta RECYDS 40/45 and 80/90, Jameson Williams RECYDS 80/90, Jahmyr Gibbs RECYDS
60/70, Amon-Ra St. Brown RECYDS 140/150, Jared Goff PASSTDS 4/5.

**Practical read:** use `yes_ask` (or the midpoint) rather than `yes_bid` when deriving
implied probabilities from these ladders. The bid side alone is not monotone on thin
strikes and will produce negative implied densities between adjacent strikes.
