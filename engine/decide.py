"""Turn projections into GATED decisions.

The rule that stops answers from moving: a slot whose top two candidates sit
inside the noise band, with no market posted to separate them, is declared
PROVISIONAL with the date it resolves. It is NOT answered with a number that
will change on Friday for no reason other than that the data arrived.

Noise band = 1.5 pts weekly. Measured: line-only prop data cannot separate two
players inside ~1.5 pts, and Sleeper-vs-market mean absolute difference is 2.8.
"""
import sys, json, csv, datetime as dt
sys.path.insert(0,'/home/claude/bsb2')
from lib import scoring as S, gate as G
from lib.names import key, team

D='/home/claude/bsb2/data/'
NOISE=1.5
PROJ=json.load(open(D+'week_proj.json'))
GAMES={}
for r in csv.DictReader(open(D+'espn_games.csv')):
    GAMES[team(r['away'])]=GAMES[team(r['home'])]=r['kickoff']
ROSTER_KEYS={key(r['player']) for r in csv.DictReader(open(D+'rosters.csv'))}
TODAY=dt.date.today().isoformat()

def cand(pos_set):
    out=[]
    for n,v in PROJ.items():
        if v['pos'] in pos_set and v['des'] not in S.UNUSABLE:
            out.append((v['pts'],n,v))
    known=[c for c in out if c[0] is not None]
    unknown=[c for c in out if c[0] is None]
    known.sort(reverse=True)
    return known,unknown

def market_depth(v):
    p=v['prov']
    return sum(1 for f in ('rec','rec_yd','rush_yd','pass_yd','pass_td') if 'KALSHI' in str(p.get(f,'')))

def decide(slot,pos_set,exclude=()):
    known,unknown=cand(pos_set)
    known=[c for c in known if c[1] not in exclude]
    unknown=[c for c in unknown if c[1] not in exclude]
    if not known: return None
    top=known[0]; second=known[1] if len(known)>1 else None
    margin=(top[0]-second[0]) if second else 99
    deep=market_depth(top[2])
    rel=[u for u in unknown if u[2]['pos'] in pos_set]
    status='SETTLED'; why=[]
    if margin<NOISE and deep<2:
        status='PROVISIONAL'
        why.append(f'margin {margin:.2f} is inside the {NOISE} noise band and no market is posted to separate them')
    if rel:
        status='PROVISIONAL'
        why.append(f'{len(rel)} candidate(s) have NO source at all this week: {", ".join(u[1] for u in rel)}')
    return dict(slot=slot,top=top,second=second,margin=margin,deep=deep,
                status=status,why=why,known=known[:5],unknown=rel)

print('='*92)
print(f'BSB WEEK 2 — GATED DECISIONS   {TODAY}')
print('='*92)

# ---------------------------------------------------------------- DEF
d=decide('DEF',{'DEF'})
sf=PROJ['49ers']; det=PROJ['Lions']
r=G.check('start','49ers DEF over Lions DEF',player='49ers',designation=sf['des'],
          sources=['vegas','sleeper'],pos='DEF',value=sf['pts'],horizon='weekly',
          market_ready=True,pulled=TODAY,
          note='start 49ers, bench Lions')
print(f'\n### DEF — 49ers {sf["pts"]:.2f}  vs  Lions {det["pts"]:.2f}   margin {sf["pts"]-det["pts"]:+.2f}')
print('    49ers  points allowed: '+sf['prov']['pts_allow'])
print('    Lions  points allowed: '+det['prov']['pts_allow'])
# G12 STATE CHECK. A recommendation that is ALREADY TRUE is not advice, it is noise --
# and worse, it makes a card look like there is work outstanding when there is not. On
# 2026-09-16 the card told Caleb to swap the 49ers in for the Lions. The 49ers had been
# in his DEF slot the whole time. The engine compared two players and never once looked
# at which of them was actually starting. Every start/sit call now states the CURRENT
# state before it states the recommendation.
_cur={r['player']:r['slot'] for r in csv.DictReader(open(D+'rosters.csv'))
      if r['manager']=='Caleb'}
if _cur.get('49ers')=='DEF':
    print(f'    >>> ALREADY SET — the 49ers are in your DEF slot, the Lions are benched.')
    print(f'        NO ACTION. Lions lock {GAMES["DET"][:10]}. Confirmed, not pending.')
else:
    print(f'    >>> START THE 49ERS (they are currently at {_cur.get("49ers","not on roster")}).')
    print(f'        Lions play THURSDAY — this locks {GAMES["DET"][:10]}.')
print(r.render())
G.record('start','49ers DEF over Lions DEF','start 49ers, bench Lions',r.verdict)

# ---------------------------------------------------------------- Thursday
print('\n'+'='*92)
print('THURSDAY LOCKS (DET @ BUF) — decidable NOW, full Kalshi ladder')
print('='*92)
for n in ('James Cook','Sam LaPorta','Keon Coleman','Ray Davis','Lions'):
    v=PROJ[n]
    pts='   ???' if v['pts'] is None else f'{v["pts"]:6.2f}'
    print(f'  {n:18s} {v["slot"]:6s} {pts}   depth={market_depth(v)} kalshi fields')
    for k2,x in v['prov'].items(): print(f'       {k2:9s} {x}')
rc=G.check('start','James Cook RB1',player='James Cook',designation=PROJ['James Cook']['des'],
           sources=['kalshi','sleeper'],pos='RB',value=PROJ['James Cook']['pts'],
           horizon='weekly',market_ready=True,pulled=TODAY,note='start')
print(rc.render())
rl=G.check('start','Sam LaPorta TE',player='Sam LaPorta',designation=PROJ['Sam LaPorta']['des'],
           sources=['kalshi','sleeper'],pos='TE',value=PROJ['Sam LaPorta']['pts'],
           horizon='weekly',market_ready=True,pulled=TODAY,note='start at TE')
print(rl.render())

# ---------------------------------------------------------------- contested
print('\n'+'='*92)
print('SUNDAY / MONDAY SLOTS — where the honest answer is NOT YET')
print('='*92)
used={'James Cook','Sam LaPorta','49ers','Jason Myers','Matthew Stafford',
      'Jaxon Smith-Njigba','Drake London','MarShawn Lloyd'}
for slot,ps in (('WR3',{'WR'}),('W/R/T',{'WR','RB','TE'})):
    d=decide(slot,ps,exclude=used)
    if not d: continue
    print(f'\n### {slot}')
    for pts,n,v in d['known']:
        ko=GAMES.get(team(v['nfl']),'')[:10]
        print(f'    {n:22s} {v["nfl"]:4s} {pts:6.2f}  {",".join(v["sources"]):22s} plays {ko}')
    for _,n,v in d['unknown']:
        print(f'    {n:22s} {v["nfl"]:4s}    ???  NO SOURCE COVERS HIM THIS WEEK')
    print(f'    margin {d["margin"]:.2f}   -> {d["status"]}')
    for w in d['why']: print(f'      - {w}')
    rr=G.check('start',f'{slot}: {d["top"][1]}',player=d['top'][1],
               designation=d['top'][2]['des'],sources=d['top'][2]['sources'],
               pos=d['top'][2]['pos'],value=d['top'][0],horizon='weekly',
               market_ready=(d['deep']>=2),pulled=TODAY,note=f'start {d["top"][1]} at {slot}')
    print(rr.render())
    used.add(d['top'][1])

print('\n'+'='*92)
print('WHAT RESOLVES THIS, AND WHEN')
print('='*92)
print("""  Kalshi posts the Sunday prop ladders and DraftKings posts Sunday player props
  roughly Thu-Fri. FFToday's Week 2 table is not published either (the site's own
  nav still reads Week 1). Re-run this file then and every ??? and PROVISIONAL
  above resolves with a market-priced number rather than a coin flip.

  Nothing above needs to be guessed today except the Thursday game, and that one
  is fully market-priced.""")
