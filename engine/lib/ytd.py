"""REALIZED SEASON — what every player has actually scored this year, in league points.

Caleb (11-10): "dropping the vikings is crazy ... that's the best def in the league."
The planner had the Vikings at 7.2/wk rest-of-season and a free Eagles unit at 7.5,
and so read the cut as free. Both numbers were the PRESEASON blend ÷ 17. By week 10
the Vikings had scored 11.1 a game in BSB scoring — first in the league — and the
Eagles were not in the top sixteen. A preseason number is a prior; eight played
weeks are the evidence. This module turns the pump's realized stat lines
(data/usage_wk{t}_{POS}.csv, Sleeper's stats, every week on disk before W) into
league points with the same scorer the outcome ledger uses (score.actual), per
player: total, games, points per game. facts._ros blends it with the preseason
number by games played (a shrinkage prior, YTD_K games' worth of preseason).

IDP is not in the stats feed; an IDP keeps his preseason / usage number.
"""
import csv, os
from . import paths as _paths
from . import score as SC
from .names import key, team

POS = ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')
# games' worth of preseason prior per family: a defense's preseason rank is nearly
# noise (3 games of it); a skill player's preseason projection carries real role
# information (6 games of it). By week 10 a DEF is ~70% realized, a WR ~57%.
YTD_K = {'DEF': 3.0, 'K': 3.0, 'QB': 6.0, 'RB': 6.0, 'WR': 6.0, 'TE': 6.0}


def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0


def row_key(r, pos):
    if pos == 'DEF':
        tm = team(r.get('team') or r.get('player_id') or '')
        return f'DST:{tm}' if tm else None
    return key(f"{r.get('first_name', '')} {r.get('last_name', '')}".strip())


def load(league, week, root=None):
    """-> {key: dict(pts, gp, ppg, weeks, pos)} over every usage_wk{t}_{POS}.csv with t < week.
    Empty when no file is on disk. A row counts only when it is a played game (gp > 0)."""
    D = _paths.data('') if root is None else os.path.join(root, 'data') + '/'
    out = {}
    for t in range(1, int(week)):
        for pos in POS:
            p = D + f'usage_wk{t}_{pos}.csv'
            if not os.path.exists(p): continue
            try: rows = list(csv.DictReader(open(p)))
            except OSError: continue
            for r in rows:
                if _f(r.get('gp')) <= 0: continue
                k = row_key(r, pos)
                if not k: continue
                v = SC.actual(r, pos, league)
                if v is None: continue
                e = out.setdefault(k, dict(pts=0.0, gp=0, weeks=[], pos=pos))
                if t in e['weeks']: continue                    # a week counted once
                e['pts'] += float(v); e['gp'] += 1; e['weeks'].append(t)
    for e in out.values():
        e['ppg'] = e['pts'] / e['gp'] if e['gp'] else 0.0
    return out


def blend(pre_pw, y, fam):
    """Rest-of-season per-week value from the preseason per-week number and the realized
    record y (dict pts/gp) -> (value, text). Shrinkage: YTD_K[fam] games of prior."""
    k = YTD_K.get(fam)
    if not y or not y.get('gp') or k is None: return None
    n = float(y['gp']); ppg = float(y['pts']) / n
    if pre_pw is None: return None
    v = (n * ppg + k * float(pre_pw)) / (n + k)
    return v, f'{int(n)}-game realized {ppg:.1f}/g blended with preseason {float(pre_pw):.1f}/wk ({k:.0f}-game prior)'


def rank(ytd, fam, k):
    """1-based rank of key k among fam by points per game (>= 3 games), or None."""
    rows = sorted(((e['ppg'], kk) for kk, e in ytd.items() if e.get('pos') == fam and e.get('gp', 0) >= 3), reverse=True)
    for i, (_, kk) in enumerate(rows, 1):
        if kk == k: return i
    return None
