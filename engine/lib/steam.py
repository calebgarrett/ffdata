"""STEAM — what the market learned between pulls.

The pump archives every Kalshi pull (data/kalshi_archive/kalshi_<stamp>.csv).
Two things fall out of comparing them, both invisible to anyone reading a
projection site:

  * LINE MOVEMENT. A player's yardage or reception ladder that moved more than
    THRESH between the week's first pull and now is the market pricing news —
    a practice report, a role change, a quiet injury — before Yahoo's tag or
    Sleeper's number catches up. Medians are read straight off the ladders
    (no fitting), so the comparison is fast and assumption-free.
  * INACTIVES. Kalshi withdraws a player's markets when he is ruled out. A
    player whose game has not kicked off, who had ladders in the previous pull
    and has none now, is out (or about to be). On the Sunday 11:30 pull that is
    the inactive list, an hour before the 1:00 lock.

Only rostered players in the two leagues are reported; the rest is noise.
"""
import csv, glob, os, re, datetime as dt
from collections import defaultdict
from . import market as M, clock as C
from .names import key

ARCH = '/home/claude/bsb2/data/kalshi_archive/'
CUR = '/home/claude/bsb2/data/kalshi.csv'
THRESH = 0.15
YARDS = {'KXNFLRECYDS': 'rec yds', 'KXNFLRSHYDS': 'rush yds', 'KXNFLPASSYDS': 'pass yds'}
COUNTS = {'KXNFLREC': 'rec', 'KXNFLPASSTDS': 'pass TD'}

def _stamp(path):
    m = re.search(r'kalshi_(\d{4}-\d{2}-\d{2}T\d{4})Z', path)
    return dt.datetime.strptime(m.group(1), '%Y-%m-%dT%H%M').replace(tzinfo=dt.timezone.utc) if m else None

def pulls(week):
    """Archived pulls that belong to this NFL week, oldest first: [(time, path)]."""
    w0, w1 = C.week_start(week), C.week_start(week + 1)
    out = []
    for p in glob.glob(ARCH + 'kalshi_*.csv'):
        t = _stamp(p)
        if t and w0 <= t.astimezone(C.ET) < w1: out.append((t, p))
    return sorted(out)

def medians(path, in_week_events):
    """{(player_key, series): median} for every player ladder in the file."""
    byp = defaultdict(list)
    for r in csv.DictReader(open(path)):
        if r['event'] not in in_week_events or r['series'] not in (*YARDS, *COUNTS): continue
        t = r['title']
        if ':' not in t: continue
        byp[(key(t.split(':', 1)[0].strip()), r['series'])].append(r)
    out = {}
    for k, rows in byp.items():
        lad = M._clean_ladder(rows)
        if len(lad) < 2: continue
        med = M._median_from_sf([(s, p) for s, p in lad])
        if med is not None: out[k] = med
    return out

def scan(proj, states, week):
    """-> dict(baseline=(time,path)|None, previous=..., moves=[...], gone=[...], note=str)"""
    ps = pulls(week)
    res = dict(baseline=None, previous=None, moves=[], gone=[], note='')
    if not os.path.exists(CUR) or not ps:
        res['note'] = 'no archived pull for this week yet — movement needs two pulls'; return res
    evs = proj.in_week_events
    now = medians(CUR, evs)
    base_t, base_p = ps[0]
    # 'previous' = the newest archived pull that is older than the current file
    cur_t = None
    try:
        cur_t = dt.datetime.fromisoformat(next(csv.DictReader(open(CUR)))['pulled_at'].replace('Z', '+00:00'))
    except Exception: pass
    older = [(t, p) for t, p in ps if cur_t is None or t < cur_t - dt.timedelta(minutes=1)]
    prev_t, prev_p = older[-1] if older else (None, None)
    base = medians(base_p, evs)
    prev = medians(prev_p, evs) if prev_p else {}
    res['baseline'] = base_t; res['previous'] = prev_t
    # who matters: every rostered player in either league, with owner and whether he is MY starter
    who = {}
    for lg, st in states.items():
        for r in st.rows:
            who.setdefault(r['key'], []).append((lg, r['owner'], r['slot'], r['player'], r['tm']))
    kicked = set()
    for tm, kk in proj.kick.items():
        if kk and kk <= C.now(): kicked.add(tm)
    # ---- movement since the week's first pull (pregame only: an in-game ladder
    # tracks the box score, not the market's opinion)
    for k, series in now:
        if k not in who or (k, series) not in base: continue
        if who[k][0][4] in kicked: continue
        a, b = base[(k, series)], now[(k, series)]
        if a <= 0: continue
        pct = (b - a) / a
        if abs(pct) < THRESH or abs(b - a) < (2.0 if series in YARDS else 0.5): continue
        label = YARDS.get(series) or COUNTS.get(series)
        res['moves'].append(dict(key=k, series=series, stat=label, before=a, after=b, pct=pct,
                                 owners=who[k], mine=[(lg, slot) for lg, own, slot, _, _ in who[k] if own == states[lg].me]))
    res['moves'].sort(key=lambda m: -abs(m['pct']))
    # ---- ladders that vanished since the previous pull, games not yet kicked off
    had = defaultdict(set); have = defaultdict(set)
    for (k, s) in prev: had[k].add(s)
    for (k, s) in now: have[k].add(s)
    for k, ss in had.items():
        if k not in who or have.get(k): continue
        tm = who[k][0][4]
        if tm in kicked: continue
        res['gone'].append(dict(key=k, player=who[k][0][3], tm=tm, series=sorted(ss), owners=who[k],
                                mine=[(lg, slot) for lg, own, slot, _, _ in who[k] if own == states[lg].me]))
    return res

def fmt(res):
    L = ['STEAM — what the market learned between pulls']
    if res['note']: L.append('  ' + res['note']); return '\n'.join(L)
    L.append(f"  baseline {res['baseline'].astimezone(C.ET):%a %-I:%M %p} ET · previous pull {res['previous'].astimezone(C.ET):%a %-I:%M %p} ET · threshold {THRESH:.0%}" if res['previous'] else f"  baseline {res['baseline'].astimezone(C.ET):%a %-I:%M %p} ET · no earlier pull to compare for withdrawals")
    if not res['moves']: L.append('  no rostered player\'s ladder moved more than the threshold')
    for m in res['moves'][:20]:
        tag = ' <- YOURS ' + ', '.join(f'{lg} {s}' for lg, s in m['mine']) if m['mine'] else ''
        L.append(f"  {m['pct']:+5.0%}  {m['key']:24} {m['stat']:9} {m['before']:6.1f} -> {m['after']:6.1f}   {', '.join(f'{lg}:{o}' for lg, o, *_ in m['owners'])}{tag}")
    if res['gone']:
        L.append('  MARKETS WITHDRAWN since the previous pull (game not started — treat as OUT until Yahoo says otherwise):')
        for g in res['gone']:
            tag = ' <- YOURS ' + ', '.join(f'{lg} {s}' for lg, s in g['mine']) if g['mine'] else ''
            L.append(f"    {g['player']} ({g['tm']}) — had {', '.join(g['series'])}{tag}")
    return '\n'.join(L)
