"""BSB scoring — read directly off /f1/156919/settings on 2026-09-15.
Not inferred from an archive note. Every value below was on the page.

  pass yds 1/20 · pass TD 6 · INT -2
  rush+rec yds 1/10 · rush/rec TD 6 · reception 1.0
  fumble lost -2 · 2pt 2 · return TD 6
  K: FG total yards 1/10, PAT +1/-1  (NO distance bands, NO FG-miss value shown)
  DEF: sack 1 · INT 2 · FR 2 · TD 6 · safety 4 · block 3 · XP returned 2
       PA 0:+10  1-6:+8  7-13:+6  14-20:+2  21-27:0  28-34:-2  35+:-6

Roster: QB / WR WR WR / RB RB / TE / W-R-T / K / DEF + 8 BN, NO IR SLOT.
Playoffs: 6 of 12, weeks 15-17, reseeding on.
"""
import math

FG_YDS_PER_MADE = 36.0   # calibrated against Yahoo over six kickers (35.0-36.9,
                         # pooled 36.01). Sleeper's own fgm_yds field is BROKEN --
                         # it reports ~26 yds/make, ~30% low, contradicting its own
                         # distance buckets. Never score K off fgm_yds.

PA_TIERS=[(0,0,10),(1,6,8),(7,13,6),(14,20,2),(21,27,0),(28,34,-2),(35,200,-6)]
PA_SD=9.5                # weekly points-allowed dispersion around the mean

def offense(pass_yd=0,pass_td=0,pass_int=0,rush_yd=0,rush_td=0,
            rec=0,rec_yd=0,rec_td=0,fum_lost=0,two_pt=0,ret_td=0):
    return (pass_yd/20 + pass_td*6 - pass_int*2
            + rush_yd/10 + rush_td*6
            + rec*1.0 + rec_yd/10 + rec_td*6
            - fum_lost*2 + two_pt*2 + ret_td*6)

def kicker(fgm=0,xpm=0,xp_miss=0):
    """FG scores on TOTAL YARDAGE at 1 point per 10 yards."""
    return fgm*FG_YDS_PER_MADE/10 + xpm*1.0 - xp_miss*1.0

def _phi(z): return 0.5*(1+math.erf(z/math.sqrt(2)))
def pa_points(mu,sd=PA_SD):
    """Expected points from the points-allowed tier for a defense projected to
    allow `mu` in this game. Integrating the tier over a distribution is not the
    same as reading the tier at the mean -- the tier is convex at the low end."""
    ev=0.0
    for lo,hi,pts in PA_TIERS:
        p=_phi((hi+0.5-mu)/sd)-_phi((lo-0.5-mu)/sd)
        ev+=max(p,0.0)*pts
    return ev

def defense(sack=0,intc=0,fr=0,td=0,safety=0,block=0,pa_mean=None,weeks=1):
    v=sack*1.0+intc*2+fr*2+td*6+safety*4+block*3
    if pa_mean is not None: v+=pa_points(pa_mean)*weeks
    return v

# magnitude bounds per WEEK in BSB scoring. Outside these, the input is garbage,
# not a bold projection -- re-pull, never report. (Gate G6.)
WEEK_BOUNDS={'QB':(2,55),'RB':(0,45),'WR':(0,45),'TE':(0,38),'K':(0,28),'DEF':(-8,32)}
SEASON_BOUNDS={'QB':(60,600),'RB':(0,420),'WR':(0,400),'TE':(0,330),
               'K':(60,260),'DEF':(-40,260)}

SLOTS=['QB','RB1','RB2','WR1','WR2','WR3','TE','W/R/T','K','DEF']
SLOT_ACCEPTS={'QB':{'QB'},'RB1':{'RB'},'RB2':{'RB'},'WR1':{'WR'},'WR2':{'WR'},
              'WR3':{'WR'},'TE':{'TE'},'W/R/T':{'WR','RB','TE'},'K':{'K'},'DEF':{'DEF'}}
SLOT_BASE={'RB1':'RB','RB2':'RB','WR1':'WR','WR2':'WR','WR3':'WR'}

# cannot be started; with NO IR slot in BSB these occupy a roster spot for nothing
from .rules import UNUSABLE, RISKY   # one vocabulary (lib/rules.py); RISKY = startable but needs a named contingency
