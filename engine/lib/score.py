"""ONE SCORER. points(line, league) for any player in either league.

BSB rules from lib/scoring.py (read off the settings page 2026-09-15).
HH rules from lib/hh_score.py (the draft model's own constants, per game).
Neither is re-implemented here; this only dispatches, and adds the two things
both leagues need computed the same way:

  boom  -- share of projected points from touchdowns and defensive big plays
           rather than volume. "Upside is more important than expected points
           on the bench." This is how a bench spot is judged.
  bounds check -- a number outside the league's per-position weekly bounds is
           a bad read, not a bold projection (gate G6).
"""
from . import scoring as B, hh_score as H
from .leagues import ALL

def points(line, league):
    """-> float, or None when the line is unknown."""
    if line.get('unknown'): return None
    if line.get('pts_override') is not None:          # Yahoo points-only fallback, league-scored by Yahoo
        return line['pts_override'].get(league)
    st, fam = line['stat'], line['fam']
    if league == 'BSB':
        if fam == 'DEF':
            return B.defense(sack=st['sack'], intc=st['int'], fr=st['fum_rec'], td=st['def_td'],
                             pa_mean=st['pts_allow'])
        if fam == 'K':
            return B.kicker(fgm=st['fgm'], xpm=st['xpm'])
        if fam in ('DL', 'LB', 'DB'):
            return None                       # BSB has no IDP
        return B.offense(pass_yd=st['pass_yd'], pass_td=st['pass_td'], pass_int=st['pass_int'],
                         rush_yd=st['rush_yd'], rush_td=st['rush_td'], rec=st['rec'],
                         rec_yd=st['rec_yd'], rec_td=st['rec_td'], fum_lost=st['fum_lost'])
    # HH
    if fam == 'DEF':
        return H.score_dst(dict(sack=st['sack'], int=st['int'], fum_rec=st['fum_rec'],
                                def_td=st['def_td'], pts_allow=st['pts_allow']))
    if fam == 'K':
        return H.score_k(dict(fgm=st['fgm'], xpm=st['xpm']))
    if fam in ('DL', 'LB', 'DB'):
        return H.score_idp(st, fam)
    return H.score_off(st, fam)

def boom(line, league):
    """Fraction of points from fat-tail categories. None when unknown."""
    if line.get('unknown'): return None
    if line.get('pts_override') is not None: return None   # points-only source: boom share unknown
    st, fam = line['stat'], line['fam']
    tot = points(line, league)
    if not tot or tot <= 0: return None
    if fam in ('DL', 'LB', 'DB'):
        if league != 'HH': return None
        vol = st['solo']*H.SOLO + st['ast']*H.ASSIST
        big = (st['sack']*H.IDP_SACK + st['int']*H.IDP_INT + st['pd']*H.PD + st['ff']*H.FF
               + st['fr']*H.FR + st['def_td']*H.IDP_TD + st['tfl']*H.TFL)
        return big / (vol + big) if vol + big > 0 else None
    if fam in ('DEF', 'K'): return None
    td_pts = (st['pass_td'] + st['rush_td'] + st['rec_td']) * (6.0 if league == 'BSB' else 5.0)
    return max(min(td_pts / tot, 1.0), 0.0)

def in_bounds(pts, fam, league, horizon='weekly'):
    cfg = ALL[league]
    lo, hi = (cfg.week_bounds if horizon == 'weekly' else cfg.season_bounds).get(fam, (-1e9, 1e9))
    return lo <= pts <= hi
