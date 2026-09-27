"""Market layer — the primary source, per Caleb's standing doctrine.

Hierarchy, strongest first:
  1. KALSHI  — the price in cents IS the probability. A multi-strike ladder is a
     full distribution, so integrating gives a TRUE MEAN with no devig and no
     median->mean fudge. This is the only source that carries probability.
  2. VEGAS GAME LINES — spread + total for all 32 teams, weeks ahead.
     Implied team total = (total +/- spread)/2. Drives DEF, K, and offensive
     environment. Prices ARE present at the game level.
  3. VEGAS PLAYER PROPS (ESPN core API) — LINE ONLY, no price, confirmed again
     2026-09-15 by enumerating every field in `current`: it contains only
     `target`. So a posted 2.5 spans an implied mean of ~2.28-3.11 depending on
     juice we cannot see. Apply the measured median->mean correction.
  4. Consensus projections (Sleeper/Rotowire, FFToday) for everything uncovered.

COVERAGE IS TIME-DEPENDENT AND THAT IS WHY ANSWERS USED TO MOVE.
On Tue 2026-09-15 only the Thursday game had player markets; the Sunday slate
had none. A decision about a Sunday player is NOT READY on Tuesday. The gate
enforces this rather than letting a projection quietly stand in for a market.
"""
import csv, math
import numpy as np
from scipy.optimize import curve_fit
from scipy.stats import nbinom, gamma as gammadist
from .names import key, team

YARDS_MED2MEAN = 1.16   # measured over 157 players; yards are right-skewed
RECS_MED2MEAN  = 1.04   # near-symmetric, small correction

# ---------------------------------------------------------------- game lines
def load_games(path):
    """-> {(away,home): dict} with implied team totals from spread+total."""
    out={}
    for r in csv.DictReader(open(path)):
        a,h=team(r['away']),team(r['home'])
        try: tot=float(r['over_under']); sp=abs(float(r['spread']))
        except (TypeError,ValueError): continue
        fav=team(r['spread_team'])
        if fav==h: ih,ia=(tot+sp)/2,(tot-sp)/2
        else:      ia,ih=(tot+sp)/2,(tot-sp)/2
        out[(a,h)]=dict(away=a,home=h,kickoff=r['kickoff'],total=tot,spread=sp,
                        fav=fav,implied={a:round(ia,2),h:round(ih,2)},
                        event_id=r['event_id'])
    return out

def team_context(games):
    """-> {TEAM: {'implied':x,'allows':y,'opp':T,'kickoff':k}}  'allows' is the
    opponent's implied total, i.e. what that team's DEFENSE is expected to give up."""
    ctx={}
    for (a,h),g in games.items():
        ctx[a]=dict(implied=g['implied'][a],allows=g['implied'][h],opp=h,
                    home=False,kickoff=g['kickoff'],total=g['total'],src=g.get('src','vegas'))
        ctx[h]=dict(implied=g['implied'][h],allows=g['implied'][a],opp=a,
                    home=True,kickoff=g['kickoff'],total=g['total'],src=g.get('src','vegas'))
    return ctx

# --------------------------------------------------- Kalshi game lines (09-24)
# KXNFLSPREAD ("KC Chiefs wins by over 9.5 points?" per team, both sides),
# KXNFLTOTAL ("Full Game: over 46.5 points scored?") and KXNFLGAME (winner) are
# full ladders: the median of each is the market's spread and total, and the
# two together give implied team totals. Same pull cadence as the player props.
def _median_from_sf(points):
    """points: [(x, P(X > x))] -> x where P crosses 0.5 (linear), or None."""
    pts=sorted(points)
    if not pts: return None
    xs=[x for x,_ in pts]; ps=[p for _,p in pts]
    # monotone non-increasing survival
    for i in range(1,len(ps)): ps[i]=min(ps[i],ps[i-1])
    if ps[0]<0.5: return xs[0]
    if ps[-1]>0.5: return xs[-1]
    for i in range(1,len(pts)):
        if ps[i]<=0.5<=ps[i-1]:
            x0,x1,p0,p1=xs[i-1],xs[i],ps[i-1],ps[i]
            return x0 if p0==p1 else x0+(x1-x0)*(p0-0.5)/(p0-p1)
    return None

def load_kalshi_games(path, teams):
    """-> {(away,home): dict(total, spread, fav, implied, src='kalshi', n)} for every
    game with a total AND a spread ladder. `teams` is the set of NFL abbreviations."""
    import re
    ev={}
    for r in csv.DictReader(open(path)):
        if r['series'] not in ('KXNFLSPREAD','KXNFLTOTAL','KXNFLGAME'): continue
        tail=r['event'].split('-',1)[1]
        if len(tail)<9 or not tail[:7][2:5].isalpha(): continue      # 26SEP27KCMIA
        ev.setdefault(tail,[]).append(r)
    out={}
    for tail,rows in ev.items():
        code=tail[7:]; a=h=None
        for i in (2,3):
            x,y=team(code[:i]),team(code[i:])
            if x in teams and y in teams: a,h=x,y; break
        if not a: continue
        tot=[]; marg=[]           # marg: (x, P(margin_home > x))
        for r in rows:
            m=_mid(r)
            if m is None: continue
            t=r['title']
            if r['series']=='KXNFLTOTAL':
                mm=re.search(r'over ([\d.]+) points',t)
                if mm: tot.append((float(mm.group(1)),m))
            elif r['series']=='KXNFLSPREAD':
                mm=re.search(r'over ([\d.]+) points',t)
                if not mm: continue
                x=float(mm.group(1)); side=team(r['ticker'].split('-')[-1].rstrip('0123456789'))
                if side==h: marg.append((x,m))                 # P(home wins by > x)
                elif side==a: marg.append((-x,1-m))            # P(home margin > -x) = 1 - P(away wins by > x)
            elif r['series']=='KXNFLGAME':
                side=team(r['ticker'].split('-')[-1])
                if side==h: marg.append((0.0,m))
                elif side==a: marg.append((0.0,1-m))
        T=_median_from_sf(tot); M=_median_from_sf(marg)
        if T is None or M is None: continue
        fav=h if M>0 else a; sp=abs(M)
        ih,ia=(T+M)/2,(T-M)/2
        out[(a,h)]=dict(away=a,home=h,total=round(T,1),spread=round(sp,1),fav=fav,
                        implied={a:round(ia,2),h:round(ih,2)},src='kalshi',n=len(tot)+len(marg),kickoff=None,tail=tail)
    return out

# ------------------------------------------------------------------- Kalshi
# Values in this API version are DOLLAR STRINGS (0.0100 = 1 cent = 1% prob),
# not the integer cents the older docs describe.
def _mid(r):
    b,a=float(r['yes_bid']),float(r['yes_ask'])
    if a<=0 and b<=0: return None
    if a<=0: return b
    if b<=0: return a
    return (a+b)/2

def _clean_ladder(rows):
    """[(strike, prob)] sorted ascending by strike, made monotone non-increasing.

    Thin strikes quote wide and their BID alone is not monotone (22 soft
    inversions observed in the DET@BUF book), which would produce negative
    implied densities. Use the midpoint and enforce monotonicity by taking the
    running minimum from the low strike upward."""
    pts=[]
    for r in rows:
        try: s=float(r['ticker'].rsplit('-',1)[1])
        except (IndexError,ValueError): continue
        m=_mid(r)
        if m is None or not (0.0<m<1.0): continue
        pts.append((s,m))
    if not pts: return []
    pts.sort()
    # collapse duplicate strikes to their mean, then enforce P(X>=s) non-increasing
    agg={}
    for s,p in pts: agg.setdefault(s,[]).append(p)
    pts=[(s,sum(v)/len(v)) for s,v in sorted(agg.items())]
    out=[];run=1.0
    for s,p in pts:
        run=min(run,p); out.append((s,run))
    return out

def _sf_nbinom(k,r,p):   return nbinom.sf(np.asarray(k)-1,r,p)
def _sf_zigamma(y,z,sh,sc): return (1-z)*gammadist.sf(np.asarray(y),sh,scale=sc)

def fit_count(ladder):
    """Negative binomial fit to P(X>=k). -> (mean, sse, npts) or None."""
    if len(ladder)<2: return None
    x=np.array([s for s,_ in ladder]); y=np.array([p for _,p in ladder])
    best=None
    for r0 in (1.0,2.0,4.0,8.0):
        for p0 in (0.3,0.5,0.7):
            try:
                pr,_=curve_fit(_sf_nbinom,x,y,p0=[r0,p0],
                               bounds=([0.05,0.01],[200,0.999]),maxfev=20000)
            except Exception: continue
            sse=float(((_sf_nbinom(x,*pr)-y)**2).sum())
            if best is None or sse<best[1]: best=(pr,sse)
    if best is None: return None
    r,p=best[0]
    return dict(mean=float(r*(1-p)/p), sse=best[1], n=len(ladder), model='nbinom')

def fit_yards(ladder):
    """Zero-inflated gamma fit to P(X>=y). -> (mean, sse, npts, p_zero) or None."""
    if len(ladder)<3: return None
    x=np.array([s for s,_ in ladder]); y=np.array([p for _,p in ladder])
    best=None
    for z0 in (0.02,0.1,0.25):
        for sh0 in (1.0,2.0,4.0):
            sc0=max(x.mean()/sh0,1.0)
            try:
                pr,_=curve_fit(_sf_zigamma,x,y,p0=[z0,sh0,sc0],
                               bounds=([0.0,0.15,0.5],[0.85,60,400]),maxfev=30000)
            except Exception: continue
            sse=float(((_sf_zigamma(x,*pr)-y)**2).sum())
            if best is None or sse<best[1]: best=(pr,sse)
    if best is None: return None
    z,sh,sc=best[0]
    return dict(mean=float((1-z)*sh*sc), sse=best[1], n=len(ladder),
                p_zero=float(z), model='zi-gamma')

SERIES_KIND={'KXNFLREC':'count','KXNFLPASSTDS':'count','KXNFLINT':'count',
             'KXNFLRECYDS':'yards','KXNFLRSHYDS':'yards','KXNFLPASSYDS':'yards',
             'KXNFLRRYDS':'yards','KXNFLTD':'td'}

def load_kalshi(path):
    """-> {(player_key, series): fit_dict}. Player identified from the market
    TITLE (authoritative) rather than the compressed ticker code.
    Fits are cached beside the CSV, keyed on its mtime -- 472 ladders take
    ~40s to fit and every command builds Projections()."""
    import os, pickle
    cache=path+'.fits.pkl'
    try:
        if os.path.exists(cache) and os.path.getmtime(cache)>=os.path.getmtime(path):
            return pickle.load(open(cache,'rb'))
    except Exception: pass
    out=_load_kalshi(path)
    try: pickle.dump(out,open(cache,'wb'))
    except Exception: pass
    return out

def _load_kalshi(path):
    rows=list(csv.DictReader(open(path)))
    byp={}
    for r in rows:
        t=r['title']
        if ':' not in t: continue
        nm=t.split(':',1)[0].strip()
        byp.setdefault((key(nm),r['series'],nm),[]).append(r)
    out={}
    for (k,series,disp),rr in byp.items():
        kind=SERIES_KIND.get(series)
        lad=_clean_ladder(rr)
        if not lad: continue
        if kind=='td':
            # the -1 strike is anytime TD: P(X>=1) directly, no fit needed
            p1=[p for s,p in lad if abs(s-1)<1e-9]
            if p1: out[(k,series)]=dict(mean=p1[0],sse=0.0,n=1,model='direct',
                                        ladder=lad,display=disp)
            continue
        f=fit_count(lad) if kind=='count' else fit_yards(lad) if kind=='yards' else None
        if f: f.update(ladder=lad,display=disp); out[(k,series)]=f
    return out

# --------------------------------------------------------------- ESPN props
PROP_MAP={'Total Passing Yards':'pass_yd','Total Passing Touchdowns':'pass_td',
 'Total Interceptions':'pass_int','Total Rushing Yards':'rush_yd',
 'Total Carries':'rush_att','Total Receptions':'rec','Total Receiving Yards':'rec_yd'}
def load_props(path):
    """-> {player_key: {stat: line}} with the median->mean correction applied.
    LINE ONLY — no price exists in this feed, so this is weaker than Kalshi."""
    out={}
    for r in csv.DictReader(open(path)):
        stat=None
        for k,v in PROP_MAP.items():
            if r['prop_type'].startswith(k): stat=v; break
        if not stat: continue
        try: val=float(r['line'])
        except (TypeError,ValueError): continue
        if stat.endswith('_yd'): val*=YARDS_MED2MEAN
        elif stat=='rec':        val*=RECS_MED2MEAN
        out.setdefault(key(r['player']),{})[stat]=round(val,2)
    return out
