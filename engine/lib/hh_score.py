"""Heritage House WEEKLY scorer.

This is score.py from the draft model (claude/model/score.py in the project),
converted from season totals to a single game. It is deliberately NOT a fresh
implementation: the season board Caleb actually drafted from was built with
these constants and these modeled rates, and a weekly number that disagrees
with the board for modelling reasons rather than football reasons is exactly
the "every time I ask you a question you give a different answer" failure.

Two things carry over verbatim from the verified draft model:
  - the per-game yardage bonus integral (gamma survival at each threshold).
    Season code multiplied by 17 games; weekly code does not. Everything else
    about it is unchanged, including the position CVs.
  - the modeled first-down and 40+ rates. Sleeper DOES publish pass_fd/rush_fd/
    rec_fd, but they are not first-down counts: Josh Allen's pass_fd (23.42)
    exceeds his completions (19.81), which is impossible. Whatever rotowire
    means by that field, wiring it to a 0.2-per-first-down rule would be
    scoring a number whose units are unknown. The modeled rates stay.
"""
import math
from scipy.stats import gamma

# ---------------- per-game yardage bonuses (verbatim from bonus.py) ----------
CV = {'pass': 0.30, 'rush': 0.68, 'rec': 0.72}
TIERS = {'pass': [(100, 1.0), (200, 2.0), (300, 3.0)],
         'rush': [(85, 1.0), (100, 2.0), (125, 3.0)],
         'rec':  [(65, 1.0), (90, 2.0), (105, 3.0)]}

def game_bonus(mean_yards, kind):
    """Expected bonus points in ONE game for a player projected `mean_yards`."""
    if mean_yards is None or mean_yards <= 0.5:
        return 0.0
    cv = CV[kind]; k = 1.0 / (cv * cv)
    d = gamma(k, scale=mean_yards / k)
    return sum(pts * d.sf(thr) for thr, pts in TIERS[kind])

# ---------------- scoring constants (read off the settings page) ------------
PASS_ATT, COMP, INCOMP = 0.15, 0.7, -0.1
PASS_YD_PER_PT, PASS_TD, INTCEPT, QB_SACK = 50.0, 5.0, -1.5, -0.25
RUSH_ATT, RUSH_YD_PER_PT, RUSH_TD = 0.15, 20.0, 5.0
REC, REC_YD_PER_PT, REC_TD = 0.9, 12.0, 5.0
FIRST_DOWN, FUM = 0.2, -1.0
LONG_COMP, LONG_REC, LONG_RUN = 1.0, 2.0, 1.0

RUSH_FD_RATE = 0.21
REC_FD_RATE_WRTE, REC_FD_RATE_RB = 0.45, 0.30
LONG_COMP_RATE, LONG_REC_RATE, LONG_RUN_RATE = 0.0022, 0.0025, 0.0060

SOLO, ASSIST, IDP_SACK, IDP_INT = 3.0, 2.0, 4.0, 4.0
FF, FR, IDP_TD, PD, TFL = 2.0, 3.0, 7.0, 4.0, 2.0

DST_SACK, DST_INT, DST_FR, DST_TD, DST_TFL = 2.0, 2.0, 2.0, 6.0, 1.5
DST_3AND0, DST_4TH_STOP, DST_SAFETY, DST_BLOCK = 1.0, 4.0, 4.0, 4.0
AVG_TFL_G, AVG_3AND0_G, AVG_4TH_STOP_G = 6.0, 3.9, 0.5
AVG_SAFETY_G, AVG_BLOCK_G, YDS_TIER_AVG_G = 0.03, 0.05, 0.7
PA_TIERS = [(0,0,10.0),(1,6,7.0),(7,13,4.0),(14,20,1.0),
            (21,27,0.0),(28,34,-2.0),(35,200,-3.0)]

FG_MADE_DIST = {(0,19):0.01,(20,29):0.20,(30,39):0.27,(40,49):0.29,(50,99):0.23}
FG_PTS = {(0,19):1.5,(20,29):2.5,(30,39):3.5,(40,49):5.5,(50,99):7.0}
FG_MID = {(0,19):15,(20,29):25,(30,39):35,(40,49):45,(50,99):53}
PTS_PER_MADE_FG = (sum(FG_MADE_DIST[b]*FG_PTS[b] for b in FG_MADE_DIST)
                   + sum(FG_MADE_DIST[b]*FG_MID[b] for b in FG_MADE_DIST)/25.0)
XP_MADE = 0.5


def _f(r, k):
    try: return float(r.get(k) or 0)
    except (TypeError, ValueError): return 0.0


def pa_tier_ev(pa, sd=7.5):
    def cdf(x): return 0.5*(1+math.erf((x-pa)/(sd*math.sqrt(2))))
    return sum((cdf(hi+0.5)-cdf(lo-0.5))*p for lo, hi, p in PA_TIERS)


# ---------------- per-game scorers ------------------------------------------
def score_off(r, pos):
    """One game. r is a row of sleeper_off_wk2.csv."""
    att, cmp_ = _f(r,'pass_att'), _f(r,'pass_cmp')
    inc = _f(r,'pass_inc') or max(att-cmp_, 0.0)
    py, ptd = _f(r,'pass_yd'), _f(r,'pass_td')
    ra, ry, rtd = _f(r,'rush_att'), _f(r,'rush_yd'), _f(r,'rush_td')
    rec, recy, rectd = _f(r,'rec'), _f(r,'rec_yd'), _f(r,'rec_td')
    fd_rate = REC_FD_RATE_RB if pos == 'RB' else REC_FD_RATE_WRTE
    return (att*PASS_ATT + cmp_*COMP + inc*INCOMP
            + py/PASS_YD_PER_PT + ptd*PASS_TD
            + _f(r,'pass_int')*INTCEPT + _f(r,'pass_sack')*QB_SACK
            + ra*RUSH_ATT + ry/RUSH_YD_PER_PT + rtd*RUSH_TD
            + rec*REC + recy/REC_YD_PER_PT + rectd*REC_TD
            + (ra*RUSH_FD_RATE + rec*fd_rate)*FIRST_DOWN
            + py*LONG_COMP_RATE*LONG_COMP
            + ra*LONG_RUN_RATE*LONG_RUN
            + recy*LONG_REC_RATE*LONG_REC
            + _f(r,'fum_lost')*FUM
            + game_bonus(py,'pass') + game_bonus(ry,'rush') + game_bonus(recy,'rec'))


TFL_BASE_G = {'DL': 4.0/17, 'LB': 4.0/17, 'DB': 2.0/17}

def score_idp(r, fam):
    """One game. r is a row of sleeper_idp_wk2.csv. `fam` in DL/LB/DB.

    TFL: Sleeper publishes idp_tkl_loss, so unlike the season model this uses
    the SOURCED number and does not fall back to the modeled sack*1.5 + base.
    """
    tfl = r.get('tfl')
    tfl = _f(r,'tfl') if (tfl not in (None,'')) else _f(r,'sack')*1.5 + TFL_BASE_G[fam]
    return (_f(r,'solo')*SOLO + _f(r,'ast')*ASSIST + _f(r,'sack')*IDP_SACK
            + _f(r,'int')*IDP_INT + _f(r,'pd')*PD + _f(r,'ff')*FF
            + _f(r,'fr')*FR + _f(r,'def_td')*IDP_TD + tfl*TFL)


def score_k(r):
    return _f(r,'fgm')*PTS_PER_MADE_FG + _f(r,'xpm')*XP_MADE


def score_dst(r):
    base = (AVG_TFL_G*DST_TFL + AVG_3AND0_G*DST_3AND0 + AVG_4TH_STOP_G*DST_4TH_STOP
            + AVG_SAFETY_G*DST_SAFETY + AVG_BLOCK_G*DST_BLOCK + YDS_TIER_AVG_G)
    return (_f(r,'sack')*DST_SACK + _f(r,'int')*DST_INT + _f(r,'fum_rec')*DST_FR
            + _f(r,'def_td')*DST_TD + pa_tier_ev(_f(r,'pts_allow')) + base)


# ---------------- Yahoo eligibility -----------------------------------------
# For ROSTERED players Yahoo's own eligibility string is in hh_rosters.csv and is
# authoritative. For FREE AGENTS all we have is Sleeper's NFL position, so this
# map is a FLOOR on eligibility, never a ceiling: a Sleeper "DE" is certainly
# DL-eligible in Yahoo and may ALSO be LB-eligible. Any FA IDP recommendation
# that depends on the wider eligibility has to be verified on Yahoo first.
NFL_TO_YAHOO = {
    'DE':{'DL'}, 'DT':{'DL'}, 'NT':{'DL'}, 'DL':{'DL'},
    'LB':{'LB'}, 'OLB':{'LB'}, 'ILB':{'LB'}, 'MLB':{'LB'},
    'CB':{'CB','DB'}, 'S':{'S','DB'}, 'FS':{'S','DB'}, 'SS':{'S','DB'}, 'DB':{'DB'},
}

def yahoo_elig(pos_string):
    """'LB,DE' -> {'LB','DL'}; 'WR' -> {'WR'}."""
    out = set()
    for p in str(pos_string or '').replace('/', ',').split(','):
        p = p.strip().upper()
        if not p: continue
        out |= NFL_TO_YAHOO.get(p, {p})
    return out
