"""Canonical player keys.

THE FAILURE THIS PREVENTS: on 2026-09-15 "Kenneth Gainwell" (FFToday) and
"Kenny Gainwell" (Yahoo roster) normalised to two different keys. Gainwell was
on Rick's bench, but the FFToday spelling matched nothing on any roster, so he
surfaced as the single best free-agent running back in the league and was
recommended as a waiver add. Caleb would have burned a claim on a rostered player.

Two defences, both required:
  1. FIRST maps formal first names to the common form before keying.
  2. audit_phantoms() re-checks the whole free-agent pool against every roster by
     surname and near-match on the first name, and MUST be run before any pool is
     used. A registry can only cover names someone thought of; the audit catches
     the rest.
"""
import re, difflib

SUFFIX = re.compile(r'\b(jr|sr|ii|iii|iv|v)\b\.?')

# formal -> common. Extend freely; a wrong entry here is far cheaper than a miss.
FIRST = {
    'kenneth':'kenny','chigoziem':'chig','michael':'mike','christopher':'chris',
    'joshua':'josh','zachary':'zach','benjamin':'ben','matthew':'matt',
    'nicholas':'nick','daniel':'dan','william':'will','anthony':'tony',
    'jonathan':'jon','samuel':'sam','jeffery':'jeff','jeffrey':'jeff',
    'cameron':'cam','alexander':'alex','patrick':'pat','raymond':'ray',
    'timothy':'tim','richard':'rich','gregory':'greg','robert':'rob',
    'edward':'ed','ronald':'ron','theodore':'ted','nathaniel':'nate',
    'joseph':'joe','tyrone':'ty','demarcus':'marcus','dominique':'dom',
}

# explicit pairs the heuristic cannot reach (nicknames, spelling variants)
EXPLICIT = {
    'cam ward':'cameron ward',
    'gabe davis':'gabriel davis',
}

TEAM_ALIAS = {'JAC':'JAX','LA':'LAR','WSH':'WAS','ARZ':'ARI','SD':'LAC','OAK':'LV'}

DST_FULL = {
 'ARI':'arizona cardinals','ATL':'atlanta falcons','BAL':'baltimore ravens',
 'BUF':'buffalo bills','CAR':'carolina panthers','CHI':'chicago bears',
 'CIN':'cincinnati bengals','CLE':'cleveland browns','DAL':'dallas cowboys',
 'DEN':'denver broncos','DET':'detroit lions','GB':'green bay packers',
 'HOU':'houston texans','IND':'indianapolis colts','JAX':'jacksonville jaguars',
 'KC':'kansas city chiefs','LAC':'los angeles chargers','LAR':'los angeles rams',
 'LV':'las vegas raiders','MIA':'miami dolphins','MIN':'minnesota vikings',
 'NE':'new england patriots','NO':'new orleans saints','NYG':'new york giants',
 'NYJ':'new york jets','PHI':'philadelphia eagles','PIT':'pittsburgh steelers',
 'SEA':'seattle seahawks','SF':'san francisco 49ers','TB':'tampa bay buccaneers',
 'TEN':'tennessee titans','WAS':'washington commanders'}
NICK2ABBR = {v.split()[-1]:k for k,v in DST_FULL.items()}
NICK2ABBR.update({'49ers':'SF','football team':'WAS'})
# Yahoo's team pages name a defense by CITY on some renders ('Minnesota', 'Kansas
# City', 'Green Bay' — 10-01: T-rex's Vikings keyed as 'minnesota', not DST:MIN, and
# the engine offered them as a free agent). Unambiguous cities map here; the two
# 'Los Angeles' and two 'New York' defenses need the team code (see state.State).
CITY2ABBR = {' '.join(v.split()[:-1]): k for k, v in DST_FULL.items()}
for amb in ('los angeles', 'new york'): CITY2ABBR.pop(amb, None)
CITY2ABBR.update({'ny jets': 'NYJ', 'ny giants': 'NYG', 'la rams': 'LAR', 'la chargers': 'LAC',
                  'n y jets': 'NYJ', 'n y giants': 'NYG', 'l a rams': 'LAR', 'l a chargers': 'LAC'})

def team(t):
    t=(t or '').strip().upper()
    return TEAM_ALIAS.get(t,t)

def key(name):
    """Canonical key for a player or a team defense. Idempotent: key(key(x)) == key(x)."""
    if (name or '').startswith('DST:'): return name
    n=(name or '').lower().strip()
    n=n.replace('.','').replace("'",'').replace('-',' ').replace('’','')
    n=SUFFIX.sub('',n)
    n=' '.join(n.split())
    if n in EXPLICIT: n=EXPLICIT[n]
    # team defense written any of several ways
    if n in DST_FULL.values(): return 'DST:'+[k for k,v in DST_FULL.items() if v==n][0]
    if n in NICK2ABBR: return 'DST:'+NICK2ABBR[n]
    if n in CITY2ABBR: return 'DST:'+CITY2ABBR[n]
    p=n.split()
    if not p: return ''
    p[0]=FIRST.get(p[0],p[0])
    return ' '.join(p)

def surname(k): return k.split()[-1] if k and not k.startswith('DST:') else k

def _common_prefix(a,b):
    n=0
    for x,y in zip(a,b):
        if x!=y: break
        n+=1
    return n

def audit_phantoms(pool_keys, roster_keys, roster_names=None, thresh=0.62,
                   meta=None, strict=True):
    """Pool entries that are really a rostered player under another spelling.

    SECOND FAILURE THIS PREVENTS (2026-09-16): the first version of this function
    flagged "josh hines allen" as Josh Allen and "brian robinson" as Bijan
    Robinson, and the callers DELETED them from the pool. Josh Hines-Allen is a
    Jaguars edge rusher and Brian Robinson is a Washington running back -- both
    real, available, and quietly removed from consideration. A pool audit that
    eats real free agents is worse than no audit, because the loss is invisible.

    Three discriminators now, all cheap:
      1. token count must match. "josh hines allen" (3) is not "josh allen" (2).
      2. a nickname shares a real PREFIX with its formal form -- kenneth/kenny
         share 4 characters, chris/christopher 5, will/william 4. brian/bijan
         share 1. SequenceMatcher's 0.8 on brian/bijan came from shared letters
         in any order, which is not how nicknames work.
      3. when `meta` is supplied ({key: {'tm':..,'pos':..}}), a disagreement on
         BOTH team and position family demotes a match to a near-miss.

    Returns (phantoms, near_misses). Only `phantoms` may be removed from a pool;
    `near_misses` must be PRINTED so a real collision can never hide in silence.
    """
    FAM={'QB':'off','RB':'off','WR':'off','TE':'off','K':'k','DEF':'def',
         'DL':'d','DE':'d','DT':'d','NT':'d','LB':'d','DB':'d','CB':'d','S':'d',
         'FS':'d','SS':'d','OLB':'d','ILB':'d','MLB':'d'}
    def fam(k):
        m=(meta or {}).get(k) or {}
        return FAM.get(str(m.get('pos','')).upper().split(',')[0].strip())
    def tm(k):
        m=(meta or {}).get(k) or {}
        return team(m.get('tm') or '')

    phantoms=[]; near=[]
    rs={}
    for rk in roster_keys: rs.setdefault(surname(rk),[]).append(rk)
    for pk in pool_keys:
        if pk.startswith('DST:'):
            if pk in roster_keys: phantoms.append((pk,pk,1.0,'same defense'))
            continue
        pp=pk.split()
        for rk in rs.get(surname(pk),[]):
            rp=rk.split()
            if len(pp)!=len(rp):
                near.append((pk,rk,0.0,f'different name length ({len(pp)} vs {len(rp)} parts)'))
                continue
            if pp[:-1]==rp[:-1]:
                phantoms.append((pk,rk,1.0,'identical name')); break
            a,b=pp[0],rp[0]
            cp=_common_prefix(a,b)
            r=difflib.SequenceMatcher(None,a,b).ratio()
            nickname = cp>=3 and (a.startswith(b) or b.startswith(a) or r>thresh)
            why=f'"{a}"/"{b}" share {cp} leading chars, ratio {r:.2f}'
            if not nickname:
                # A bare surname collision (Milton Williams vs Kyren Williams) is
                # normal and there are hundreds. Only surface the ones that are
                # close enough to be worth a human glance.
                if cp>=2 or r>0.55:
                    near.append((pk,rk,round(r,2),why+' — not a nickname pattern'))
                continue
            if meta is not None:
                ft,fr=fam(pk),fam(rk); tt,tr=tm(pk),tm(rk)
                if ft and fr and tt and tr and ft!=fr and tt!=tr:
                    near.append((pk,rk,round(r,2),
                                 f'{why}; but {tt}/{ft} vs {tr}/{fr} — different player'))
                    continue
            phantoms.append((pk,rk,round(r,2),why)); break
    if not strict:
        return phantoms
    return phantoms, near
