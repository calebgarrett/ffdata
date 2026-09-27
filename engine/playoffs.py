"""PLAYOFF-WINDOW EDGE — what the December market already knows.

The books have posted look-ahead spreads and totals for every game through week
18. That means the implied points total for every team in weeks 15, 16 and 17 --
the fantasy playoff weeks in BOTH leagues -- is a PRICE that exists right now, in
September, and essentially nobody in a 12-team home league is looking at it.

This is the one place market data says something fantasy consensus does not, and
it says it four months early. Preseason strength-of-schedule articles use last
year's win-loss records; this uses money.

WHAT THIS IS NOT. These are look-ahead lines. Books post them at low limits and
move them freely, so they are genuine prices but a weaker signal than a week-of
line. Treat the ORDERING as informative and the absolute numbers as soft, and
never let a 1-point gap here decide anything.

THREE WINDOWS, because they answer different questions:
  wk 3-9   the near term -- already in season_env.json
  wk 10-14 the QUALIFYING run. For a team sitting 11th, this is the window that
           decides whether the playoff window is ever reached at all.
  wk 15-17 the payoff window.
"""
import sys, csv, json, datetime as dt
from collections import defaultdict
sys.path.insert(0,'/home/claude/bsb2')
import numpy as np
from lib.names import key, team

D='/home/claude/bsb2/data/'
PO=(15,16,17); RUN=(10,11,12,13,14)

# ---------------- implied team totals from posted lines ----------------
wk=defaultdict(dict)
for fn in ('lines_wk3_9.csv','lines_wk10_18.csv'):
    for r in csv.DictReader(open(D+fn)):
        try: tot=float(r['over_under']); sp=float(r['spread'] or 0)
        except ValueError: continue
        w=int(r['week']); a,h=team(r['away']),team(r['home']); fav=team(r['favorite'])
        # implied team total = (total +/- spread)/2, favourite gets the plus
        ih,ia=((tot+sp)/2,(tot-sp)/2) if fav==h else ((tot-sp)/2,(tot+sp)/2)
        wk[w][a]=ia; wk[w][h]=ih
        wk[w].setdefault('_opp',{}); wk[w]['_opp'][a]=ih; wk[w]['_opp'][h]=ia
TEAMS=sorted({t for w in wk for t in wk[w] if t!='_opp'})

def window(weeks, opp=False):
    out={}
    for t in TEAMS:
        v=[(wk[w]['_opp'][t] if opp else wk[w][t]) for w in weeks
           if w in wk and t in (wk[w]['_opp'] if opp else wk[w])]
        if v: out[t]=float(np.mean(v))
    return out

EARLY=window(range(3,10)); QUAL=window(RUN); PLAY=window(PO)
PLAY_OPP=window(PO, opp=True)          # for defenses: who faces the worst offenses
rk=lambda d:{t:i+1 for i,t in enumerate(sorted(d,key=lambda x:-d[x]))}
RE,RQ,RP=rk(EARLY),rk(QUAL),rk(PLAY)
RPD={t:i+1 for i,t in enumerate(sorted(PLAY_OPP,key=lambda x:PLAY_OPP[x]))}  # 1 = easiest

print('='*100)
print('PLAYOFF-WINDOW EDGE — implied team totals from posted look-ahead lines (DraftKings via ESPN)')
print(f'weeks 15-17 have all 32 teams, no byes.   pulled {dt.date.today().isoformat()}')
print('='*100)

print('\nBEST OFFENSE ENVIRONMENTS IN THE FANTASY PLAYOFFS (wk 15-17 implied points/game)')
print(f'{"team":5s} {"wk15-17":>8s} {"rk":>4s}   {"wk3-9":>7s} {"rk":>4s}   {"shift":>7s}  {"wk15":>6s} {"wk16":>6s} {"wk17":>6s}')
order=sorted(PLAY,key=lambda x:-PLAY[x])
for t in order[:10]+['...']+order[-8:]:
    if t=='...': print('  ...'); continue
    sh=PLAY[t]-EARLY.get(t,PLAY[t])
    g=[f'{wk[w][t]:6.2f}' if t in wk[w] else '    --' for w in PO]
    print(f'{t:5s} {PLAY[t]:8.2f} {RP[t]:4d}   {EARLY.get(t,0):7.2f} {RE.get(t,0):4d}   {sh:+7.2f}  '+' '.join(g))
print(f'\n  spread top to bottom in the playoff window: {max(PLAY.values())-min(PLAY.values()):.2f} pts/game')
print(f'  spread in weeks 3-9 for comparison:          {max(EARLY.values())-min(EARLY.values()):.2f} pts/game')

print('\n'+'='*100)
print('BIGGEST SCHEDULE SWINGS — teams the December schedule treats very differently')
print('='*100)
sw={t:PLAY[t]-EARLY[t] for t in PLAY if t in EARLY}
up=sorted(sw,key=lambda x:-sw[x])[:8]; dn=sorted(sw,key=lambda x:sw[x])[:8]
print('  schedule OPENS UP in the playoffs:  '+' · '.join(f'{t} {sw[t]:+.2f}' for t in up))
print('  schedule TIGHTENS in the playoffs:  '+' · '.join(f'{t} {sw[t]:+.2f}' for t in dn))

print('\n'+'='*100)
print('DEFENSE STREAMING, WEEKS 15-17 — whose opponents score the least')
print('(a DEF is a matchup slot; this is the cheapest edge on the board because nobody')
print(' rosters a defense in September for a December schedule)')
print('='*100)
print(f'{"team":5s} {"opp pts/gm":>10s}   wk15 / wk16 / wk17 opponent implied totals')
for t in sorted(PLAY_OPP,key=lambda x:PLAY_OPP[x])[:10]:
    g=' / '.join(f'{wk[w]["_opp"][t]:5.2f}' for w in PO if t in wk[w]['_opp'])
    print(f'{t:5s} {PLAY_OPP[t]:10.2f}   {g}')

# ---------------- overlay the rosters ----------------
def overlay(label, rows, namecol, teamcol, mgr=None, mgrcol=None):
    print('\n'+'='*100)
    print(f'{label} — your players, by the window that matters')
    print('='*100)
    mine=[r for r in rows if (mgr is None or r[mgrcol]==mgr)]
    print(f'{"player":24s} {"tm":4s} {"wk3-9":>7s} {"wk10-14":>8s} {"wk15-17":>8s} {"rk":>4s} {"qual→play":>10s}')
    for r in sorted(mine,key=lambda x:-PLAY.get(team(x[teamcol]),0)):
        t=team(r[teamcol])
        if t not in PLAY: continue
        d=PLAY[t]-QUAL.get(t,PLAY[t])
        flag=''
        if RP[t]<=8: flag='  << playoff asset'
        elif RP[t]>=25: flag='  << playoff drag'
        print(f'{r[namecol][:24]:24s} {t:4s} {EARLY.get(t,0):7.2f} {QUAL.get(t,0):8.2f} '
              f'{PLAY[t]:8.2f} {RP[t]:4d} {d:+10.2f}{flag}')

bsb=list(csv.DictReader(open(D+'rosters.csv')))
overlay('BSB · OVERKILL', bsb, 'player', 'nfl', 'Caleb', 'manager')
hh=[r for r in csv.DictReader(open(D+'hh_rosters.csv'))]
overlay('HERITAGE HOUSE · Tecmo Bowlers', hh, 'player', 'nfl', 'Tecmo Bowlers', 'team_name')

# ---------------- week 11, priced ----------------
print('\n'+'='*100)
print('THE WEEK 11 PROBLEM IN BSB, NOW PRICED')
print('='*100)
bye11=sorted(set(TEAMS)-set(wk[11]))
print(f'  on bye week 11: {", ".join(bye11)}')
out=[r for r in bsb if r['manager']=='Caleb' and team(r['nfl']) in bye11]
print(f'  your players out: {", ".join(r["player"] for r in out)}')
print(f'  week 11 sits inside the QUALIFYING window (10-14), not the playoff window.')

# ---------------- who to trade with ----------------
print('\n'+'='*100)
print('TRADE DIRECTION — other rosters priced on the playoff window')
print('(the manager whose roster is worst in weeks 15-17 is the one with the most reason')
print(' to sell December value for September wins, and vice versa)')
print('='*100)
bym=defaultdict(list)
for r in bsb: bym[r['manager']].append(r)
tab=[]
for m,rs in bym.items():
    sk=[r for r in rs if r['pos'] in ('QB','RB','WR','TE') and team(r['nfl']) in PLAY]
    if not sk: continue
    tab.append((float(np.mean([PLAY[team(r['nfl'])] for r in sk])),
                float(np.mean([QUAL[team(r['nfl'])] for r in sk if team(r['nfl']) in QUAL])), m, len(sk)))
print(f'{"manager":14s} {"wk10-14":>8s} {"wk15-17":>8s} {"shift":>7s}  skill players')
for p,q,m,n in sorted(tab,reverse=True):
    star=' <<< YOU' if m=='Caleb' else ''
    print(f'{m:14s} {q:8.2f} {p:8.2f} {p-q:+7.2f}  {n}{star}')

json.dump({'PLAY':PLAY,'QUAL':QUAL,'EARLY':EARLY,'PLAY_OPP':PLAY_OPP,
           'RP':RP,'RQ':RQ,'RPD':RPD},open(D+'windows.json','w'),indent=1)
print('\nwrote data/windows.json')
