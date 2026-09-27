"""NEXT MAN UP — who inherits the role when a starter goes out, and whether he
is on the wire.

The snap-share data already on disk orders every NFL depth chart (two weeks
blended, newest weighted double). For each of Caleb's starters and each of his
opponent's, the backup is the next man at the position on the same NFL team,
with his wire status in THIS league: free agent, on waivers (BSB), or owned.

Wired to the inactive scan (steam.gone: Kalshi withdrew a player's markets
before kickoff) and to Yahoo's O/D tags: when a starter is out and his backup
is a free agent, that is a Decide tile with the mechanics and the clean drop,
because in BSB a free agent is Caleb's until his game kicks off and nobody else
in the league is positioned for the 11:30 pull.

Offense only (QB/RB/WR/TE): IDP and DEF have no next-man logic worth trusting
from snap counts.
"""
from collections import defaultdict
from . import usage as U, clock as C
from .names import key

OFF = ('QB', 'RB', 'WR', 'TE')
OUT_TAGS = {'O', 'D', 'IR', 'IR-R', 'PUP', 'PUP-R', 'SUSP', 'NA', 'CEL'}

def _score(r):
    # RBs are ordered on touches, everyone else on snaps; the newest week counts double
    return (r['touch_share'] * 0.6 + r['snap_share'] * 0.4) if r['pos'] == 'RB' else r['snap_share']

def depth_charts(week):
    """{(tm, pos): [row, ...]} ordered starter-first, blended from the two newest usage pulls."""
    pulls = []
    for w in (week - 1, week - 2, week - 3):
        if w < 1: continue
        u = U.load(w)
        if u: pulls.append(u)
        if len(pulls) == 2: break
    if not pulls: return {}, None
    agg = defaultdict(lambda: defaultdict(float)); meta = {}
    weights = (2.0, 1.0)
    for wgt, u in zip(weights, pulls):
        for k, r in u.items():
            if r['pos'] not in OFF or not r['tm']: continue
            agg[(r['tm'], r['pos'])][k] += wgt * _score(r)
            meta[k] = dict(name=r['name'], tm=r['tm'], pos=r['pos'])
    charts = {}
    for tp, d in agg.items():
        tot = sum(weights[:len(pulls)])
        charts[tp] = sorted([dict(meta[k], key=k, share=v / tot) for k, v in d.items()], key=lambda x: -x['share'])
    return charts, pulls[0][next(iter(pulls[0]))]['week']

def backups(charts, r, n=2):
    """The next `n` men behind roster row `r` on his NFL depth chart (same team, same position)."""
    ch = charts.get((r['tm'], r['pos'])) or []
    idx = next((i for i, x in enumerate(ch) if x['key'] == r['key']), None)
    if idx is None:
        # not in the usage data (did not play the last two weeks): the chart top is the man
        return ch[:n]
    return ch[idx + 1: idx + 1 + n]

def _where(k, state, wire, waived):
    if k in waived: return 'waivers', f'on waivers (dropped {waived[k]})'
    o = state.owner_of(k)
    if o == state.me: return 'mine', 'on your bench'
    if o: return 'owned', f'owned by {o}'
    if k in wire.pool: return 'fa', 'free agent'
    return 'unknown', 'not in the pool (no projection)'

def scan(state, proj, wire, lineup, steam, week, opp=None, drops=None, waived=None):
    """-> dict(rows=[...], alerts=[...], usage_week, note)
    rows: one per starter of mine and my opponent's (offense): starter, status, backups with wire status.
    alerts: starters who are OUT now (tag or withdrawn market) whose backup is a free agent."""
    charts, uwk = depth_charts(week)
    waived = waived or {}
    res = dict(rows=[], alerts=[], usage_week=uwk, note='')
    if not charts:
        res['note'] = 'no usage pull on disk — depth charts unavailable'; return res
    gone = {g['key'] for g in (steam or {}).get('gone', [])}
    sides = [('you', state.me)] + ([('opponent', opp)] if opp else [])
    for side, owner in sides:
        for r in state.by_owner.get(owner, []):
            if r['slot'] in ('BN', 'IR') or r['pos'] not in OFF: continue
            kick = proj.kickoff(r['tm'])
            if kick and kick <= C.now(): continue                       # already playing or played
            status = 'OUT (Kalshi withdrew his markets)' if r['key'] in gone else \
                     f'{r["designation"]}' if r['designation'] in OUT_TAGS else \
                     f'{r["designation"]}' if r['designation'] in ('Q',) else 'active'
            out_now = r['key'] in gone or r['designation'] in OUT_TAGS
            bks = []
            for b in backups(charts, r):
                w, txt = _where(b['key'], state, wire, waived)
                L = proj.line(b['key'], b['pos'], b['tm'])
                from . import score as SC
                pts = SC.points(L, state.league) if not L.get('unknown') else None
                bks.append(dict(b, where=w, where_txt=txt, pts=pts))
            row = dict(side=side, owner=owner, slot=r['slot'], player=r['player'], key=r['key'], tm=r['tm'], pos=r['pos'],
                       status=status, out=out_now, kick=kick, backups=bks)
            res['rows'].append(row)
            if side == 'you' and out_now:
                fa = next((b for b in bks if b['where'] == 'fa'), None)
                mine = next((b for b in bks if b['where'] == 'mine'), None)
                d = drops[0] if drops else None
                res['alerts'].append(dict(row=row, fa=fa, mine=mine, drop=(d['row']['player'] if d else None),
                                          drop_why=(d['why'] if d else None)))
    return res

def mechanics(league, kick):
    lock = f' — his game locks {kick:%a %-I:%M %p} ET' if kick else ''
    if league == 'HH': return 'free agent, immediate; counts 1 of 7 weekly acquisitions' + lock
    return 'free agent until kickoff (never-rostered players do not sit on waivers)' + lock

def fmt(res, league):
    L = [f'NEXT MAN UP — {league}' + (f' (depth charts from week-{res["usage_week"]} usage, two pulls blended)' if res.get('usage_week') else '')]
    if res['note']: L.append('  ' + res['note']); return '\n'.join(L)
    for a in res['alerts']:
        r = a['row']
        L.append(f"  !! {r['player']} ({r['slot']}) is {r['status']}: " + (f"{a['fa']['name']} is a FREE AGENT ({a['fa']['pts'] or 0:.1f} this week)" if a['fa'] else 'no backup on the wire') + (f"; drop {a['drop']}" if a['drop'] and a['fa'] else ''))
    for r in res['rows']:
        b = ' · '.join(f"{x['name']} {x['share']:.0%} ({x['where_txt']}{', ' + format(x['pts'], '.1f') if x['pts'] is not None else ''})" for x in r['backups']) or 'no backup in the usage data'
        L.append(f"  {r['side']:8} {r['slot']:7} {r['player']:24} {r['status']:12} -> {b}")
    return '\n'.join(L)
