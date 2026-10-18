"""STASH WATCH — free agents worth a roster spot LATER, invisible to the weekly producers.

A player with a real season number (the blend, or a usage-verified role) whose last two
played weeks project ZERO is hurt or suspended now. The depth producer cannot price him
(facts marks him O — no pulse) and the breakout scanner never sees him (no snaps). Yet
Rashee Rice (10-18) was exactly this: a WR1/2 role, hamstring, dropped by a manager who
needed the spot, free for anyone taking a longer view.

This module only LISTS them, with the evidence a person needs to verify the injury and
timeline (the registry add_yes is the second source that lets the planner act). It
never makes a call.
"""
import os, csv, json
from . import paths as _paths, clock as C
from .names import key
from .rules import roles_path

D = _paths.data('')
MIN_SEASON = {'QB': 200.0, 'RB': 110.0, 'WR': 110.0, 'TE': 80.0}          # BSB-scored season blend; a real role, not a body
N = 6
# a verified verdict in data/roles.json 'stash' ends the watch for that name:
#   season  — out for the season (Dart, Reed, Achane 10-18): never a stash
#   skip    — healthy but not a role (Mendoza behind Cousins), or back too late / too small a role (Brooks)
#   watch   — real role, return week known: stays on the list WITH the verified timeline
CLOSED = ('season', 'skip')

def verified(root=None):
    try: return (json.load(open(roles_path(root))).get('stash') or {})
    except (OSError, ValueError): return {}

def _week_proj(t):
    """{key: pts_ppr} for week t from the Sleeper files on disk, or None when no file."""
    out, found = {}, False
    for fn in (f'sleeper_off_wk{t}.csv', f'sleeper_wk{t}.csv'):
        p = D + fn
        if not os.path.exists(p): continue
        found = True
        for r in csv.DictReader(open(p)):
            try: out[key(r['player'])] = float(r.get('pts_ppr') or r.get('pts') or 0)
            except ValueError: pass
    return out if found else None

def scan(league, state, proj, week, season=None, n=N):
    """-> [dict(name, pos, tm, season, last_proj_week, weeks_zero, owned_elsewhere)] sorted by season value."""
    season = season or {}
    if not season: return []
    wk = {t: _week_proj(t) for t in range(max(1, week - 3), week + 1)}
    wk = {t: v for t, v in wk.items() if v is not None}
    if len(wk) < 2: return []
    rostered = set(state.roster_keys)
    ver = verified()
    out = []
    for k, v in season.items():
        if k in rostered: continue
        vv = ver.get(k) or {}
        if vv.get('verdict') in CLOSED: continue                                # a person already looked: season over / not a role
        pos = (v.get('pos') or '').upper(); fam = pos if pos in MIN_SEASON else None
        if fam is None: continue
        pts = v.get('pts') or 0.0
        if pts < MIN_SEASON[fam]: continue
        recent = sorted(wk)[-2:]
        if any((wk[t].get(k) or 0.0) > 0 for t in recent): continue          # he is projected: the wire sees him
        if all(k not in wk[t] for t in wk): continue                           # never in any weekly file: not a current NFL player
        last = max([t for t in wk if (wk[t].get(k) or 0.0) > 0] or [0])
        out.append(dict(key=k, name=v.get('name') or k, pos=pos, tm=v.get('tm') or '', season=round(pts, 1),
                        per_week=round(pts / 17.0, 1), last_proj_week=last or None,
                        weeks_zero=sum(1 for t in wk if (wk[t].get(k) or 0.0) <= 0),
                        verified=(dict(vv) if vv else None)))
    out.sort(key=lambda r: -r['season'])
    return out[:n]

def fmt(league, rows):
    if not rows: return f'STASH WATCH — {league}: nothing on the wire with a real season number and no current projection'
    L = [f'STASH WATCH — {league}: free agents with a real season number and NO projection in the last two weeks (hurt or suspended; verify before adding)']
    for r in rows:
        L.append(f"  {r['name']:24} {r['pos']:3} {r['tm']:4} season {r['season']:6.1f} ({r['per_week']:4.1f}/wk)  last projected wk {r['last_proj_week'] or '-'}  zero for {r['weeks_zero']} wk(s)")
        if r.get('verified'): L.append(f"      verified {r['verified'].get('as_of','')}: {r['verified'].get('why','')}")
    if any(not r.get('verified') for r in rows):
        L.append('  -> the engine cannot see WHY. Verify the injury/suspension and the return date; a verified role is a registry add_yes and the planner prices him.')
    return '\n'.join(L)
