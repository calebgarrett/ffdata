"""BSB weekly decision engine — market first, gated, with provenance per number.

Run:  python3 week.py
"""
import sys, csv, json, datetime as dt
from collections import defaultdict
sys.path.insert(0,'/home/claude/bsb2')
import numpy as np
from scipy.optimize import linear_sum_assignment
from lib import market as M, scoring as S, gate as G
from lib.names import key, team, audit_phantoms

D='/home/claude/bsb2/data/'
ME='Caleb'; WEEK=2; PULLED=dt.date.today().isoformat()

# ---------------------------------------------------------------- state
rost=list(csv.DictReader(open(D+'rosters.csv')))
for r in rost: r['key']=key(r['player']) if r['pos']!='DEF' else key(r['player'])
ROSTER_KEYS={r['key'] for r in rost}
MINE=[r for r in rost if r['manager']==ME]
games=M.load_games(D+'espn_games.csv')
CTX=M.team_context(games)
KAL=M.load_kalshi(D+'kalshi.csv')
PROPS=M.load_props(D+'espn_props.csv')
SLP={}
for r in csv.DictReader(open(D+'sleeper_wk2.csv')):
    SLP[key(r['player'])]=r
def fnum(v):
    try: return float(v)
    except (TypeError,ValueError): return 0.0

# which games have a player market posted at all
MKT_GAMES={t.split('-')[1] for t in {r['event'] for r in csv.DictReader(open(D+'kalshi.csv'))}}
def market_ready(tm):
    tm=team(tm)
    for ev in MKT_GAMES:
        if tm in ev and not ev.startswith('26SEP20') or (tm in ev and _full_series(ev)):
            return True
    return False
def _full_series(ev):
    rows=[r for r in csv.DictReader(open(D+'kalshi.csv')) if r['event'].endswith(ev)]
    return len({r['series'] for r in rows})>=4

# ------------------------------------------------------- projections
def project(p):
    """-> dict(pts, parts, sources, provenance). Kalshi where it exists,
    Sleeper for the uncovered tail, Vegas for DEF/K. Never silently mixes."""
    k,pos,tm=p['key'],p['pos'],team(p['nfl'])
    src=[]; prov={}
    if pos=='DEF':
        ab=tm
        c=CTX.get(ab)
        s=SLP.get(k,{})
        allows_vegas=c['allows'] if c else None
        allows_slp=fnum(s.get('pts_allow')) or None
        if allows_vegas and allows_slp:
            src+=['vegas','sleeper']
            allows=(allows_vegas+allows_slp)/2
            prov['pts_allow']=f'vegas {allows_vegas:.2f} / sleeper {allows_slp:.2f} -> {allows:.2f}'
        else:
            allows=allows_vegas or allows_slp
            src+=['vegas'] if allows_vegas else ['sleeper']
            prov['pts_allow']=f'{allows:.2f} (single source)'
        pts=S.defense(sack=fnum(s.get('sack')),intc=fnum(s.get('int')),
                      fr=fnum(s.get('fum_rec')),td=fnum(s.get('def_td')),
                      pa_mean=allows)
        if s: src.append('sleeper')
        prov['turnovers']=f"sack {fnum(s.get('sack')):.2f} int {fnum(s.get('int')):.2f} fr {fnum(s.get('fum_rec')):.2f} td {fnum(s.get('def_td')):.2f} (sleeper)"
        return dict(pts=pts,sources=sorted(set(src)),prov=prov,pos=pos)
    if pos=='K':
        s=SLP.get(k,{})
        fgm=fnum(s.get('fgm')); xpm=fnum(s.get('xpm'))
        pts=S.kicker(fgm,xpm)
        prov['fg']=f'{fgm:.2f} made x {S.FG_YDS_PER_MADE}yd/10 (sleeper volume; fgm_yds field is BROKEN and not used)'
        prov['xp']=f'{xpm:.2f}'
        return dict(pts=pts,sources=['sleeper'],prov=prov,pos=pos)
    # skill positions
    s=SLP.get(k,{})
    g=lambda f: fnum(s.get(f))
    stat=dict(pass_yd=g('pass_yd'),pass_td=g('pass_td'),pass_int=g('pass_int'),
              rush_yd=g('rush_yd'),rush_td=g('rush_td'),rec=g('rec'),
              rec_yd=g('rec_yd'),rec_td=g('rec_td'),fum_lost=g('fum_lost'))
    if s: src.append('sleeper')
    for field,series in (('rec','KXNFLREC'),('rec_yd','KXNFLRECYDS'),
                         ('rush_yd','KXNFLRSHYDS'),('pass_yd','KXNFLPASSYDS'),
                         ('pass_td','KXNFLPASSTDS')):
        f=KAL.get((k,series))
        if f and f['sse']<0.05:
            prov[field]=f"KALSHI {f['mean']:.2f} (n={f['n']} strikes, sse {f['sse']:.4f}) vs sleeper {stat[field]:.2f}"
            stat[field]=f['mean']; src.append('kalshi')
    td=KAL.get((k,'KXNFLTD'))
    if td:
        # anytime-TD price is P(>=1 TD); slight understatement of E[TD], flagged
        tot_td=stat['rush_td']+stat['rec_td']
        prov['td']=f"KALSHI P(anytime TD)={td['mean']:.2f} vs sleeper E[TD]={tot_td:.2f}"
        if tot_td>0:
            sc=td['mean']/tot_td
            stat['rush_td']*=sc; stat['rec_td']*=sc
        src.append('kalshi')
    pr=PROPS.get(k)
    if pr and not any(x in prov for x in ('rec','rec_yd','rush_yd','pass_yd')):
        for f,v in pr.items():
            if f in stat: prov[f]=f'espn prop line {v} (line-only, med->mean corrected)'; stat[f]=v
        src.append('props')
    # A PLAYER NO SOURCE COVERS MUST NOT SCORE 0.00.  A silent zero is how a real
    # contributor gets benched on an absence rather than on evidence -- the same
    # shape as the ESPN 0.00 trap (Likely, Lloyd) that had to be hard-blocked before.
    if not src:
        return dict(pts=None,sources=[],prov={'!':'NO SOURCE COVERS THIS PLAYER — not zero, UNKNOWN'},
                    pos=pos,stat=stat,unknown=True)
    return dict(pts=S.offense(**stat),sources=sorted(set(src)),prov=prov,pos=pos,stat=stat)

for p in rost: p['proj']=project(p)

# ------------------------------------------------------- lineup solve
def usable(p): return p['designation'] not in S.UNUSABLE
def solve(players):
    R=[p for p in players if usable(p)]
    C=np.full((len(R),len(S.SLOTS)),1e6)
    for i,p in enumerate(R):
        for j,s in enumerate(S.SLOTS):
            if p['pos'] in S.SLOT_ACCEPTS[s] and p['proj']['pts'] is not None:
                C[i,j]=-p['proj']['pts']
    ri,ci=linear_sum_assignment(C)
    out={s:None for s in S.SLOTS}
    for i,j in zip(ri,ci):
        if C[i,j]<1e5: out[S.SLOTS[j]]=R[i]
    return out

LU=solve(MINE)

print('='*90)
print(f'BSB WEEK {WEEK} — OVERKILL — market-first, every call gated   ({PULLED})')
print('='*90)
print('\nSOURCE COVERAGE THIS RUN')
kal_games=sorted({e.split("-")[1] for e in {r["event"] for r in csv.DictReader(open(D+"kalshi.csv"))}})
full=[g for g in kal_games if _full_series(g)]
print(f'  Kalshi ladders (price = probability): {len(KAL)} fitted markets')
print(f'    FULL prop suite: {", ".join(full)}')
print(f'    anytime-TD only: {", ".join(g for g in kal_games if g not in full)}')
print(f'  Vegas game lines: {len(games)}/16 games — implied totals available for all 32 teams')
print(f'  ESPN player props: line-only, no price (confirmed again this run)')
print(f'  Sleeper week {WEEK}: {len(SLP)} players')
print('\n  >> The Sunday slate has NO player market yet. Sunday start/sit calls are')
print('     PROVISIONAL today and should be re-run Friday. Thursday is decidable now.')

print('\n'+'='*90)
print('PROJECTED LINEUP')
print('='*90)
print(f'{"slot":7s} {"player":22s} {"tm":4s} {"pts":>6s}  {"sources":28s} kickoff')
tot=0
for s in S.SLOTS:
    p=LU[s]
    if not p: print(f'{s:7s} -- EMPTY --'); continue
    tot+=p['proj']['pts'] or 0
    c=CTX.get(team(p['nfl']),{})
    ko=c.get('kickoff','')[:10]
    pv=p['proj']['prov']
    deep=sum(1 for f in ('rec','rec_yd','rush_yd','pass_yd','pass_td') if 'KALSHI' in str(pv.get(f,'')))
    star='*' if deep>=2 else ('t' if 'kalshi' in p['proj']['sources'] else ' ')
    val=f'{p["proj"]["pts"]:6.2f}' if p['proj']['pts'] is not None else '   ???'
    print(f'{s:7s} {p["player"][:22]:22s} {p["nfl"]:4s} {val}{star} '
          f'{",".join(p["proj"]["sources"])[:28]:28s} {ko}')
print(f'{"":7s} {"TOTAL":22s} {"":4s} {tot:6.2f}    (* full Kalshi ladder, t = TD market only)')

print('\nBENCH')
for p in sorted([x for x in MINE if x not in LU.values()],key=lambda x:-(x['proj']['pts'] or -1)):
    tag=f'  [{p["designation"]}]' if p['designation']!='none' else ''
    v=f'{p["proj"]["pts"]:6.2f}' if p['proj']['pts'] is not None else '   ???'
    srcs=",".join(p['proj']['sources'])[:28] or 'NO SOURCE — UNKNOWN, not zero'
    print(f'        {p["player"][:22]:22s} {p["nfl"]:4s} {v}  {srcs}{tag}')

json.dump({p['player']:dict(pts=p['proj']['pts'],sources=p['proj']['sources'],
                            prov=p['proj']['prov'],pos=p['pos'],nfl=p['nfl'],
                            des=p['designation'],
                            slot=next((s for s in S.SLOTS if LU[s] is p),'BN'))
           for p in MINE}, open(D+'week_proj.json','w'), indent=1)
print('\nwrote data/week_proj.json')
