#!/usr/bin/env python3
"""Load the data pump (github.com/calebgarrett/ffdata) into data/.

The container CAN reach github.com and raw.githubusercontent.com directly
(verified 2026-09-23), so this is a git clone, not a WebFetch: every byte
verbatim, no summarizer, no truncation, one command.

    python3 ffdata_load.py            # clone/pull, install this week's files, report
    python3 ffdata_load.py --week 3   # override the NFL week

What lands where (only when the pump's file is newer than what is on disk):
  data/kalshi.csv                 <- data/kalshi.csv (full pull; fits cache deleted)
  data/espn_games.csv             <- data/espn_games.csv when the pump has it, else the
                                     week's rows of lines_wk3_9.csv / lines_wk10_18.csv,
                                     labelled 'look-ahead' in data/pulls/ffdata_pull.md
  data/sleeper_off_wk{W}.csv      <- data/sleeper/sleeper_off_wk{W}.csv
  data/sleeper_idp_wk{W}.csv      <- data/sleeper/sleeper_idp_wk{W}.csv
  data/trending_adds.csv          <- data/sleeper/trending.csv (adds only)
  data/usage_wk{W-1}_{POS}.csv    <- data/sleeper/stats_wk{W-1}_{POS}.csv when non-empty
Never estimates, never relabels another week's file as this week's.
"""
import re, csv, os, sys, shutil, subprocess, datetime as dt
sys.path.insert(0, '/home/claude/bsb2')
from lib import clock as C

REPO = 'https://github.com/calebgarrett/ffdata.git'
CLONE = '/home/claude/ffdata_repo'
D = '/home/claude/bsb2/data/'

def game_frac(game):
    """Fraction of a game played, read off Yahoo's game-status text.
    'Q3 5:12 vs Atl' -> 0.66 · 'Half' -> 0.5 · 'End Q1' -> 0.25 · 'OT' -> 0.97 ·
    'Final W 35-14' -> 1.0 · a future kickoff ('Sun 1:00 pm') -> None."""
    g = (game or '').strip()
    if g.startswith('Final'): return 1.0
    m = re.match(r'^(?:End\s+)?Q([1-4])(?:\s+(\d{1,2}):(\d{2}))?', g)
    if m:
        q = int(m.group(1))
        if m.group(2) is None: return q / 4.0                      # 'End Q3'
        left = int(m.group(2)) + int(m.group(3)) / 60.0
        return round(((q - 1) * 15 + (15 - left)) / 60.0, 4)
    if g.lower().startswith('half'): return 0.5
    if g.startswith('OT'): return 0.97
    return None

def sync():
    if os.environ.get('FFDATA_IN_ACTION'):
        # running inside the pump's own workflow: the checkout IS the repo
        head = subprocess.run(['git', '-C', CLONE, 'log', '-1', '--format=%cI %s'], capture_output=True, text=True).stdout.strip()
        return head + ' (in-action, no pull)'
    if os.path.isdir(os.path.join(CLONE, '.git')):
        subprocess.run(['git', '-C', CLONE, 'pull', '-q', '--ff-only'], check=True, timeout=120)
    else:
        subprocess.run(['git', 'clone', '-q', '--depth', '1', REPO, CLONE], check=True, timeout=180)
    head = subprocess.run(['git', '-C', CLONE, 'log', '-1', '--format=%cI %s'], capture_output=True, text=True).stdout.strip()
    return head

def rows(path):
    return list(csv.DictReader(open(path))) if os.path.exists(path) else []

def main():
    head = sync()
    src = os.path.join(CLONE, 'data')
    # the week is the PUMP's week (what the files on disk describe), not the calendar's:
    # on Tuesday morning the calendar rolls at 7 am while the newest pull may be from
    # 2:49 am with week-3 files (09-29). Building week-4 games and matchups from a
    # week-3 pull emptied the schedule and broke every DEF line.
    week = int(sys.argv[sys.argv.index('--week') + 1]) if '--week' in sys.argv else None
    if week is None:
        try:
            first = open(os.path.join(src, 'yahoo', 'pulled.txt')).readline()
            m = re.search(r'week (\d+)', first); week = int(m.group(1)) if m else None
        except Exception: week = None
    if week is None: week = C.nfl_week()
    log = [f'# ffdata pull loaded {C.stamp()} — repo head: {head}', f'week {week}']
    os.makedirs(D + 'pulls', exist_ok=True)

    # ---- Kalshi: full pull, verbatim
    k = os.path.join(src, 'kalshi.csv')
    kr = rows(k)
    if len(kr) >= 200:
        shutil.copy(k, D + 'kalshi.csv')
        for f in ('kalshi.csv.fits.pkl',):
            if os.path.exists(D + f): os.remove(D + f)
        evs = {r['event'] for r in kr}
        log.append(f'kalshi.csv: {len(kr)} markets, {len(evs)} events, pulled {kr[0]["pulled_at"]}')
    else:
        log.append(f'kalshi.csv: NOT installed — pump file has {len(kr)} rows (<200)')

    # ---- Kalshi archive: every pull the pump made (line movement, inactives)
    os.makedirs(D + 'kalshi_archive', exist_ok=True); n_arch = 0
    for f in sorted(os.listdir(os.path.join(src, 'archive'))) if os.path.isdir(os.path.join(src, 'archive')) else []:
        dst = D + 'kalshi_archive/' + f
        if f.startswith('kalshi_') and not os.path.exists(dst): shutil.copy(os.path.join(src, 'archive', f), dst); n_arch += 1
    log.append(f'kalshi_archive: {n_arch} new pull(s) copied, {len(os.listdir(D + "kalshi_archive"))} on disk')

    # ---- game schedule + lines: the look-ahead file carries every kickoff for the
    #      week; ESPN rows (when the pump got any) overlay their lines on top. The
    #      market's own lines come from Kalshi inside Projections and override both.
    fn = 'lines_wk3_9.csv' if week <= 9 else 'lines_wk10_18.csv'
    base = {}
    for r in rows(D + fn):
        if r['week'] == str(week):
            base[(r['away'], r['home'])] = dict(event_id=r['event_id'], away=r['away'], home=r['home'], kickoff=r['kickoff'],
                                                spread_team=r['favorite'], spread=r['spread'], over_under=r['over_under'],
                                                over_odds='', under_odds='', away_ml='', home_ml='', src='lookahead')
    e = os.path.join(src, 'espn_games.csv'); n_espn = 0
    for r in rows(e):
        k = (r['away'], r['home'])
        if r.get('over_under') and (k in base or r['kickoff'][:7] == C.week_start(week).strftime('%Y-%m')):
            base[k] = dict(base.get(k, {}), **{kk: r[kk] for kk in ('event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under', 'over_odds', 'under_odds', 'away_ml', 'home_ml')}, src='espn'); n_espn += 1
    if base:
        with open(D + 'espn_games.csv', 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under',
                                               'over_odds', 'under_odds', 'away_ml', 'home_ml', 'src'])
            w.writeheader(); w.writerows(base.values())
        log.append(f'espn_games.csv: {len(base)} games for week {week} — {n_espn} with ESPN lines from the pump, {len(base) - n_espn} schedule-only from {fn}; Kalshi spread/total ladders supply the lines inside the engine')
    else:
        log.append('espn_games.csv: NOT written — no schedule rows for this week')

    # ---- Sleeper projections
    for kind in ('off', 'idp'):
        p = os.path.join(src, 'sleeper', f'sleeper_{kind}_wk{week}.csv'); n = len(rows(p))
        if n >= (100 if kind == 'off' else 50):
            shutil.copy(p, D + f'sleeper_{kind}_wk{week}.csv'); log.append(f'sleeper_{kind}_wk{week}.csv: {n} rows')
        else:
            log.append(f'sleeper_{kind}_wk{week}.csv: NOT installed ({n} rows)')

    # ---- trending adds
    tp = os.path.join(src, 'sleeper', 'trending.csv'); t = rows(tp)
    if t and 'kind' in t[0]:
        shutil.copy(tp, D + 'trending_adds.csv')      # adds AND drops, with the kind column breakout._trending reads
        log.append(f'trending_adds.csv: {sum(1 for r in t if r["kind"] == "add")} adds / {sum(1 for r in t if r["kind"] == "drop")} drops (48h)')

    # ---- last week's usage (realized stats); the pump writes stats for the week it ran in,
    #      so these appear once the pump pulls W-1 (workflow v2). Install only when non-empty.
    for pos in ('QB', 'RB', 'WR', 'TE'):
        for wk in (week - 1, week):
            p = os.path.join(src, 'sleeper', f'stats_wk{wk}_{pos}.csv'); n = len(rows(p))
            if n >= 20:
                shutil.copy(p, D + f'usage_wk{wk}_{pos}.csv'); log.append(f'usage_wk{wk}_{pos}.csv: {n} rows')
    if not any(l.startswith('usage_wk') for l in log):
        log.append(f'usage: no non-empty stats file for week {week - 1} in the pump (workflow pulls the current week; v2 pulls W-1)')

    # ---- Yahoo (pump v5): every roster, the week's matchup, the transactions log
    from lib import state as ST
    import json
    ydir = os.path.join(src, 'yahoo')
    LG = {'BSB': dict(me='OVERKILL'), 'HH': dict(me='Tecmo Bowlers')}
    for lg, cfg in LG.items():
        rr = rows(os.path.join(ydir, f'{lg}_rosters.csv'))
        if not rr:
            log.append(f'{lg}: no rosters in the pump'); continue
        ts = rr[0]['pulled_at']
        latest = ST.latest(lg)
        owners = sorted({r['owner'] for r in rr})
        srows = [dict(owner=r['owner'], manager=r['owner'], slot=r['slot'], player=r['player'], pos=r['pos'],
                      nfl=r['nfl'], designation=(r['status'] or 'none')) for r in rr if r['player']]
        recs = {r['owner']: dict(record=r['record'], rank=r['rank']) for r in rr}
        if latest is None or latest.pulled < ts:
            ST.save(lg, srows, ts, note=f'pump v5 Yahoo pull {ts}: all {len(owners)} rosters, tags from the team pages', others_pulled=ts, records=recs)
            log.append(f'{lg} rosters: {len(srows)} players on {len(owners)} teams, pulled {ts} -> new snapshot')
        else:
            log.append(f'{lg} rosters: pump pull {ts} is not newer than the snapshot on disk ({latest.pulled})')
        # Yahoo projections for every rostered player (the points-only fallback)
        with open(D + f'yahoo_{lg}_wk{week}.csv', 'w', newline='') as fh:
            w = csv.writer(fh); w.writerow(['player', 'tm', 'pos', 'pts'])
            for r in rr:
                if r['player'] and r['proj_pts'] not in ('', '–', '-'): w.writerow([r['player'], r['nfl'], r['pos'], r['proj_pts']])
        # matchup: opponent on file + finals as actuals
        mr = rows(os.path.join(ydir, f'{lg}_matchup_wk{week}.csv'))
        if mr:
            opp = next((r['owner'] for r in mr if r['side'] == 'opp'), None)
            mp = D + 'matchups.json'
            mj = json.load(open(mp)) if os.path.exists(mp) else {}
            mj.setdefault(str(week), {})[lg] = opp
            mj['_src'] = (mj.get('_src', '') + f' | wk{week} {lg} from the pump {ts}')[-600:]
            json.dump(mj, open(mp, 'w'), indent=1)
            # finals AND games in progress: a live number plus the fraction played
            scored = [(r, game_frac(r['game'])) for r in mr if r['fan_pts'] not in ('', '–', '-') and game_frac(r['game']) is not None]
            finals = [r for r, f in scored if f >= 1.0]
            live = [r for r, f in scored if f < 1.0]
            os.makedirs(D + 'actuals', exist_ok=True)
            with open(D + f'actuals/{lg}_wk{week}.csv', 'w', newline='') as fh:
                w = csv.writer(fh); w.writerow(['owner', 'slot', 'player', 'tm', 'status', 'pts', 'final', 'frac'])
                for r, f in scored: w.writerow([r['owner'], r['slot'], r['player'], r['nfl'], r['game'], r['fan_pts'], 1 if f >= 1.0 else 0, f])
            tot = {r['side']: r['total'] for r in mr}
            log.append(f'{lg} matchup wk{week}: vs {opp}; {len(finals)} final rows, {len(live)} in progress; totals me {tot.get("me")} opp {tot.get("opp")}')
        # transactions -> the FAB log (BSB) / the HH log, merged and deduped
        tr = rows(os.path.join(ydir, f'{lg}_transactions.csv'))
        if tr:
            import re as _re
            def when(s):
                try: return dt.datetime.strptime(s + ' 2026', '%b %d, %I:%M %p %Y').strftime('%Y-%m-%d %H:%M')
                except Exception: return s
            path = D + ('bsb_transactions.csv' if lg == 'BSB' else 'hh_transactions.csv')
            old = [r for r in rows(path) if 'action' in r and 'datetime' in r]      # an older log with another shape is not merged
            seen = {(r['datetime'], r['team'], r['player'], r['action']) for r in old}
            new_rows = []
            for r in tr:
                m = _re.match(r'\$(\d+) Waiver', r['kind'])
                rec = dict(datetime=when(r['ts']), team=r['team'], action='Add' if r['action'] == 'add' else 'Drop', player=r['player'],
                           pos=r['pos'], nfl=r['nfl'], bid=(m.group(1) if m else ''), note=('Waiver' if m else r['kind']))
                k = (rec['datetime'], rec['team'], rec['player'], rec['action'])
                if k not in seen: seen.add(k); new_rows.append(rec)
            allr = sorted(old + new_rows, key=lambda r: r['datetime'], reverse=True)
            with open(path, 'w', newline='') as fh:
                w = csv.DictWriter(fh, fieldnames=['datetime', 'team', 'action', 'player', 'pos', 'nfl', 'bid', 'note']); w.writeheader(); w.writerows(allr)
            log.append(f'{lg} transactions: {len(new_rows)} new of {len(tr)} on the page; log now {len(allr)} rows')

    open(D + 'pulls/ffdata_pull.md', 'w').write('\n'.join(log) + '\n')
    print('\n'.join(log))

if __name__ == '__main__':
    main()
