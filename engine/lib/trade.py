"""TRADE MARKET — where the room's projections and the betting market disagree.

Caleb (09-17): other BSB managers are running the same AI. Their sessions are
fed consensus projections (Sleeper/Rotowire, ESPN, FantasyPros); ours is fed
Kalshi ladders and DraftKings lines. The market is the better forecaster, so
the gap between the two is a price disagreement we can trade into:

  SELL  a player of mine the projection rates well above the market: their AI
        will value him at the projection.
  BUY   a player of theirs the market rates well above the projection: their AI
        will let him go at the projection.

One week of lines is noisy (a game script, a bad matchup). So every week's
ratios are written to data/gaps/{league}_wk{W}.csv and the panel counts how
many weeks a player has sat on the same side of the line. Trade into the ones
that persist. Ratios are judged against the league-wide median that week, not
against 1.0: in week 2 Kalshi ran below Sleeper almost everywhere, and what
matters is who is far from the pack.
"""
import csv, os
from collections import defaultdict
from statistics import median
from . import score as SC
from .names import key

D = '/home/claude/bsb2/data/gaps/'
FIELD = {'WR': ('rec_yd', 'KXNFLRECYDS'), 'TE': ('rec_yd', 'KXNFLRECYDS'),
         'RB': ('rush_yd', 'KXNFLRSHYDS'), 'QB': ('pass_yd', 'KXNFLPASSYDS')}
SELL, BUY = 0.85, 1.15      # relative to the week's median ratio
MIN_LINE = 15               # ignore lines too small for the ratio to mean anything

def _ratios(state, proj):
    out = []
    for r in state.rows:
        pos = (r['pos'] or '').upper().split(',')[0]
        if pos not in FIELD: continue
        field, series = FIELD[pos]
        f = proj.kal.get((r['key'], series)); s = proj.off.get(r['key'])
        if not f or f['sse'] >= 0.05 or not s: continue
        try: sv = float(s.get(field) or 0)
        except ValueError: continue
        if sv < MIN_LINE or f['mean'] < 1: continue
        L = proj.line(r['key'], r['pos'], r['tm'])
        out.append(dict(key=r['key'], player=r['player'], owner=r['owner'], pos=pos, tm=r['tm'],
                        market=f['mean'], sleeper=sv, ratio=f['mean'] / sv, field=field,
                        week_pts=SC.points(L, state.league) if not L.get('unknown') else None,
                        starting=r['slot'] not in ('BN', 'IR')))
    return out

def _save(league, week, rows, med):
    os.makedirs(D, exist_ok=True)
    p = D + f'{league}_wk{week}.csv'
    with open(p, 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(['key', 'player', 'owner', 'pos', 'market', 'sleeper', 'ratio', 'rel', 'median'])
        for x in rows: w.writerow([x['key'], x['player'], x['owner'], x['pos'], f"{x['market']:.2f}", f"{x['sleeper']:.2f}", f"{x['ratio']:.4f}", f"{x['ratio']/med:.4f}", f"{med:.4f}"])

def _history(league, week):
    """{key: [(week, rel), ...]} for weeks before this one."""
    h = defaultdict(list)
    if not os.path.isdir(D): return h
    for fn in sorted(os.listdir(D)):
        if not fn.startswith(f'{league}_wk'): continue
        w = int(fn[len(league) + 3:-4])
        if w >= week: continue
        for r in csv.DictReader(open(D + fn)): h[r['key']].append((w, float(r['rel'])))
    return h

def scan(state, proj):
    """-> dict(sell=[...], buy=[...], med, n, week, note)"""
    rows = _ratios(state, proj)
    if len(rows) < 10: return dict(sell=[], buy=[], med=None, n=len(rows), week=proj.week, note='too few priced players to compare')
    med = median(x['ratio'] for x in rows)
    for x in rows: x['rel'] = x['ratio'] / med
    _save(state.league, proj.week, rows, med)
    hist = _history(state.league, proj.week)
    for x in rows:
        prior = hist.get(x['key'], [])
        side = 'sell' if x['rel'] <= SELL else 'buy' if x['rel'] >= BUY else None
        x['side'] = side
        x['weeks'] = 1 + sum(1 for _, rel in prior if (side == 'sell' and rel <= SELL) or (side == 'buy' and rel >= BUY)) if side else 0
        x['seen'] = 1 + len(prior)
    mine = state.me
    sell = sorted([x for x in rows if x['owner'] == mine and x['side'] == 'sell'], key=lambda x: (-x['weeks'], x['rel']))
    buy = sorted([x for x in rows if x['owner'] != mine and x['side'] == 'buy'], key=lambda x: (-x['weeks'], -x['rel']))
    # what their AI will want from me: my players the projection loves (chips), for context
    chips = sorted([x for x in rows if x['owner'] == mine and x['side'] == 'sell'], key=lambda x: x['rel'])
    return dict(sell=sell, buy=buy, chips=chips, med=med, n=len(rows), week=proj.week,
                note=(f'{len(rows)} rostered players priced by both Kalshi and Sleeper this week; league median market/projection = {med:.2f}. '
                      'A ratio is judged against that median. Weeks = consecutive weeks on the same side of the line (this week counts as 1).'))

def fmt(res, league):
    L = [f"TRADE MARKET — {league} — week {res['week']}: {res['note']}"]
    for side, rows in (('SELL (yours — projection above market; their AI values him at the projection)', res['sell']),
                       ('BUY (theirs — market above projection; their AI undervalues him)', res['buy'])):
        L.append('  ' + side)
        if not rows: L.append('    none this week')
        for x in rows[:8]:
            L.append(f"    {x['player']:22} {x['pos']:3} {x['owner'][:18]:18} {x['field']} market {x['market']:5.0f} vs sleeper {x['sleeper']:5.0f}  rel {x['rel']:.2f}  weeks {x['weeks']}/{x['seen']}" + ('  (starter)' if x['starting'] else ''))
    return '\n'.join(L)
