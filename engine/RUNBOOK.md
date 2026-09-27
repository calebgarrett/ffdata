# ff — the fantasy system. Runbook.

Built 2026-09-16 after a week in which the same question got different answers, a
rostered player was recommended as a waiver add, an IR player was recommended twice,
a handcuff was flagged as a drop, a defense was told to be swapped in when it was
already starting, and the projection board's top two names had played three snaps
between them. Every one of those is now a regression test, and nothing ships unless
all of them pass.

Code lives at `/home/claude/bsb2` in the session and is mirrored to the project under
`claude/system/`. **The container is ephemeral; the project copy is the one that survives.**

---

## The one command

```
python3 ff.py run
```

That is the weekly routine. It does, in order, and refuses to continue if any step fails:

1. **check** — the gate regression (17 cases) and the system regression (27 cases).
2. **week** — both lineups by exact assignment, diffed against the slots that are actually filled.
3. **wire** — both free-agent pools by subtraction, audited, ranked usage-first, gated.
4. **season** — December environment (weeks 15–17) and byes, from posted look-ahead lines.
5. **card** — regenerates the Lineup Card **from that output**. Nothing on the card is typed by hand.

Other commands:

| command | what it answers |
|---|---|
| `ff.py status` | "Are we good?" — state age, next locks, open ledger items, starters nobody projects |
| `ff.py check` | the two regression suites, with detail |
| `ff.py week` / `wire` / `season` / `card` | one step of `run` |
| `ff.py decline BSB add "Player Name"` | record a "no" so the call is never re-raised without new evidence |

---

## The five things that make it reliable

**One clock.** `lib/clock.py`. Everything is US Eastern. The NFL week, the BSB waiver
deadline (Wednesday 06:00 ET), every kickoff, and a *lineup phase* per game — `early`,
`decide` (≤36h), `alert` (≤24h), `locked`. Caleb's rule, "don't worry about lineup
changes unless it's at least 1 day before the game," is enforced by the phase, not by memory.

**One state.** `lib/state.py`. A snapshot of every roster in each league, with slots, with
a pull time. Yahoo's repeated slot names (RB, RB, WR, WR, WR) are numbered so a lineup
dict can never silently drop a starter. The state knows its age and refuses purposes it is
too old for: 18h for a lineup call, 30h for an add/drop. **Every recommendation is a diff
against this object.** A start call on a player already starting is filed `already_set`
and never surfaced.

**One ledger.** `lib/ledger.py`. Every call, with a status — `proposed`, `executed`,
`already_set`, `declined`, `superseded`, `expired`. Each run begins by reconciling open
items against live state. A new call that contradicts a prior one is marked as a
reversal and the prior is superseded by name. A declined call BLOCKS in the gate until
there is new evidence.

**One projection layer, one scorer.** `lib/project.py` builds one stat line per player,
market-first — Kalshi ladders (price = probability; a ladder is a distribution), then
Vegas implied totals, then DraftKings props (line only, median→mean corrected), then
Sleeper. `lib/score.py` scores that same line under either league's rules. LaPorta's
4.24 receptions is one number from one source that becomes 4.24 points in BSB and 3.82
in HH. Two leagues cannot disagree for modelling reasons. A player nobody covers is
**unknown, never 0.00**. Market readiness is per game: on a Tuesday only Thursday is
priced, and everything else says PROVISIONAL.

**One gate.** `lib/gate.py`, twelve checks, each encoding a real failure:

| gate | what it caught |
|---|---|
| G1 ownership | Kenneth/Kenny Gainwell recommended as a free agent; he was on Rick's bench |
| G2 designation | Jordyn Tyson recommended twice; he is on IR |
| G3 role | Ray Davis flagged as a drop; he is the James Cook handcuff |
| G4 horizon | "Drop the 49ers" off a season number; DEF is a weekly matchup slot |
| G5 sources | Yahoo and Sleeper called two sources; both are Rotowire |
| G6 magnitude | Yahoo's roster "points" column read as points; it is a rank |
| G7 readiness | a Sunday start/sit answered on Tuesday with no market posted |
| G8 freshness | replacement level from a stale pull |
| G9 reversal | six silent reversals in one session |
| G10 mechanics | a start-then-drop planned inside one scoring week |
| G11 role registry | Germie Bernard (3 snaps) and Ty Johnson (RB3, hurt) topped the projection board |
| G12 state | "swap in the 49ers" when they were already in the slot |

---

## The role registry — the tiebreaker

`data/roles.json`, mirrored to `claude/verified-roles-2026-wk2.md`. Sourced beat reporting
and published snap counts, dated. Four lists: `hold`, `drop_ok`, `add_yes` (with a
`priority` that encodes the reasoning, e.g. Hutchinson above Antonio Williams because
Higgins' ACL makes the role permanent), `add_no`, `unavailable`.

**A projection forecasts production. A snap count observes whether a player is on the
field. Where they disagree, the snap count wins.** No player is added without a usage
row. Realized usage is its own evidence family in the gate, separate from any projection,
even when Rotowire published it.

Re-verify entries older than seven days. The weekly usage pull (snap %, route %, target
share for the top ~40 available at each position) is the one input that still comes
from a research subagent rather than a fixed endpoint.

---

## Doctrine the code enforces (all Caleb's, all stated in the thread)

- **A tag is never a drop reason** (Caleb, 2026-09-21: "You are telling me to drop control of players and you have no idea why they missed one week. That's horrible roster management."). O/Q/D/IR/PUP/SUSP/CEL on a Yahoo page is a fact about one week. `wire.dead_spot()` is true only for a long-term designation AND a `roles.json` `drop_ok` entry that records what the injury is and how long (Dell IR-R was one; Jennings O was not). Without that, `gate_drop` BLOCKs (G13-injury), the breakout scanner skips him as a drop, the claim plan skips him, and the card says "why and for how long is NOT on record; not a drop until it is". Verifying the injury — reported cause and expected timeline — is a registry write, done with Caleb present.
- **A market from another week is never applied** (`Projections` week guard, 09-23): Kalshi ladders are kept only when the event ticker's date falls in the current NFL week; game lines only when the kickoff does; the props file only when it was written after the week began; market-readiness counts only this week's events. Before the guard, a week-3 Wednesday priced Sunday's players off week-2 ladders and Goff off week-2 props.
- **Yahoo projections are the fallback, labelled** (`data/yahoo_{league}_wk{W}.csv`, copied off the matchup page): points-only, league-scored by Yahoo, one source family (`yahoo`), boom share unknown. Every call on them is PROVISIONAL (G5 single source, G7 no market) until the market posts. Win probability refuses to compute P(beat opponent) when the opponent has a starter no source prices, rather than overstating it.
- **"Unrostered" is only as current as the LEAGUE read** (Caleb, 2026-09-23: "Fields is not available in BSB. Don't make bad recommendations like that."). The matchup page refreshes my roster and my opponent's; the other ten (BSB) / eight (HH) rosters carry the date they were actually read — `others_pulled` on the snapshot. G1 now BLOCKs any BSB add when that read predates the last Wednesday waiver run (claims processed that the snapshot cannot see), and WARNs any add on a league read older than 24h; the card prints the warning on the tile as "check first". Refreshing availability for a BSB add after Wednesday means reading every roster or the transactions page since the run.
- **The tag counts for nothing — in either direction** (refined 09-23). A merely-tagged player is not a dead spot, but he is not undroppable either: drop candidates are ranked on SEASON value in both leagues, as if healthy, and the gate's G13 is a WARN that says the tag was not counted. Pierce (D) was the HH drop for Fields because Kelce and Henderson showed starter usage of their own and Pierce played 26% of snaps — not because of the D.
- **Two straight weeks of starter usage is the confirmation** (09-23). A Tier-B row (usage says starter, market not caught up) whose PRIOR week's pull also shows starter usage is `held` and becomes an ADD when a clean drop exists that he out-projects this week; otherwise it says exactly what blocks it ("no clean drop left" / "no drop worth less than him"). A third TE, or any add who would sit behind everyone rostered at a position with dedicated slots (flex not counted), is NONE.
- **A player Caleb dropped is not re-proposed** on the same usage pull (`state.recently_dropped`, 7 days; Black 09-21).
- **The card is read on a phone: decisions first, detail folded** (Caleb, 2026-09-25: "a bit overly detailed to scroll through on a phone"). `card._assemble()` reorders the rendered page: DECIDE (every tile that needs an action or a decision within 36h — lineup swaps, adds, withdrawn markets, market cuts on my starters; "Nothing needs a decision right now." when empty) → OUTLOOK (one tile per league: record, rank, PF, projected total, P(beat opponent)/P(beat median), next lock and who locks, Watching: OUT/Q starters and provisional swaps) → collapsed `<details>` sections in the old order (lineups and gate output, provisional calls and holds, market moves, FAB, streaming, breakouts, December, inputs). Nothing is dropped from the page — the gate output is still there verbatim, one tap down. Records come from `state.records` (pump standings, saved on every snapshot).
- **The engine runs in the pump, and the card publishes itself** (v6, 09-26; Caleb: "Is there a better way we could keep the card from being so stale in terms of game results and matchup odds?"). The ffdata workflow unpacks `engine/` (this directory, shipped once as `engine.tar.gz`), symlinks `/home/claude/bsb2` and `/home/claude/ffdata_repo` at the checkout, runs `ffdata_load.py` (`FFDATA_IN_ACTION=1`: no git pull, the checkout is the repo) and `ff.py run`, wraps `lineup-card.html` in a document skeleton and commits it as `docs/index.html`; GitHub Pages serves it at calebgarrett.github.io/ffdata. If the check refuses, the previous card stands and `docs/run.txt` says why. Pulls follow the game week: daily 7 am ET; Thu 7 pm; Fri/Tue 11:45 pm (post-game); Sun 11:30 am; Sun 12:30 pm to 12:30 am every 30 min. Crons are UTC, so after Nov 1 they land an hour earlier ET. Engine code changes reach the repo only by uploading a new `engine.tar.gz` (Caleb, from the phone); data flows only through the pump. The repo's `engine/data` (ledger, state, actuals) is the authoritative record once v6 runs.
- **Live scoring** (09-26). `ffdata_load.game_frac()` reads the fraction played off Yahoo's game text (Q3 5:12 → 0.66, Half → 0.5, End Qn → n/4, OT → 0.97, Final → 1). `actuals/{LG}_wk{W}.csv` carries finals AND games in progress with `final` and `frac`; a live player counts `live pts + projection × (1 − frac)` in the lineup and total, the win-probability sampler keeps only the unplayed share of his spread, and the card shows LIVE with points so far. Live and final players are locked: never proposed in or out.
- **QBs in superflex are depth, not drop fodder** (Caleb, 2026-09-27: "QBs are too valuable in superflex though compared to a flyer WR."). `Wire.gate_drop` G14: in a league with two or more QB-eligible slots (HH: QB + Q/W/R/T), every QB up to one past those slots (QB3 in HH) is bye-week and trade depth and is BLOCKED as the drop for a non-QB add; a fourth QB is fair game; a dead spot or registry drop_ok still overrides. BSB (one QB slot) is untouched. This retracts the Mitchell-for-Stafford tile of 09-27 12:35.
- **Tier A needs a starter's line, and the drop must be worth less than the add** (09-27). "The market agrees" requires the market line itself to clear a starter floor (receiving 35 yds, rushing 40, passing 200), not merely to sit above Sleeper (Treadwell: 26 over 23). A Tier-A add never takes the last clean drop when that player's season value over the wire's replacement at his own position exceeds the add's.
- **Five rules from the first Saturday card** (09-26). A QB starting (gs=1) is not a role change: from usage alone a wire QB is WATCH, never Tier A/B (Maye proposed as a 4th QB). A player Caleb added this week is never the proposed drop (`state.recently_added`; Jameson Williams, added 09-25). A player he dropped in EITHER league is not re-proposed in the other for 7 days (`recently_dropped_anywhere`; Fields, dropped in HH 09-25). A BSB player dropped "To Waivers" since the Wednesday run is a CLAIM that processes Wednesday and cannot play this week, never a free-agent add (`breakout._on_waivers` from the transactions log; Fields sat on waivers Fri 09-18 → Wed 09-23). The weekly upgrade board never proposes a player "over" a starter whose game is final or live (Perine over Lloyd's 3.80). All five are regression cases.
- **Gate controls are stamped fresh** (09-25). The pump has no Friday pull, so a live snapshot is 20h+ old every Friday; the control cases in `test_gate.py` (start/drop/add "should PASS") run against a copy of live state stamped now, because they test mechanics, not the calendar. Staleness itself is still enforced on every real call (G12 WARN for lineups >18h, BLOCK for add/drop) and shown on the card.

- **Market first.** Kalshi and Vegas outrank every projection. Fantasy prognosticators are amateurs.
- **Individual points matter.** A season projection already contains team context. Environment is never a haircut on a mean and never in a headline. It is for upside, tie-breaks, streaming slots, and speculative adds.
- **Upside on the bench.** Bench spots are judged on *boom share* — the fraction of projected points from touchdowns and defensive big plays. T.J. Watt at 11.7 with 47% boom beats a 20.5-point tackle-volume linebacker on a bench.
- **Two DEFs in BSB are worth it — measured, not assumed** (Caleb, 2026-09-24: "Are we sure 2 DEF spots isn't warranted given how much they can score or earn negative points?"). Weeks 3-9 on posted look-ahead lines, BSB scoring: best-of-two (Vikings + 49ers) beats the Vikings alone by **+1.2 pts/week**; streaming the 6th-best matchup instead (what the wire realistically offers) beats them by +0.7. So the second DEF is worth ~0.5/week over streaming plus two bye weeks covered (MIN 6, SF 8) and the dodge of a negative game. The old "hold ONE defense in BSB" line was my inference and is retired. Rule in code: the spare DEF (lower season value of the pair) is a drop candidate for a **Tier-A** add only; a Tier-B (unpriced) add never takes it. Both DEFs stay; the lineup picks the matchup each week.
- **Spots go to season-changing upside.** Do not carry a spot to insure a streamable bye hole. Week 11 in BSB is a week-10 calendar item.
- **Lineup calls one day out.** Earlier in the week is roster construction.
- **Don't narrate errors. Fix them.** Errors go to the regression suite; the card shows calls.
- **Don't reach.** A clean negative ("the manager-level December spread is 1.9 points across twelve rosters — noise") is a result.

---

## Timing rule for the December DEF/K edge (Caleb, 2026-09-16)

"Teams will start holding multiple defenses later in the season as they prepare for the
playoffs." So the week-15-17 matchup edge is not collected in December — by then the wire is
picked over. It is collected by getting there **first**:

- **Weeks 1–9:** stream DEF/K freely in BSB (uncapped). In HH a second DEF that is elite on
  the season and strong in the playoff window is already a hold (the Texans).
- **Weeks 8–13:** `ff.py season` prints the PLAYOFF STASH WINDOW — the best week-15-17 DEF
  and K still on the wire, ranked by opponent (DEF) / own (K) implied total. Take the best one
  before the hoarding starts, in both leagues. A second DEF with a playoff schedule becomes a
  hold from here on, capped league or not.
- **Weeks 14–17:** hold; the wire is empty of anything good.

Current week-15-17 DEF ordering by opponent implied total: NE 20.33, GB 20.67, PHI 20.67,
HOU 20.92, LAC 21.25, LV / MIN / PIT / SEA 21.33. HOU is already Caleb's in HH.

## Strategic edges the system computes that opponents do not

- **Line movement and withdrawn markets** (`lib/steam.py`, 2026-09-25). The pump archives every Kalshi pull (`data/kalshi_archive/`). Every rostered player's ladder median (read off the ladder, no fit) is compared with the week's first pull; a move past 15% is reported with who rosters him, and a move against one of my starters becomes a card flag. A player whose markets existed in the previous pull and are gone now, with his game not yet kicked off, is reported as withdrawn = OUT until Yahoo says otherwise (the Sunday 11:30 pull is the inactive list, before the 1:00 lock). First run: Achane +67% rec yds, Rice +47%, Worthy +20%, Kelce +17% between Wednesday and Thursday — a KC/MIA repricing nobody's projection showed.


1. **Kalshi ladders as distributions.** Not lines — full probability distributions per stat, fitted to SSE < 0.01. No devig, no median→mean fudge. Two independent methods (Kalshi, Rotowire) agreed on LaPorta to two decimals.
2. **Usage before projection.** The projection-only board recommended two players who barely played. The usage-first board recommended two who did.
3. **December priced in September.** Look-ahead lines through week 18 give every team's implied total in the fantasy playoffs. LAC is the biggest schedule opening in the league (21st → 7th). And the edge pays in Heritage House (8 of 10 make playoffs) more than BSB (11th of 12 — has to get there first).
4. **IDP environment inverted.** A defender scores off the opponent's plays. Schwesinger is 32nd by own offense and 6th by the number that governs his scoring.
5. **Exact-assignment lineups with Yahoo umbrella eligibility.** Fifteen HH slots including D/DB/DL umbrellas, solved optimally, permutations suppressed.
6. **Positional-fit trades** (`trade2.py`, not yet folded into `ff.py`). Every piece the other side receives must start for them.
7. **The breakout scan** (`ff.py breakout`, in every `run`, on the card). Caleb, 2026-09-16: "Typically there are 3-4 undrafted players who get added this first 1-3 weeks that change seasons or even win the league." They share one trait: a role that arrives before the price. `lib/breakout.py` ranks the unrostered pool on last week's verified usage (share of team snaps / targets / air yards / RB touches), next week's Kalshi or DK line against the Sleeper projection, the preseason rank, and Sleeper's 48-hour trending adds. Tier A = usage says starter and the market agrees (claim). B = usage says starter, market not there yet (the cheap window). C = the crowd is chasing a box score the usage does not back (let them). W = watch, including 'usage says starter but the posted market prices him well under the projection' — market first, always. The scan is a lens, not a claim plan: a Tier A/B that passes the gate two consecutive weeks, or that has a verified injury to the player ahead of him, gets written into `roles.json add_yes` with a priority, which is what puts him at the top of the wire.

---

- **Next man up** (`lib/nextup.py`, 09-26). Depth charts from the last two usage pulls (snap share; RBs on touches; newest weighted double). For each of Caleb's starters and his opponent's whose game has not kicked off: the next man at his position on his NFL team and where he is in this league (free agent / on waivers / owned). A starter who is OUT (Yahoo tag, or Kalshi withdrew his markets on the 11:30 pull) with a free-agent backup becomes a Decide tile with the mechanics and the clean drop. In BSB a never-rostered free agent is Caleb's until his game kicks off.
- **Playoff leverage** (`lib/playoff.py`, 09-26). Every roster's weekly strength (optimal lineup on individual per-week values; BSB season blend ÷ 17, HH this week's projections; byes zeroed per future week), the rest of the regular season simulated 4,000 times (known opponent this week, random pairings after — the league schedule is not on file; BSB vs-median each week; BSB divisions not modelled). Outputs P(playoffs), P|win and P|loss this week (leverage), P at +5 pts/week, top-half seed odds, and every team's odds. Regression: seats conserved, a win never lowers the odds, +5 raises them, a zero roster misses.
- **Rivals** (`lib/rivals.py`, 09-26). Per manager from the transaction logs and rosters: adds, claims, FA pickups, last-7-day adds, FAB spent/left, usual bid, whether he streams DEF, and where his roster is thin (weakest starter under 80% of the league median at the family, or a starter out). The Tier-A bid on a breakout tile is now the bid to beat against the likely field (everyone thin at the position plus habitual bidders — two or more claims or a $5+ bid — each priced at his usual bid; one claim counts at 60% unless he is thin there), bounded by the Tier-B floor and the contested cap. Tier-B claims always take the floor. HH: adds in the last 7 days against the 7-a-week cap (reset day undocumented — stated as such).
- **Calibration** (`lib/calib.py`, 09-26). Every run logs each source's pregame number for every rostered player (`data/proj_log/{LG}_wk{W}.csv`: engine, Sleeper-only via `Projections.line(market=False)`, Yahoo); a row locks at kickoff; a first sighting after kickoff is `post` and never scored. The report joins Yahoo actuals (exact scoring, matchup-page rosters only) and gives n / MAE / bias per source and position, cumulative. Under three weeks it is a report; after that a source measurably worse at a position loses its override there. HH week 2 is back-filled engine-only.
- **Same-game correlation** (`lib/winprob.py`, 09-26). Skill players' samples carry a shared game factor (sd 0.15) and team factor (sd 0.25), idiosyncratic part shrunk 4% so each mean and spread hold; teammates correlate ~0.25-0.35, opposing offences ~0.1. DEF, K, IDP independent (stated). Lineup sd rose ~15% as a result; probabilities are honest rather than overconfident.

## What still needs a person or a browser

- **Yahoo roster pulls.** The live state comes from a Chrome session. When Chrome is unreachable the system runs on the newest snapshot and says how old it is; add/drop calls BLOCK past 30h.
- **The weekly usage pull — now a fixed endpoint, on request.** Sleeper's stats feed `https://api.sleeper.app/stats/nfl/2026/{week}?season_type=regular&position[]={QB|RB|WR|TE}&order_by=off_snp` carries `off_snp`, `tm_off_snp`, `rec_tgt`, `rec_air_yd`, `rec_rz_tgt`, `gs` per player. Only WebFetch reaches it, and WebFetch's summarizer truncates the payload around the 65th object and corrupts long tables, so the protocol is: (1) one subagent per position; (2) extract in small chunks by `off_snp` range, verbatim; (3) repeat every chunk against the same URL with `&v=2` appended (a fresh cache entry = an independent extraction); (4) keep a row only where both agree on every field, break ties with a single-player raw-dict lookup by `player_id`, drop what will not resolve and say so; (5) for the players the truncation hides (low snaps, real targets — the JAX WRs on 09-17), re-order the array with `order_by=rec_tgt` and `order_by=rec_air_yd` and union. Output `data/usage_wk{W}_{POS}.csv`. Trending adds: `https://api.sleeper.app/v1/players/nfl/trending/add?lookback_hours=48&limit=40` (ids; resolve via `/v1/players/nfl/{id}`) → `data/trending_adds.csv`. Route share is not in this feed; beat reporting still supplies it for the registry. Run Monday night or Tuesday after the week's games are in, when Caleb asks.
- **Fetch provenance, learned 2026-09-18.** In a session where a host has not been approved, WebFetch refuses it (PROVENANCE_REQUIRED) and no approval prompt reliably reaches Caleb's phone. A URL Caleb pastes into the chat becomes fetchable — but every later request to that host+path is rewritten to the pasted URL, query string included: paste `/markets` bare and every Kalshi request returns the bare default page (cross-category junk); paste `/markets?event_ticker=X` and every request returns X. So one pasted URL buys exactly one page. A full Kalshi re-pull (14 games × 4-6 series, with cursor pages) is not possible this way; ask for the handful of pages the open calls depend on, and say so. The Wednesday-night ladders remain the working set for the week unless a page is re-pulled by name. Yahoo pages are unaffected (each team/transactions page is its own path and was approved earlier in the session).
- **Getting ALL of Kalshi, automatically (Caleb, 2026-09-18: "it's super valuable data").** The cloud container cannot reach api.elections.kalshi.com (org policy) and WebFetch is a one-page-per-paste instrument (above). Caleb's own computer can, through the desktop bridge. `pull/kalshi_pull.py` (public endpoints, no key, standard library) walks every open event of every NFL prop series and writes the exact CSV `lib/market.py` reads, refusing to report success on a partial pull; `pull/espn_pull.py` does the same for the week's game lines. Run them on the computer with `device_bash`, write the output into a connected folder, stage it into the container, and copy over `data/kalshi.csv` / `data/espn_games.csv` (delete `kalshi.csv.fits.pkl`). Automation, as built 2026-09-18 (Caleb is away from his computer for two weekends, so the cloud has to do it): scheduled task **"NFL market pull — Kalshi ladders + game lines"**, cloud-only, Tue/Thu/Sat/Sun 11:00 UTC (7 am ET). It uses WebFetch with the Wednesday protocol (events per series, then /markets at limit=35 paged by cursor, verbatim, ticker-prefix checked, subagents in parallel) and writes `claude/system/data/kalshi.csv` (only if ≥1500 rows), `claude/system/data/espn_games.csv`, dated copies under `claude/system/data/pulls/`, and `claude/system/data/pulls/last_pull.md`. **It only works if the task is set to "Automatically approve" in the app** — a one-shot test on 09-18 proved an unattended run raises a per-URL permission request that expires unanswered (`claude/system/pull/fetch_test.md`). **Superseded 2026-09-21** — every scheduled cloud pull stalled on a fetch permission prompt (test, two real runs, one manual fire); all triggers are deleted and no scheduled task is to be created again. Caleb, 2026-09-20: "You are burning through a ridiculous amount of usage credits… mostly failing due to permissions or failed web pulls. We need a better model that's more efficient." → "Sounds good."
- **Rosters come from the pump too (v5, 2026-09-24 17:27 UTC).** `pull/yahoo_pull.py` + `pull/yahoo_parse.py` read the logged-out Yahoo pages from GitHub's runner — every team page in both leagues (slots, tags, bye, Yahoo proj), the week's matchup (both lineups, scores, finals) and the transactions log (who added whom, FAB bid, when) — into `data/yahoo/*.csv`. `ffdata_load.py` turns them into a state snapshot per league with `others_pulled` = the pull time (so G1 sees a fresh league read), `yahoo_{lg}_wk{W}.csv` projections for every rostered player, `matchups.json`, `actuals/{lg}_wk{W}.csv` from rows whose game text starts with Final, and merges the transactions into `bsb_transactions.csv` / `hh_transactions.csv`. **The pasted Yahoo links are retired.** Refresh = `python3 ffdata_load.py && python3 ff.py run`, then republish. Parser notes: rows split after stripping `data-tooltip` attributes (the only nested tables); slot from `data-pos`; tag from `ysf-player-status`; the matchup page lists both lineups side by side per row [mine | proj | fan | slot×3 | fan | proj | theirs]; record from `Fw-b Fz-xxl`. GitHub gotcha that cost three runs: **Re-run replays the old file** — a new version needs Run workflow (All workflows ▾ → the workflow → Run workflow ▾).
- **Game lines come from Kalshi too (v3, 2026-09-24).** `KXNFLSPREAD` ("KC wins by over 9.5?", both sides, ~25 strikes), `KXNFLTOTAL` ("over 46.5 points?", ~19 strikes) and `KXNFLGAME` (winner) are full ladders for every game; `market.load_kalshi_games` takes the median of each and derives implied team totals, and `Projections` overlays them on the schedule (kickoffs from ESPN/look-ahead). All 16 week-3 games on Wednesday night, agreeing with ESPN where ESPN had a line (GB −4.5/42.5 vs Kalshi −4.7/42.5). ESPN's scoreboard on the runner returns a calendar-year dump capped at 100 events (one week-3 row) — it is a schedule source now, not the lines source. Readiness still counts PLAYER prop series only. `KXNFLTEAMPTS` on Kalshi is season most/least-points, not team totals.
- **THE DATA PUMP IS LIVE (2026-09-23 15:23 UTC first run): `github.com/calebgarrett/ffdata`, public.** And the container can reach github.com and raw.githubusercontent.com directly — so the load is `python3 ffdata_load.py` (git clone/pull, verbatim bytes, no WebFetch, no summarizer, no truncation), then `python3 ff.py run`. That is the whole refresh: two commands (rosters, tags and finals come from the pump since v5). First run: 1,645 Kalshi markets over 58 week-3 events (381 fitted ladders, 20 of 32 teams priced on a Wednesday), 3,305 Sleeper offense and 4,604 IDP projections, 80 trending adds/drops. ESPN failed on the runner (no espn_games.csv) — the loader falls back to the week's rows of the look-ahead lines file, labelled and carrying the source file's age. The week's usage stats came back empty because v1 pulled the CURRENT week; **workflow v2** (in `claude/system/ffdata/`, and on the setup page's "Update to v2" section) pulls W-1 and W with three orderings unioned, and hardens ESPN. Until Caleb installs v2 the breakout scan runs on the newest usage on disk and says how stale it is. Workflow runs are checked in the GitHub app (Actions tab, green check / red X); api.github.com is 403 from the container.
- **The data pump as designed: GitHub Actions repo `ffdata` (built 2026-09-21, package mirrored at `claude/system/ffdata/`, zip delivered to Caleb).** The pulling moves entirely out of this session. A public GitHub repo runs `pull/kalshi_pull.py`, `pull/espn_pull.py`, `pull/sleeper_pull.py` (projections in the engine's format, per-position stats with `off_snp/tm_off_snp/rec_tgt/rec_air_yd/rec_rz_tgt/gs` plus actual points, 48-h trending adds/drops) and `pull/digest.py` on cron `0 11 * * 0,2,4,6` + `30 15 * * 0` (7 am ET Tue/Thu/Sat/Sun, 11:30 am ET Sunday) and commits the results. Digest writes one compact ladder file per event (`data/kalshi/<EVENT>.csv`: ticker,yes_bid,yes_ask,last_price,volume; each ≤9 KB so WebFetch's summarizer cannot truncate it), splits any Sleeper file over 9 KB into `_partN` files, and writes `data/index.txt` listing every file's raw URL. Because a URL that appears in a prior fetch result becomes fetchable, the session's whole protocol is: Caleb pastes the raw `index.txt` URL ONCE; fetch it; every listed file is then readable one WebFetch each, verbatim, no prompts. Cost per refresh: ~1 fetch per game-stat ladder actually needed (usually 6-12) + 1 per Sleeper part + 1 for espn_games, no subagents, no retries, no waits. Loader still to write: ingest `data/kalshi/<EVENT>.csv` (fill event/series/title from the ticker; title is optional for the fitter) and the Sleeper parts into `data/`, then delete `kalshi.csv.fits.pkl`. Until Caleb is at a computer to set up the repo: cheap mode — Yahoo matchup pages (`week=` always) and pasted Kalshi links only.
- **Actuals (Caleb, 2026-09-18: "shouldn't the card update projections with results?").** Yes. Source: the Yahoo MATCHUP page, `/f1/<league>/matchup?week=<W>&mid1=<my team id>` (BSB 7, HH 6) with a cachebust — it lists both lineups with each player's game status ("Final L 31-41 @ Buf") and the week's fantasy points, and the two totals reconcile (OVERKILL 20.90 + 17.20 = 38.10). The TEAM page's points column is NOT reliable: the same read gave 30.80/27.00 (wrong, does not reconcile) and later ranking columns. Copy the matchup page's final rows verbatim into `data/actuals/{league}_wk{W}.csv` (owner,slot,player,tm,status,pts,final). `lib/actuals.py` loads it; `lineup.solve(actuals=)` replaces the projection, locks the slot and never proposes a change involving a final player; `winprob.evaluate(actuals=)` treats a final score as a constant; the card shows FINAL rows and 'scored + projected' in the header. Read the matchup page on every check once a game has finished. Only my team and my opponent carry actuals; the other teams' finished players run on projections in the median (stated on the card).
- **The injury report.** 'The starter ahead of him is out' is the strongest single breakout signal (Higgins → Hutchinson) and is still not a feed: ESPN's and CBS's injury pages need a site approval in this session. Pull on request with Caleb present, write the verified role change into `roles.json`.
- **Win probability, not mean** (`ff.py win`, in every `run`, a tile per league on the card). Caleb, 2026-09-17: everyone is savvy, get one to three steps ahead in the lineup. `lib/winprob.py` samples every rostered player in the league 6,000 times — from the posted Kalshi ladder where one exists (inverse CDF through the strikes, nothing fitted), around the Sleeper mean where not (Poisson counts, gamma CV 0.55 yards, stated) — sums every team's current starters, and scores my current lineup, the mean-optimal lineup and every legal bench swap on P(beat opponent) and, in BSB, P(beat the league median). A swap is called only at +3 points of combined win probability. Opponents come from `data/matchups.json`, read off the Yahoo team page each week. Not modelled: same-game correlation.
- **No 2-for-1 where Caleb gives up the best overall asset** (Caleb, 2026-09-24, on Regulators' London-for-Love offer and my Love+Wicks counter idea). The best single asset in a deal has to land on his side. Incoming offers still get a numbers answer; counters that depth-for-star him are never proposed.
- **Trades are off.** Caleb, 2026-09-17: everyone in these leagues is savvy, trades do not happen, spend nothing on them. `lib/trade.py` exists (projection-vs-market gaps across rosters, persisted in `data/gaps/`) but is not run and not on the card.
- **The FAB ladder.** `lib/fab.py` reads the winning bids off `data/bsb_transactions.csv` (Yahoo transactions page, 'Added Players' view, shows the $ on every processed claim) into bands the breakout card quotes: Tier B = floor, Tier A = beats every bid but the whale's, contested = whale + 1. Re-pull the transactions page after each Wednesday run.
- **BSB plays vs Median.** Seen on the team page 09-17: 'Loss Week 1 vs Median', record 0-2-0 after one week. Two results a week, one against the opponent and one against the league median score. Half the record is pure scoring.
- **Division standings in BSB.** Six of twelve make the playoffs, division winners advance but seed by overall record, three divisions. A weak division is a path to January that does not require out-scoring eight teams. Not yet read.

---

## Files

```
ff.py                 entry point
lib/clock.py          one clock (ET)
lib/state.py          live state, snapshots, staleness
lib/ledger.py         every call with a status; reconciliation
lib/project.py        stat lines with provenance, market-first
lib/score.py          one scorer, both leagues (dispatches to scoring.py / hh_score.py)
lib/lineup.py         exact assignment, diffed against live slots
lib/wire.py           pool by subtraction, audit, usage-first ranking, claim plan
lib/usage.py          weekly usage pull as shares of team (snap / target / air / RB touch)
lib/breakout.py       breakout scan: role before price, tiers A/B/C/W
pull/kalshi_pull.py   full Kalshi NFL ladder pull (runs on Caleb's computer via the bridge)
pull/espn_pull.py     ESPN scoreboard lines pull (same)
../ffdata/            the GitHub Actions data pump (kalshi/espn/sleeper pulls + digest + workflow); project: claude/system/ffdata/
ffdata_load.py        git-clone the pump and install this week's files into data/ (run before ff.py run)
merge_kalshi.py       merge one verbatim page into data/kalshi.csv by player block
lib/winprob.py        win probability from the ladders: P(beat opponent), P(beat median), every bench swap
lib/steam.py          line movement since the week's first pull; markets withdrawn = inactives
lib/trade.py          (not run) projection-vs-market gaps across every roster
lib/fab.py            FAB ladder from the league's own transaction log
lib/gate.py           twelve checks
lib/names.py          canonical keys, phantom audit
lib/windows.py        December environment from look-ahead lines
lib/card.py           the generated card
lib/leagues.py        both rule sets
lib/market.py         Kalshi ladder fitting, Vegas lines, DK props
test_gate.py          17 gate regressions
test/test_system.py   27 system regressions
data/roles.json       the verified role registry
data/ledger.json      the decision ledger
data/state/<LG>/      roster snapshots
data/lines_wk*.csv    posted lines, weeks 3–18
data/kalshi.csv       fitted ladders
data/sleeper_*.csv    stat lines (offense, IDP, K/DEF)
```
