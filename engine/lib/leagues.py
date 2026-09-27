"""League rule sets. One config per league so the same engine, gate and card
serve both instead of two divergent pipelines — which is how the answers started
moving in the first place.

BSB scoring read off /f1/156919/settings 2026-09-15.
HH scoring read off the settings page and recorded in
claude/heritage-house-2026-league-profile.md (verified line by line).
"""
import math

def _phi(z): return 0.5*(1+math.erf(z/math.sqrt(2)))

class League:
    def __init__(self,**kw): self.__dict__.update(kw)
    def pa_points(self,mu,sd=9.5):
        ev=0.0
        for lo,hi,pts in self.pa_tiers:
            p=_phi((hi+0.5-mu)/sd)-_phi((lo-0.5-mu)/sd)
            ev+=max(p,0.0)*pts
        return ev

BSB = League(
    key='BSB', yahoo=156919, team=7, name='OVERKILL', managers=12,
    slots=['QB','RB1','RB2','WR1','WR2','WR3','TE','W/R/T','K','DEF'],
    accepts={'QB':{'QB'},'RB1':{'RB'},'RB2':{'RB'},'WR1':{'WR'},'WR2':{'WR'},
             'WR3':{'WR'},'TE':{'TE'},'W/R/T':{'WR','RB','TE'},'K':{'K'},'DEF':{'DEF'}},
    base={'RB1':'RB','RB2':'RB','WR1':'WR','WR2':'WR','WR3':'WR'},
    bench=8, ir_slots=0, acq_cap=None, fab=100,
    waivers='Wednesday morning', playoff_teams=6, playoff_weeks=(15,16,17),
    # Yahoo 'vs Median' is ON (seen 09-17 on the team page: 'Loss Week 1 vs Median',
    # record 0-2-0 after one week). Two results a week: head-to-head AND vs the
    # league median score. Half the record is pure scoring, no matchup luck.
    vs_median=True,
    ppr=1.0, pass_yd=20.0, pass_td=6, pass_int=-2, rush_yd=10.0, rush_td=6,
    rec_yd=10.0, rec_td=6, fum=-2, two_pt=2,
    fg_yds_per_made=36.0, xp=1.0,
    def_sack=1, def_int=2, def_fr=2, def_td=6, def_safety=4, def_block=3,
    pa_tiers=[(0,0,10),(1,6,8),(7,13,6),(14,20,2),(21,27,0),(28,34,-2),(35,200,-6)],
    idp=False,
    fam_slots={'QB':('QB',),'RB':('RB1','RB2','W/R/T'),'WR':('WR1','WR2','WR3','W/R/T'),
               'TE':('TE','W/R/T'),'K':('K',),'DEF':('DEF',)},
    week_bounds={'QB':(2,55),'RB':(0,45),'WR':(0,45),'TE':(0,38),'K':(0,28),'DEF':(-8,32)},
    season_bounds={'QB':(60,600),'RB':(0,420),'WR':(0,400),'TE':(0,330),'K':(60,260),'DEF':(-40,260)},
)

HH = League(
    key='HH', yahoo=824489, team=6, name='Tecmo Bowlers', managers=10,
    slots=['QB','WR','RB','TE','W/R','W/R/T','Q/W/R/T','K','DEF','D','DB','DL','LB','CB','S'],
    accepts={'QB':{'QB'},'WR':{'WR'},'RB':{'RB'},'TE':{'TE'},
             'W/R':{'WR','RB'},'W/R/T':{'WR','RB','TE'},'Q/W/R/T':{'QB','WR','RB','TE'},
             'K':{'K'},'DEF':{'DEF'},
             # Yahoo umbrella slots, VERIFIED (Help SLN6500/SLN6318):
             # DL takes DE/DT, DB takes CB/S, D takes any defender.
             # Narrow slots are EXACT MATCH — a DE does NOT fill LB.
             'D':{'LB','DL','DE','DT','DB','CB','S'},'DB':{'DB','CB','S'},
             'DL':{'DL','DE','DT'},'LB':{'LB'},'CB':{'CB'},'S':{'S'}},
    base={},
    bench=8, ir_slots=3, acq_cap=7, fab=None,
    waivers='1-day, rolling by standings; free agents available immediately',
    playoff_teams=8, playoff_weeks=(15,16,17),
    ppr=0.9, pass_yd=50.0, pass_td=5, pass_int=-1.5, rush_yd=20.0, rush_td=5,
    rec_yd=12.0, rec_td=5, fum=-1, two_pt=2,
    pass_att=0.15, pass_cmp=0.7, pass_inc=-0.1, sack_taken=-0.25, pick_six=-2.5,
    rush_att=0.15, first_down=0.2,
    fg_yds_per_made=None, xp=0.5,   # HH kickers score on distance bands, not total yards
    def_sack=2, def_int=2, def_fr=2, def_td=6, def_safety=4, def_block=4,
    def_tfl=1.5, def_4th_stop=4, def_three_and_out=1,
    pa_tiers=None,   # HH uses PA and yards-allowed tiers; modelled in the HH scorer
    idp=True,
    fam_slots={'QB':('QB','Q/W/R/T'),'RB':('RB','W/R','W/R/T','Q/W/R/T'),
               'WR':('WR','W/R','W/R/T','Q/W/R/T'),'TE':('TE','W/R/T','Q/W/R/T'),
               'K':('K',),'DEF':('DEF',),'DL':('DL','D'),'LB':('LB','D'),'DB':('DB','CB','S','D')},
    idp_solo=3, idp_assist=2, idp_sack=4, idp_int=4, idp_pd=4, idp_tfl=2,
    idp_ff=2, idp_fr=3, idp_td=7, idp_safety=5,
    week_bounds={'QB':(5,80),'RB':(0,45),'WR':(0,45),'TE':(0,40),'K':(0,25),'DEF':(-5,45),
                 'LB':(0,45),'DL':(0,35),'CB':(0,35),'S':(0,35),'DB':(0,35),'D':(0,45)},
    season_bounds={'QB':(200,750),'RB':(0,400),'WR':(0,400),'TE':(0,300),'K':(80,280),
                   'DEF':(200,550),'LB':(100,520),'DL':(80,360),'CB':(60,380),
                   'S':(80,400),'DB':(60,400),'D':(60,520)},
)

ALL={'BSB':BSB,'HH':HH}
