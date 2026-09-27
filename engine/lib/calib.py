"""CALIBRATION — how far each source's number lands from the actual, by position.

Every run logs, for every rostered player in each league, the pregame number
each source gives him under the league's own scoring:

  engine   the blended line the card uses (Kalshi/props over Sleeper)
  sleeper  the Sleeper-only line (no market override)
  yahoo    Yahoo's own projection off the matchup page (when on file)

data/proj_log/{LG}_wk{W}.csv, one row per player. A row locks at his kickoff so
the number scored is the last PREGAME one, never a post-hoc one. When Yahoo's
actuals for the week land (final rows in data/actuals/, exact league scoring —
only the two rosters on the matchup page, which is the honest limit of the
sample), the report joins them and gives n, mean absolute error and bias per
source and position, cumulative over the season.

What it is for: the blend stays market-first by doctrine, but a source that is
measurably worse at a position (a fitted ladder at TE, say) should lose its
override there once the sample says so. Until three weeks are in, this is a
report, not a weight. Week 2 (HH) is back-filled from the engine's saved week-2
projections; it carries engine numbers only.
"""
import csv, os, json
from collections import defaultdict
from . import score as SC, clock as C, actuals as AC
from .names import key

D = '/home/claude/bsb2/data/proj_log/'
FIELDS = ['key', 'player', 'owner', 'pos', 'tm', 'slot', 'engine', 'sleeper', 'yahoo', 'kalshi_fields', 'kick', 'locked', 'post', 'logged']

def _read(p):
    return {r['key']: r for r in csv.DictReader(open(p))} if os.path.exists(p) else {}

def log(state, proj, week):
    """Merge this run's pregame numbers into the week's log; rows past kickoff stay as they were."""
    os.makedirs(D, exist_ok=True)
    p = D + f'{state.league}_wk{week}.csv'
    old = _read(p)
    now = C.now(); out = {}
    for r in state.rows:
        if r['slot'] == 'IR': continue
        prev = old.get(r['key'])
        kick = proj.kickoff(r['tm'])
        if prev and prev.get('locked') == '1':
            out[r['key']] = prev; continue
        L = proj.line(r['key'], r['pos'], r['tm'])
        Ls = proj.line(r['key'], r['pos'], r['tm'], market=False)
        eng = SC.points(L, state.league) if not L.get('unknown') else None
        slp = SC.points(Ls, state.league) if not Ls.get('unknown') and 'sleeper' in Ls['sources'] else None
        yh = (proj.yahoo.get(r['key']) or {}).get(state.league)
        kf = ','.join(f for f in ('rec', 'rec_yd', 'rush_yd', 'pass_yd', 'pass_td', 'td') if f in (L.get('prov') or {}))
        locked = bool(kick and kick <= now)
        # first seen after his kickoff: not a pregame number, never scored
        post = '1' if (locked and not prev) else (prev.get('post', '0') if prev else '0')
        out[r['key']] = dict(key=r['key'], player=r['player'], owner=r['owner'], pos=r['pos'], tm=r['tm'], slot=r['slot'],
                             engine='' if eng is None else f'{eng:.2f}', sleeper='' if slp is None else f'{slp:.2f}',
                             yahoo='' if yh is None else f'{yh:.2f}', kalshi_fields=kf,
                             kick=C.iso(kick) if kick else '', locked='1' if locked else '0', post=post, logged=C.iso())
    for k, r in old.items():                      # players who left the league keep their row
        out.setdefault(k, r)
    with open(p, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader(); w.writerows(out.values())
    return p, len(out)

def _backfill_hh_wk2():
    """Engine-only rows for HH week 2 from the saved projection json (before the log existed)."""
    p = '/home/claude/bsb2/data/hh_proj_wk2.json'
    if not os.path.exists(p): return {}
    j = json.load(open(p))
    return {k: dict(key=k, player=v.get('name', k), pos=v.get('pos', ''), engine=v.get('pts'), sleeper=None, yahoo=None) for k, v in j.items()}

def report(week):
    """-> dict(rows=[{league, pos, source, n, mae, bias}], weeks=[...], n_total, note)"""
    rows = []; weeks = set(); n_total = 0
    err = defaultdict(list)          # (league, pos, source) -> [(proj - actual)]
    for lg in ('BSB', 'HH'):
        for w in range(1, week + 1):
            act = AC.load(lg, w)
            act = {k: a for k, a in act.items() if a['final']}
            if not act: continue
            logp = D + f'{lg}_wk{w}.csv'
            plog = {r['key']: r for r in csv.DictReader(open(logp))} if os.path.exists(logp) else {}
            if not plog and lg == 'HH' and w == 2: plog = _backfill_hh_wk2()
            if not plog: continue
            used = False
            for k, a in act.items():
                r = plog.get(k)
                if not r or r.get('post') == '1': continue
                pos = _fam(r.get('pos', ''))
                for src in ('engine', 'sleeper', 'yahoo'):
                    v = r.get(src)
                    if v in (None, ''): continue
                    err[(lg, pos, src)].append(float(v) - a['pts']); used = True
            if used: weeks.add((lg, w))
    for (lg, pos, src), e in sorted(err.items()):
        n = len(e); mae = sum(abs(x) for x in e) / n; bias = sum(e) / n
        rows.append(dict(league=lg, pos=pos, source=src, n=n, mae=mae, bias=bias))
        if src == 'engine': n_total += n
    # per-league, all positions
    for lg in ('BSB', 'HH'):
        for src in ('engine', 'sleeper', 'yahoo'):
            e = [x for (l, p, s), es in err.items() if l == lg and s == src for x in es]
            if e: rows.append(dict(league=lg, pos='ALL', source=src, n=len(e), mae=sum(abs(x) for x in e) / len(e), bias=sum(e) / len(e)))
    note = ('Yahoo actuals cover the two rosters on each matchup page, so the sample is those players only; '
            'errors are in each league\'s own points. Under three weeks, a report, not a weight.')
    return dict(rows=rows, weeks=sorted(weeks), n_total=n_total, note=note)

def _fam(pos):
    p = (pos or '').split(',')[0].strip().upper()
    return {'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB'}.get(p, p)

def fmt(rep):
    L = ['CALIBRATION — projection error vs Yahoo actuals (pregame numbers, league scoring)']
    if not rep['rows']: L.append('  no week with both a projection log and final actuals yet'); return '\n'.join(L)
    L.append('  weeks: ' + ', '.join(f'{lg} wk{w}' for lg, w in rep['weeks']) + f' · {rep["n_total"]} scored player-weeks')
    L.append(f"  {'league':6} {'pos':4} {'source':8} {'n':>4} {'MAE':>6} {'bias':>6}")
    for r in rep['rows']:
        L.append(f"  {r['league']:6} {r['pos']:4} {r['source']:8} {r['n']:4d} {r['mae']:6.2f} {r['bias']:+6.2f}")
    return '\n'.join(L)
