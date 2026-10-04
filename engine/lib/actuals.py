"""ACTUALS — what a player already scored this week, in the league's own points.

Source: Yahoo's matchup page for the week, which shows each starter's and
bench player's fantasy points once his game is final (data/actuals/{league}_wk{W}.csv,
copied verbatim). A final number replaces the projection everywhere: in the
lineup (locked, no longer a decision), in the total, and in the win-probability
sampler (a constant, not a distribution). A game IN PROGRESS carries the live
score and the fraction played (`frac`, from Yahoo's quarter and clock): the
player counts as live points + projection x (1 - frac), and the sampler keeps
only the unplayed share of his spread. (09-26: the Sunday pulls every 30 min.)

Only teams whose matchup page was read carry actuals; other teams' finished
players still run on projections in the league-median simulation, which is a
stated approximation until all six matchup pages are read.
"""
from . import paths as _paths
import csv, os
from .names import key, team

D = _paths.data('actuals', '')

def load(league, week):
    p = D + f'{league}_wk{week}.csv'
    if not os.path.exists(p): return {}
    out = {}
    for r in csv.DictReader(open(p)):
        final = r.get('final', '1') in ('1', 'true', 'True')
        try: frac = float(r.get('frac') or (1.0 if final else 0.0))
        except ValueError: frac = 1.0 if final else 0.0
        if not final and frac <= 0: continue                    # nothing played yet: a projection, not an actual
        out[key(r['player'])] = dict(pts=float(r['pts']), status=r['status'], owner=r['owner'], tm=team(r['tm']),
                                     final=final, frac=1.0 if final else frac)
    return out

def blend(a, proj_pts):
    """The number to use for a player with an actual on file: the final score, or
    the live score so far plus the unplayed fraction of his projection."""
    if a['final']: return a['pts']
    return a['pts'] + (proj_pts or 0.0) * (1.0 - a['frac'])

def pulled_at(league, week):
    """When the matchup page behind this file was read: its pulled_at column (the
    loader writes it), else the loader's as-of record; None when the file carries
    no stamp — unknown, never the file's mtime (a git checkout resets every mtime)."""
    from . import ts as T
    p = D + f'{league}_wk{week}.csv'
    if not os.path.exists(p): return None
    st = [t for t in (T.try_ts(r.get('pulled_at'), 'pump') for r in csv.DictReader(open(p)) if r.get('pulled_at')) if t]
    if st: return max(st)
    from . import contract as CT
    return CT.file_as_of(f'actuals/{league}_wk{week}.csv', root=os.path.dirname(os.path.dirname(D.rstrip('/'))))[0]
