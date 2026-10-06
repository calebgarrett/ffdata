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

The input contract (lib/contract.py) runs on every pump file BEFORE it is installed:
a file that violates it is not installed and the load log names the code (C4: a
team page missing; C15: a '%' in a points column; C2: a stamp that does not parse;
C14: a matchup page whose rows are not its totals; C6: a defense without a team).
What the engine needs to judge its inputs later is installed beside them:
  data/yahoo/                     <- the raw Yahoo CSVs (rosters, this week's matchup, the
                                     transactions page, pulled.txt): team ids, game text
  data/asof.json                  <- per installed file, its as-of from CONTENT (pulled_at
                                     columns, pulled.txt, the pump's git history) — never mtime
  pulled_at column                <- appended to actuals/{lg}_wk{W}.csv and yahoo_{lg}_wk{W}.csv
  status column                   <- ESPN's game status, kept in espn_games.csv
Exit status 2 when any pump file was refused.
"""
import re, csv, os, sys, shutil, subprocess, datetime as dt
sys.path.insert(0, '/home/claude/bsb2')
from lib import clock as C, ts as T, contract as CT, rules as RU

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
    """Pump rows. Yahoo's display-points columns are blanked when they hold a percentage
    (Yahoo's in-game pages shift a '% started' figure into them, 10-04): the row itself —
    owner, slot, player, tag — is still the truth and is installed."""
    if not os.path.exists(path): return []
    out = list(csv.DictReader(open(path)))
    for r in out:
        for col in ('fan_pts', 'proj_pts'):
            if col in r and '%' in (r[col] or ''): r[col] = ''
    return out

def git_time(rel):
    """When the pump last CHANGED data/<rel> (its git history), ISO. In the Action's
    shallow checkout this is the head commit — the pull that just ran."""
    r = subprocess.run(['git', '-C', CLONE, 'log', '-1', '--format=%cI', '--', 'data/' + rel], capture_output=True, text=True)
    return r.stdout.strip() or None

def refuse_or_ok(kind, path, log, label, **kw):
    """Run the contract on one pump file; on any REFUSE log 'NOT installed — <codes>'."""
    vs = [v for v in CT.check_pump_file(kind, path, **kw) if v.severity == CT.REFUSE]
    if vs:
        log.append(f'{label}: NOT installed — contract ' + '; '.join(f'{v.code}: {v.msg}' for v in vs[:3]))
        REFUSED.extend(vs)
        return False
    return True

REFUSED = []

def adopt_runner_state(log):
    """Local runs only: the pump runner is the authoritative writer of the decision
    record (contract C17). When its engine/data ledger is newer than the local one,
    adopt its ledger, outcomes, projection log and plans before deciding here."""
    if os.environ.get('FFDATA_IN_ACTION'): return
    rd = os.path.join(CLONE, 'engine', 'data')
    if not os.path.isdir(rd) or os.path.realpath(rd) == os.path.realpath(D.rstrip('/')): return
    import json, shutil, glob as _g
    def newest(path):
        try:
            L = json.load(open(path)); ts = [T.try_ts(e.get(k), 'ledger') for e in L for k in ('ts', 'status_ts') if e.get(k)]
            ts = [t for t in ts if t]; return max(ts) if ts else None
        except Exception: return None
    a, b = newest(os.path.join(rd, 'ledger.json')), newest(D + 'ledger.json')
    if not a or (b and a <= b): return
    shutil.copy(D + 'ledger.json', D + 'ledger.local.bak.json') if os.path.exists(D + 'ledger.json') else None
    shutil.copy(os.path.join(rd, 'ledger.json'), D + 'ledger.json')
    n = 1
    for sub, pat in (('outcomes', '*.jsonl'), ('proj_log', '*.csv'), ('', 'plan*.json')):
        os.makedirs(os.path.join(D, sub), exist_ok=True)
        for f in _g.glob(os.path.join(rd, sub, pat)):
            shutil.copy(f, os.path.join(D, sub, os.path.basename(f))); n += 1
    bt = b.strftime('%Y-%m-%d %H:%M') if b else 'none'
    log.append(f'runner state adopted: the pump runner\'s ledger ({a:%Y-%m-%d %H:%M}) was newer than the local one ({bt}) — {n} files copied (C17)')

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
    adopt_runner_state(log)
    os.makedirs(D + 'pulls', exist_ok=True)
    ASOF = {}                      # data/asof.json: per installed file, as-of from content
    head_t = (head.split() or [''])[0]

    # ---- Kalshi: full pull, verbatim
    k = os.path.join(src, 'kalshi.csv')
    kr = rows(k)
    if len(kr) >= 200 and refuse_or_ok('kalshi', k, log, 'kalshi.csv'):
        shutil.copy(k, D + 'kalshi.csv')
        ASOF['kalshi.csv'] = dict(as_of=max(r['pulled_at'] for r in kr if r.get('pulled_at')), src='pulled_at column')
        for f in ('kalshi.csv.fits.pkl',):
            if os.path.exists(D + f): os.remove(D + f)
        evs = {r['event'] for r in kr}
        log.append(f'kalshi.csv: {len(kr)} markets, {len(evs)} events, pulled {kr[0]["pulled_at"]}')
    elif len(kr) < 200:
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
                                                over_odds='', under_odds='', away_ml='', home_ml='', status='', src='lookahead')
    e = os.path.join(src, 'espn_games.csv'); n_espn = 0
    espn_ok = refuse_or_ok('espn', e, log, 'espn_games.csv (pump rows)') if os.path.exists(e) else False
    for r in (rows(e) if espn_ok else []):
        k = (r['away'], r['home'])
        if r.get('over_under') and (k in base or r['kickoff'][:7] == C.week_start(week).strftime('%Y-%m')):
            base[k] = dict(base.get(k, {}), **{kk: r[kk] for kk in ('event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under', 'over_odds', 'under_odds', 'away_ml', 'home_ml')},
                           status=r.get('status', ''), src='espn'); n_espn += 1
    if base:
        with open(D + 'espn_games.csv', 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under',
                                               'over_odds', 'under_odds', 'away_ml', 'home_ml', 'status', 'src'])
            w.writeheader(); w.writerows(base.values())
        ASOF['espn_games.csv'] = dict(as_of=(git_time('espn_games.csv') if n_espn else None) or head_t,
                                      src='pump git: espn_games.csv' if n_espn else 'pump head (look-ahead schedule)')
        log.append(f'espn_games.csv: {len(base)} games for week {week} — {n_espn} with ESPN lines from the pump, {len(base) - n_espn} schedule-only from {fn}; Kalshi spread/total ladders supply the lines inside the engine')
    else:
        log.append('espn_games.csv: NOT written — no schedule rows for this week')

    # ---- Sleeper projections
    for kind in ('off', 'idp'):
        p = os.path.join(src, 'sleeper', f'sleeper_{kind}_wk{week}.csv'); n = len(rows(p))
        if n >= (100 if kind == 'off' else 50) and refuse_or_ok(f'sleeper_{kind}', p, log, f'sleeper_{kind}_wk{week}.csv'):
            shutil.copy(p, D + f'sleeper_{kind}_wk{week}.csv'); log.append(f'sleeper_{kind}_wk{week}.csv: {n} rows')
            ASOF[f'sleeper_{kind}_wk{week}.csv'] = dict(as_of=git_time(f'sleeper/sleeper_{kind}_wk{week}.csv') or head_t, src='pump git: last change')
        elif n >= (100 if kind == 'off' else 50):
            pass
        else:
            log.append(f'sleeper_{kind}_wk{week}.csv: NOT installed ({n} rows)')

    # ---- trending adds
    tp = os.path.join(src, 'sleeper', 'trending.csv'); t = rows(tp)
    if t and 'kind' in t[0]:
        shutil.copy(tp, D + 'trending_adds.csv')      # adds AND drops, with the kind column breakout._trending reads
        ASOF['trending_adds.csv'] = dict(as_of=git_time('sleeper/trending.csv') or head_t, src='pump git: last change')
        log.append(f'trending_adds.csv: {sum(1 for r in t if r["kind"] == "add")} adds / {sum(1 for r in t if r["kind"] == "drop")} drops (48h)')

    # ---- last week's usage (realized stats); the pump writes stats for the week it ran in,
    #      so these appear once the pump pulls W-1 (workflow v2). Install only when non-empty.
    for pos in ('QB', 'RB', 'WR', 'TE'):
        for wk in (week - 1, week):
            p = os.path.join(src, 'sleeper', f'stats_wk{wk}_{pos}.csv'); n = len(rows(p))
            if n >= 20:
                shutil.copy(p, D + f'usage_wk{wk}_{pos}.csv'); log.append(f'usage_wk{wk}_{pos}.csv: {n} rows')
                ASOF[f'usage_wk{wk}_{pos}.csv'] = dict(as_of=git_time(f'sleeper/stats_wk{wk}_{pos}.csv') or head_t, src='pump git: last change')
    if not any(l.startswith('usage_wk') for l in log):
        log.append(f'usage: no non-empty stats file for week {week - 1} in the pump (workflow pulls the current week; v2 pulls W-1)')

    # ---- Yahoo (pump v5): every roster, the week's matchup, the transactions log
    from lib import state as ST
    import json
    ydir = os.path.join(src, 'yahoo')
    os.makedirs(D + 'yahoo', exist_ok=True)
    if os.path.exists(os.path.join(ydir, 'pulled.txt')): shutil.copy(os.path.join(ydir, 'pulled.txt'), D + 'yahoo/pulled.txt')
    LG = {'BSB': dict(me='OVERKILL'), 'HH': dict(me='Tecmo Bowlers')}
    for lg, cfg in LG.items():
        rp = os.path.join(ydir, f'{lg}_rosters.csv')
        rr = rows(rp)
        if not rr:
            log.append(f'{lg}: no rosters in the pump'); continue
        ts = rr[0]['pulled_at']
        rost_ok = refuse_or_ok('rosters', rp, log, f'{lg} rosters (pump pull {ts})', league=lg)
        latest = ST.latest(lg)
        owners = sorted({r['owner'] for r in rr})
        srows = [dict(owner=r['owner'], manager=r['owner'], slot=r['slot'], player=r['player'], pos=r['pos'],
                      nfl=r['nfl'], designation=(r['status'] or 'none')) for r in rr if r['player']]
        recs = {r['owner']: dict(record=r['record'], rank=r['rank']) for r in rr}
        if not rost_ok:
            pass                                    # the team pages failed the contract: the snapshot on disk stands
        elif latest is None or latest.pulled < ts:
            ST.save(lg, srows, ts, note=f'pump v5 Yahoo pull {ts}: all {len(owners)} rosters, tags from the team pages', others_pulled=ts, records=recs)
            log.append(f'{lg} rosters: {len(srows)} players on {len(owners)} teams, pulled {ts} -> new snapshot')
        else:
            log.append(f'{lg} rosters: pump pull {ts} is not newer than the snapshot on disk ({latest.pulled})')
        # Yahoo projections for every rostered player (the points-only fallback)
        if rost_ok:
            shutil.copy(rp, D + f'yahoo/{lg}_rosters.csv')
            with open(D + f'yahoo_{lg}_wk{week}.csv', 'w', newline='') as fh:
                w = csv.writer(fh); w.writerow(['player', 'tm', 'pos', 'pts', 'pulled_at'])
                for r in rr:
                    if r['player'] and r['proj_pts'] not in ('', '–', '-', '—'): w.writerow([r['player'], r['nfl'], r['pos'], r['proj_pts'], ts])
            ASOF[f'yahoo_{lg}_wk{week}.csv'] = dict(as_of=ts, src='Yahoo pulled_at')
        # matchup: opponent on file + finals as actuals
        mp_ = os.path.join(ydir, f'{lg}_matchup_wk{week}.csv')
        mr = rows(mp_)
        if mr and not refuse_or_ok('matchup', mp_, log, f'{lg} matchup wk{week}', league=lg):
            mr = []
        if mr:
            shutil.copy(mp_, D + f'yahoo/{lg}_matchup_wk{week}.csv')
            mts = max(r['pulled_at'] for r in mr if r.get('pulled_at')) if any(r.get('pulled_at') for r in mr) else ts
            opp = next((r['owner'] for r in mr if r['side'] == 'opp'), None)
            mp = D + 'matchups.json'
            mj = json.load(open(mp)) if os.path.exists(mp) else {}
            mj.setdefault(str(week), {})[lg] = opp
            mj['_src'] = (mj.get('_src', '') + f' | wk{week} {lg} from the pump {mts}')[-600:]
            mj.setdefault('_pulled', {}).setdefault(str(week), {})[lg] = mts
            RU.atomic_write_json(mp, mj)
            # finals AND games in progress: a live number plus the fraction played
            scored = [(r, game_frac(r['game'])) for r in mr if r['fan_pts'] not in ('', '–', '-', '—') and game_frac(r['game']) is not None]
            finals = [r for r, f in scored if f >= 1.0]
            live = [r for r, f in scored if f < 1.0]
            os.makedirs(D + 'actuals', exist_ok=True)
            with open(D + f'actuals/{lg}_wk{week}.csv', 'w', newline='') as fh:
                w = csv.writer(fh); w.writerow(['owner', 'slot', 'player', 'tm', 'status', 'pts', 'final', 'frac', 'pulled_at'])
                for r, f in scored: w.writerow([r['owner'], r['slot'], r['player'], r['nfl'], r['game'], r['fan_pts'], 1 if f >= 1.0 else 0, f, r.get('pulled_at') or mts])
            ASOF[f'actuals/{lg}_wk{week}.csv'] = dict(as_of=mts, src='Yahoo matchup pulled_at')
            tot = {r['side']: r['total'] for r in mr}
            log.append(f'{lg} matchup wk{week}: vs {opp}; {len(finals)} final rows, {len(live)} in progress; totals me {tot.get("me")} opp {tot.get("opp")}')
        # transactions -> the FAB log (BSB) / the HH log, merged and deduped
        tp_ = os.path.join(ydir, f'{lg}_transactions.csv')
        tr = rows(tp_)
        if tr and not refuse_or_ok('transactions', tp_, log, f'{lg} transactions', league=lg):
            tr = []
        if tr:
            import re as _re
            shutil.copy(tp_, D + f'yahoo/{lg}_transactions.csv')
            tts = max(r['pulled_at'] for r in tr if r.get('pulled_at')) if any(r.get('pulled_at') for r in tr) else ts
            ref = T.try_ts(tts, 'pump')
            def when(s):
                # 'Oct 3, 8:39 pm' is Eastern; the year is the one that puts it at or
                # before the pull (a December page read in January is last year's)
                return T.parse_ts(s, 'yahoo_page', now=ref).strftime('%Y-%m-%d %H:%M')
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
            ASOF['bsb_transactions.csv' if lg == 'BSB' else 'hh_transactions.csv'] = dict(as_of=tts, src='Yahoo transactions page pulled_at')

    # ---- data/asof.json: what each installed file is AS OF, from content (merged:
    #      a file not re-installed keeps the as-of it was installed with)
    ap = D + 'asof.json'
    try: aj = json.load(open(ap)) if os.path.exists(ap) else {}
    except Exception: aj = {}
    aj.setdefault('files', {}).update({f: v for f, v in ASOF.items() if v.get('as_of')})
    aj['pump_week'] = week; aj['pump_head'] = head_t; aj['loaded'] = C.iso()
    RU.atomic_write_json(ap, aj)
    # ---- C1: the engine runs the week whose Sleeper file is on disk; it must be the pump's week
    ew = CT.data_week(os.path.dirname(D.rstrip('/')))
    if ew != week:
        REFUSED.append(CT.Violation('C1', CT.REFUSE, f'pump week {week} but the engine will run data week {ew}'))
        log.append(f'C1 REFUSE: the pump pulled week {week} but the engine data week is {ew} (sleeper_off_wk{week}.csv not installed) — ff.py run will refuse')
    if REFUSED:
        log.append('contract: ' + ', '.join(sorted({v.code for v in REFUSED})) + ' refused pump file(s) — see the NOT installed lines above')

    open(D + 'pulls/ffdata_pull.md', 'w').write('\n'.join(log) + '\n')
    print('\n'.join(log))
    return 2 if REFUSED else 0

if __name__ == '__main__':
    sys.exit(main())
