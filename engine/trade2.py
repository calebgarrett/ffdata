"""Trade engine v2 — with POSITIONAL FIT on the counterparty's side.

The gap Caleb found: the model measured a counterparty's gain only as the change
in their optimal lineup total. That treats a piece they CANNOT START as neutral.
It is not neutral — it is a wasted roster spot, and no manager accepts one.
Granddude starts ONE tight end and already has Jake Ferguson; sending him
LaPorta + Likely hands him a third TE.

Rule now enforced: EVERY piece the counterparty receives must crack their own
starting lineup. If it does not, the deal is rejected outright.
"""
import sys,csv,json,itertools
sys.path.insert(0,'/home/claude/bsb2')
import numpy as np
from collections import defaultdict
from scipy.optimize import linear_sum_assignment
from lib import scoring as S
from lib.names import key,team
D='data/'
rost=list(csv.DictReader(open(D+'rosters.csv')))
for r in rost: r['key']=key(r['player'])
B=json.load(open(D+'season_blend.json'))
for r in rost:
    b=B.get(r['key']); r['pts']=b['pts'] if b else 0.0; r['nsrc']=b['n'] if b else 0
teams=defaultdict(list)
for r in rost: teams[r['manager']].append(r)
ME='Caleb'; MINE=teams[ME]; RK={r['key'] for r in rost}
BLOCKED={'jordyn tyson','omar cooper','isiah pacheco'}
POOL={k:v for k,v in B.items() if k not in RK and v['pts']>0 and k not in BLOCKED}
FA=defaultdict(list)
for k,v in POOL.items(): FA[v['pos']].append(v['pts'])
REPL={p:max(v) for p,v in FA.items()}
UNTOUCHABLE={'drake london','jaxon smith-njigba','james cook','ray davis','keon coleman'}
def fill(ps):
    R=[p for p in ps if p['designation'] not in S.UNUSABLE]
    C=np.full((len(R),10),1e6)
    for i,p in enumerate(R):
        for j,s in enumerate(S.SLOTS):
            if p['pos'] in S.SLOT_ACCEPTS[s]: C[i,j]=-p['pts']
    ri,ci=linear_sum_assignment(C)
    o={s:None for s in S.SLOTS}
    for i,j in zip(ri,ci):
        if C[i,j]<1e5: o[S.SLOTS[j]]=R[i]
    return o
def tot(ps):
    lu=fill(ps)
    return sum((v['pts'] if v else REPL[S.SLOT_BASE.get(s,s)]) for s,v in lu.items())
def vow(p): return p['pts']-REPL.get(p['pos'],0)
BASE={t:tot(v) for t,v in teams.items()}

print('POSITIONAL-FIT CHECK — what each rival actually starts, and where they are thin')
print(f'{"manager":11s} {"QB":>3s} {"RB":>3s} {"WR":>3s} {"TE":>3s}   their weakest STARTING slot')
for t,r in sorted(teams.items()):
    c=defaultdict(int)
    for p in r: c[p['pos']]+=1
    lu=fill(r)
    weak=sorted([(lu[s]['pts']-REPL.get(lu[s]['pos'],0),s,lu[s]['player']) for s in S.SLOTS if lu[s]])[:1]
    w=f'{weak[0][1]} {weak[0][2]} ({weak[0][0]:+.0f})' if weak else ''
    print(f'{t:11s} {c["QB"]:3d} {c["RB"]:3d} {c["WR"]:3d} {c["TE"]:3d}   {w}')

print('\n'+'='*92)
print('TRADES WHERE EVERY PIECE THEY RECEIVE ACTUALLY STARTS FOR THEM')
print('='*92)
res=[]
for o,ro in teams.items():
    if o==ME: continue
    give=[p for p in MINE if p['key'] not in UNTOUCHABLE
          and p['designation'] not in S.UNUSABLE and p['pos'] in {'QB','RB','WR','TE'}]
    for n in (1,2):
        for gv in itertools.combinations(give,n):
            for m in (1,2):
                for got in itertools.combinations([x for x in ro if x['pts']>120
                                                   and x['designation'] not in S.UNUSABLE],m):
                    their_new=[x for x in ro if x not in got]+list(gv)
                    lu_them=fill(their_new)
                    starters={id(v) for v in lu_them.values() if v}
                    # EVERY piece they receive must start for them
                    if not all(id(x) in starters for x in gv): continue
                    ga=tot([x for x in MINE if x not in gv]+list(got))-BASE[ME]
                    gb=tot(their_new)-BASE[o]
                    gvv=sum(max(vow(x),0) for x in gv)
                    gtv=sum(max(vow(x),0) for x in got)
                    if gtv>0 and gvv/gtv<0.40: continue
                    if ga>=10 and gb>=6:
                        res.append((ga,gb,gv,got,o))
res.sort(key=lambda x:-x[0]); seen=set(); n=0
for ga,gb,gv,got,o in res:
    sig=(tuple(sorted(x['player'] for x in gv)),o)
    if sig in seen: continue
    seen.add(sig); n+=1
    if n>10: break
    gtxt=" + ".join(x["player"] for x in gv)
    rtxt=" + ".join("{} ({} {:.0f})".format(x["player"],x["pos"],x["pts"]) for x in got)
    print(f'  give {gtxt:34s} get {rtxt:46s}')
    print(f'       from {o:11s} you {ga:+6.1f}   them {gb:+6.1f}')
if not res:
    print('  NOTHING. No trade in this league passes positional fit on the counterparty side.')
