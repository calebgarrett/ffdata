"""ROSTER CONSTRUCTION — the Mon-Wed job.

Caleb, 2026-09-15: "The focus earlier in the week is roster construction for the
coming weeks and season."

Three questions, in order of leverage:
  1. Where does the roster STRUCTURALLY break in the coming weeks (bye coverage)?
  2. Whose value is GROWING and whose is decaying, priced by the market?
     "You want to get the players now that grow in value later."
  3. What trade actually moves the needle, gated?

Horizon here is SEASON. Weekly numbers are the wrong instrument this early and
the Sunday market has not posted anyway.
"""
import sys, csv, json, itertools, datetime as dt
from collections import defaultdict
sys.path.insert(0,'/home/claude/bsb2')
import numpy as np
from scipy.optimize import linear_sum_assignment
from lib import scoring as S, gate as G
from lib.names import key, team

D='/home/claude/bsb2/data/'; ME='Caleb'; TODAY=dt.date.today().isoformat()

# ---------- market environment, per week and per team ----------
wk=defaultdict(dict)
for r in csv.DictReader(open(D+'lines_wk3_9.csv')):
    try: tot=float(r['over_under']); sp=float(r['spread'] or 0)
    except ValueError: continue
    w=int(r['week']); a,h=team(r['away']),team(r['home']); fav=team(r['favorite'])
    ih,ia=((tot+sp)/2,(tot-sp)/2) if fav==h else ((tot-sp)/2,(tot+sp)/2)
    wk[w][a]=ia; wk[w][h]=ih
WEEKS=sorted(wk)
ENV={t:np.mean([wk[w][t] for w in WEEKS if t in wk[w]]) for t in set().union(*[set(v) for v in wk.values()])}
ENV_RK={t:i+1 for i,t in enumerate(sorted(ENV,key=lambda x:-ENV[x]))}
EARLY=[w for w in WEEKS if w<=5]; LATE=[w for w in WEEKS if w>=7]
TRAJ={}
for t in ENV:
    e=[wk[w][t] for w in EARLY if t in wk[w]]; l=[wk[w][t] for w in LATE if t in wk[w]]
    if e and l: TRAJ[t]=np.mean(l)-np.mean(e)
BYE={w:sorted(set(ENV)-set(wk[w])) for w in WEEKS}

# ---------- state ----------
rost=list(csv.DictReader(open(D+'rosters.csv')))
for r in rost: r['key']=key(r['player'])
RK={r['key'] for r in rost}
teams=defaultdict(list)
for r in rost: teams[r['manager']].append(r)
BLEND=json.load(open(D+'season_blend.json'))
for r in rost:
    b=BLEND.get(r['key']); r['pts']=b['pts'] if b else 0.0; r['nsrc']=b['n'] if b else 0
MINE=teams[ME]
BLOCKED={'jordyn tyson','omar cooper','isiah pacheco'}
PROTECTED={'ray davis':('James Cook','Bills RB2 — the Cook handcuff'),
           'keon coleman':(None,'Bills WR3, a real role')}
POOL={k:v for k,v in BLEND.items() if k not in RK and v['pts']>0 and k not in BLOCKED}
FA=defaultdict(list)
for k,v in POOL.items(): FA[v['pos']].append((v['pts'],v['name'],v.get('tm',''),v['n']))
for p in FA: FA[p].sort(reverse=True)
REPL={p:(FA[p][0][0] if FA[p] else 0) for p in ('QB','RB','WR','TE','K','DEF')}
def vow(p): return p['pts']-REPL.get(p['pos'],0)

print('='*94)
print(f'BSB ROSTER CONSTRUCTION — season horizon, weeks 3-9 priced by the market   {TODAY}')
print('='*94)

# ---------- 1. bye structure ----------
print('\n'+'='*94)
print('1. WHERE THE ROSTER BREAKS — bye coverage, weeks 3-9')
print('='*94)
def fill(players):
    R=[p for p in players if p['designation'] not in S.UNUSABLE]
    C=np.full((len(R),len(S.SLOTS)),1e6)
    for i,p in enumerate(R):
        for j,s in enumerate(S.SLOTS):
            if p['pos'] in S.SLOT_ACCEPTS[s]: C[i,j]=-p['pts']
    ri,ci=linear_sum_assignment(C)
    out={s:None for s in S.SLOTS}
    for i,j in zip(ri,ci):
        if C[i,j]<1e5: out[S.SLOTS[j]]=R[i]
    return out
base=fill(MINE)
print(f'{"wk":>3s}  {"on bye":22s} {"your players out":42s} {"unfilled slots"}')
holes={}
for w in WEEKS:
    out=[p for p in MINE if team(p['nfl']) in BYE[w]]
    avail=[p for p in MINE if team(p['nfl']) not in BYE[w]]
    lu=fill(avail)
    gaps=[s for s in S.SLOTS if lu[s] is None]
    holes[w]=gaps
    names=', '.join(p['player'].split()[-1] for p in out) or '—'
    flag='  <<<' if gaps else ''
    print(f'{w:3d}  {",".join(BYE[w]) or "none":22s} {names[:42]:42s} {",".join(gaps) or "all covered"}{flag}')
print('\n  Doctrine: do NOT spend a roster spot now to insure a bye five weeks out.')
print('  Surface it so a TRADE can solve value and coverage at once, and revisit 1-2 weeks out.')

# ---------- 2. value trajectory ----------
print('\n'+'='*94)
print('2. WHOSE VALUE IS GROWING — market environment, weeks 3-5 vs weeks 7-9')
print('='*94)
print(f'{"player":24s} {"tm":4s} {"season":>8s} {"VOW":>7s} {"env":>6s} {"rk":>4s} {"early":>6s} {"late":>6s} {"trend":>7s}')
for p in sorted(MINE,key=lambda x:-TRAJ.get(team(x['nfl']),-99)):
    t=team(p['nfl']);
    if t not in TRAJ: continue
    e=np.mean([wk[w][t] for w in EARLY if t in wk[w]]); l=np.mean([wk[w][t] for w in LATE if t in wk[w]])
    arrow='UP  ' if TRAJ[t]>1.2 else ('DOWN' if TRAJ[t]<-1.2 else '  · ')
    print(f'{p["player"][:24]:24s} {t:4s} {p["pts"]:8.1f} {vow(p):+7.1f} {ENV[t]:6.2f} {ENV_RK[t]:4d} '
          f'{e:6.2f} {l:6.2f} {TRAJ[t]:+6.2f} {arrow}')
ris=sorted(TRAJ,key=lambda x:-TRAJ[x])[:6]; fal=sorted(TRAJ,key=lambda x:TRAJ[x])[:6]
print(f'\n  biggest risers league-wide: '+' · '.join(f'{t} {TRAJ[t]:+.2f}' for t in ris))
print(f'  biggest fallers:            '+' · '.join(f'{t} {TRAJ[t]:+.2f}' for t in fal))

# ---------- 3. the trade ----------
print('\n'+'='*94)
print('3. TRADE ENGINE — season horizon, both sides priced on value over the wire')
print('='*94)
def tot(players):
    lu=fill(players)
    return sum((v['pts'] if v else REPL[S.SLOT_BASE.get(s,s)]) for s,v in lu.items())
BASE={t:tot(v) for t,v in teams.items()}
# PLAUSIBILITY. A model will happily propose a kicker for two starters because the
# counterparty's optimal lineup barely moves. No human accepts that, and floating it
# costs credibility with the league. Two constraints:
#   - the give side must be a skill position; nobody trades assets for a K or DEF
#   - the give side must carry at least 40% of the get side's value over the wire
GIVE_OK={'QB','RB','WR','TE'}
res=[]
for o,ro in teams.items():
    if o==ME: continue
    for a in MINE:
        if a['key'] in PROTECTED or a['designation'] in S.UNUSABLE: continue
        if a['pos'] not in GIVE_OK: continue
        for n in (1,2):
            for got in itertools.combinations([x for x in ro if x['pts']>90],n):
                if any(x['designation'] in S.UNUSABLE for x in got): continue
                ga=tot([x for x in MINE if x is not a]+list(got))-BASE[ME]
                gb=tot([x for x in ro if x not in got]+[a])-BASE[o]
                gv=sum(max(x['pts']-REPL.get(x['pos'],0),0) for x in got)
                if gv>0 and max(vow(a),0)/gv < 0.40: continue   # fleece filter
                if ga>=20 and gb>=6:
                    res.append((ga,gb,a,got,o))
res.sort(key=lambda x:-x[0]); pairs=set(); shown=0
for ga,gb,a,got,o in res:
    if (a['player'],o) in pairs: continue      # one best offer per (asset, counterparty)
    pairs.add((a['player'],o)); shown+=1
    if shown>7: break
    gn=' + '.join(x['player'] for x in got)
    envs=' / '.join(f'{team(x["nfl"])} #{ENV_RK.get(team(x["nfl"]),"?")}' for x in got)
    print(f'\n  give {a["player"]} ({a["pos"]}, VOW {vow(a):+.0f}, {team(a["nfl"])} #{ENV_RK.get(team(a["nfl"]),"?")})')
    print(f'    get {gn}  [{envs}]   from {o}')
    print(f'    you {ga:+.1f}   them {gb:+.1f}')
    # what it does to bye coverage
    newr=[x for x in MINE if x is not a]+list(got)
    fixed=[]
    for w in WEEKS:
        av=[p for p in newr if team(p['nfl']) not in BYE[w]]
        g2=[s for s in S.SLOTS if fill(av)[s] is None]
        if holes[w] and not g2: fixed.append(w)
    if fixed: print(f'    also closes the week {",".join(map(str,fixed))} hole')
    r=G.check('trade',f'give {a["player"]} for {gn}',player=got[0]['player'],
              designation=got[0]['designation'],
              sources=['fftoday','sleeper'] if got[0]['nsrc']==2 else ['fftoday'],
              pos=got[0]['pos'],value=got[0]['pts'],horizon='season',pulled=TODAY)
    print(r.render('      '))
if not res: print('  nothing clears the bar.')
