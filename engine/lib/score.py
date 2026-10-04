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

# ------------------------------------------------------------------ realized points
# (outcome ledger, 10-04) The same two rule books applied to what HAPPENED: a Sleeper
# stat line (data/sleeper/stats_wk{W}_{POS}.csv in the pump, or the engine's usage
# copies) -> league points. Projections integrate a bonus or a tier over a spread;
# an actual reads the tier the game landed in. What Sleeper's stats feed does not
# carry is stated, not invented: HH long-play bonuses (40+ comp/rec/run) and the HH
# DEF's TFL / 3-and-out / 4th-down-stop / yards-allowed terms stay at the draft
# model's modeled per-game rates; IDP is not in the stats pull at all (None).
# lib/outcomes.fidelity() measures this scorer against Yahoo's exact matchup-page
# points every week, so the error of the stand-in is a printed number.
FG_BAND_MID_BSB = {'fgm_0_19': 18.0, 'fgm_20_29': 25.0, 'fgm_30_39': 35.0, 'fgm_40_49': 45.0, 'fgm_50p': 53.0}

def _sf(r, k):
    try: return float(r.get(k) or 0)
    except (TypeError, ValueError): return 0.0

def actual(row, pos, league):
    """Realized league points from one Sleeper stat row. -> float, or None when the
    position is not scorable from the stats pull (IDP, or BSB IDP which does not exist)."""
    p = (pos or '').upper()
    f = lambda k: _sf(row, k)
    two = f('pass_2pt') + f('rush_2pt') + f('rec_2pt')
    if league == 'BSB':
        if p == 'DEF':
            v = f('sack') + f('int') * 2 + f('fum_rec') * 2 + f('def_td') * 6 + f('safe') * 4 + f('blk_kick') * 3
            pa = f('pts_allow')
            v += next(pts for lo, hi, pts in B.PA_TIERS if lo <= pa <= hi)
            return v
        if p == 'K':
            bands = sum(f(b) for b in FG_BAND_MID_BSB)
            yds = sum(f(b) * m for b, m in FG_BAND_MID_BSB.items()) if bands >= f('fgm') and f('fgm') else f('fgm') * B.FG_YDS_PER_MADE
            return yds / 10 + f('xpm') - max(f('xpa') - f('xpm'), 0)
        if p in ('QB', 'RB', 'WR', 'TE'):
            return B.offense(pass_yd=f('pass_yd'), pass_td=f('pass_td'), pass_int=f('pass_int'), rush_yd=f('rush_yd'),
                             rush_td=f('rush_td'), rec=f('rec'), rec_yd=f('rec_yd'), rec_td=f('rec_td'),
                             fum_lost=f('fum_lost'), two_pt=two)
        return None
    # HH
    if p == 'DEF':
        base = (H.AVG_TFL_G * H.DST_TFL + H.AVG_3AND0_G * H.DST_3AND0 + H.AVG_4TH_STOP_G * H.DST_4TH_STOP
                + H.YDS_TIER_AVG_G)
        pa = f('pts_allow')
        tier = next(pts for lo, hi, pts in H.PA_TIERS if lo <= pa <= hi)
        return (f('sack') * H.DST_SACK + f('int') * H.DST_INT + f('fum_rec') * H.DST_FR + f('def_td') * H.DST_TD
                + f('safe') * H.DST_SAFETY + f('blk_kick') * H.DST_BLOCK + tier + base)
    if p == 'K':
        bands = {'fgm_0_19': (0, 19), 'fgm_20_29': (20, 29), 'fgm_30_39': (30, 39), 'fgm_40_49': (40, 49), 'fgm_50p': (50, 99)}
        if sum(f(b) for b in bands) >= f('fgm'):
            fg = sum(f(b) * (H.FG_PTS[rng] + H.FG_MID[rng] / 25.0) for b, rng in bands.items())
        else:
            fg = f('fgm') * H.PTS_PER_MADE_FG
        return fg + f('xpm') * H.XP_MADE
    if p in ('QB', 'RB', 'WR', 'TE'):
        att, cmp_ = f('pass_att'), f('pass_cmp')
        py, ry, recy = f('pass_yd'), f('rush_yd'), f('rec_yd')
        ra, rec = f('rush_att'), f('rec')
        bonus = lambda y, kind: sum(pts for thr, pts in H.TIERS[kind] if y >= thr)
        return (att * H.PASS_ATT + cmp_ * H.COMP + max(att - cmp_, 0) * H.INCOMP
                + py / H.PASS_YD_PER_PT + f('pass_td') * H.PASS_TD + f('pass_int') * H.INTCEPT + f('pass_sack') * H.QB_SACK
                + ra * H.RUSH_ATT + ry / H.RUSH_YD_PER_PT + f('rush_td') * H.RUSH_TD
                + rec * H.REC + recy / H.REC_YD_PER_PT + f('rec_td') * H.REC_TD
                + (f('rush_fd') + f('rec_fd')) * H.FIRST_DOWN
                + py * H.LONG_COMP_RATE * H.LONG_COMP + ra * H.LONG_RUN_RATE * H.LONG_RUN + recy * H.LONG_REC_RATE * H.LONG_REC
                + f('fum_lost') * H.FUM + two * 2
                + bonus(py, 'pass') + bonus(ry, 'rush') + bonus(recy, 'rec'))
    return None
