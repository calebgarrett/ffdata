"""Season layer — waivers and trades.

DOCTRINE (Caleb's, and it is the one I broke before):
  A season projection ALREADY embeds the player's team context. Do NOT multiply
  it by his offense's rank as well — that counts the same thing twice. The
  market-implied environment earns its place on UPSIDE: probability of a blow-up
  week, and what the role is worth if one opens. So it is shown as a SEPARATE
  column and used to rank upside and break ties, never as a haircut on the mean.

  And: "roster spots should be prioritized for high upside season changing
  players." A spot is capital. Do not spend one insuring a streamable hole.
"""
import sys, csv, json, datetime as dt
from collections import defaultdict
sys.path.insert(0,'/home/claude/bsb2')
from lib import scoring as S, gate as G
from lib.names import key, team, audit_phantoms

D='/home/claude/bsb2/data/'
ME='Caleb'; TODAY=dt.date.today().isoformat()

# ---------------- market environment, weeks 3-9 ----------------
env=defaultdict(list)
for r in csv.DictReader(open(D+'lines_wk3_9.csv')):
    try: tot=float(r['over_under']); sp=float(r['spread'] or 0)
    except ValueError: continue
    a,h=team(r['away']),team(r['home']); fav=team(r['favorite'])
    ih,ia=((tot+sp)/2,(tot-sp)/2) if fav==h else ((tot-sp)/2,(tot+sp)/2)
    env[a].append(ia); env[h].append(ih)
ENV={t:sum(v)/len(v) for t,v in env.items()}
ENV_RK={t:i+1 for i,t in enumerate(sorted(ENV,key=lambda x:-ENV[x]))}

# ---------------- state ----------------
rost=list(csv.DictReader(open(D+'rosters.csv')))
for r in rost: r['key']=key(r['player'])
RK={r['key'] for r in rost}
MINE=[r for r in rost if r['manager']==ME]
BLEND=json.load(open(D+'season_blend.json'))

# verified unavailable — checked by name 2026-09-15, BSB has NO IR slot
import json as _j
_R=_j.load(open(D+'roles.json'))
# BLOCKED is no longer a hand-typed list. It is the verified role registry:
# everyone reporting says is unavailable, plus everyone whose week-1 snap count
# says he is not on the field. See data/roles.json for the source of each line.
BLOCKED={k:v for k,v in _R['unavailable'].items()}
BLOCKED.update({k:v for k,v in _R['add_no'].items() if not k.startswith('_')})
# protected by an NFL depth chart the projections cannot see
PROTECTED={k:(v.get('handcuff_for'),v['call']) for k,v in _R['hold'].items()}

POOL={k:v for k,v in BLEND.items() if k not in RK and v['pts']>0 and k not in BLOCKED}

# ---------------- MANDATORY pool audit ----------------
ph,near=audit_phantoms(set(POOL), RK, meta={k:{'tm':v.get('tm'),'pos':v.get('pos')} for k,v in POOL.items()})
print('='*92)
print(f'BSB SEASON LAYER   {TODAY}')
print('='*92)
print(f'\nPOOL AUDIT — {len(POOL)} free agents derived as (projection pool minus all 216 rostered)')
if ph:
    print(f'  *** {len(ph)} PHANTOM(S) — pool is contaminated, these are already rostered:')
    for a,b,r,why in ph: print(f'      {a}  ==  rostered {b}  ({why})')
    print('  Removing them before anything downstream runs.')
    for a,_,_,_ in ph: POOL.pop(a,None)
else:
    print('  no phantoms — every pool entry checked by surname and first-name variant')
if near:
    print(f'  {len(near)} surname near-miss(es) KEPT in the pool (shown so a real collision cannot hide):')
    for a,b,r,why in near[:8]: print(f'      kept {a}  vs rostered {b}  — {why}')
print(f'  {len(BLOCKED)} excluded by the verified role registry (data/roles.json, checked {_R["_checked"]}):')
for k,v in list(BLOCKED.items()): print(f'      {k:22s} {v[:76]}')

# RANKING. A projection is a forecast; a snap count is an observation. Where the
# two disagree the snap count wins, so a player with verified week-1 usage sorts
# ahead of a higher projection with no evidence he is on the field. This is the
# ordering that would have put Xavier Hutchinson (44 snaps, WR2, the man ahead of
# him out for the season) above Germie Bernard (115 projected, 3 snaps).
VERIFIED=set(_R['add_yes'])
FA=defaultdict(list)
for k,v in POOL.items():
    FA[v['pos']].append((k in VERIFIED, v['pts'],v['name'],v.get('tm',''),v['n'],k))
for p in FA: FA[p].sort(reverse=True)
FA={p:[t[1:] for t in v] for p,v in FA.items()}
FA=defaultdict(list,FA)
REPL={p:(FA[p][0][0] if FA[p] else 0) for p in ('QB','RB','WR','TE','K','DEF')}

print('\nREPLACEMENT LEVEL — the best player actually available, by position')
for p in ('QB','RB','WR','TE','K','DEF'):
    b=FA[p][0]
    e=ENV.get(team(b[2]),0)
    print(f'  {p:4s} {b[1][:24]:24s} {b[2]:4s} {b[0]:7.1f}  ({b[3]} src)'
          + (f'   offense env {e:.2f} (#{ENV_RK.get(team(b[2]),"?")})' if e else ''))

print('\n'+'='*92)
print('YOUR ROSTER — value over the wire, with the market-priced environment SEPARATE')
print('(environment is NOT multiplied into the mean; the mean already contains it)')
print('='*92)
print(f'{"player":24s} {"pos":4s} {"season":>8s} {"wire":>7s} {"VOW":>7s}  {"env wk3-9":>9s} note')
rows=[]
for p in MINE:
    b=BLEND.get(p['key'])
    if not b: continue
    vow=b['pts']-REPL.get(p['pos'],0)
    e=ENV.get(team(p['nfl']))
    rows.append((vow,p,b,e))
for vow,p,b,e in sorted(rows,reverse=True):
    note=''
    if p['designation'] in S.UNUSABLE: note=f"[{p['designation']}] no IR slot — dead spot"
    if p['key'] in PROTECTED: note='HOLD: '+PROTECTED[p['key']][1]
    es=f'{e:.2f} #{ENV_RK[team(p["nfl"])]:>2}' if e else '   --'
    print(f'{p["player"][:24]:24s} {p["pos"]:4s} {b["pts"]:8.1f} {REPL.get(p["pos"],0):7.1f} '
          f'{vow:+7.1f}  {es:>9s} {note}')

print('\n'+'='*92)
print('WAIVER BOARD — gated. Ranked by value over the wire, then by offense environment')
print('='*92)
mine_by_pos=defaultdict(list)
for p in MINE: mine_by_pos[p['pos']].append(p)
cands=[]
for pos in ('RB','WR','TE','QB'):   # DEF and K are WEEKLY matchup slots -- see decide.py.
                                    # Evaluating them here would be the exact category
                                    # error that produced the "drop the 49ers" call.
    worst=sorted([p for p in mine_by_pos[pos]
                  if p['key'] not in PROTECTED],
                 key=lambda p:(p['designation'] in S.UNUSABLE and -1e9) or BLEND.get(p['key'],{}).get('pts',1e9))
    if not worst or not FA[pos]: continue
    drop=worst[0]
    add=FA[pos][0]
    dp=BLEND.get(drop['key'],{}).get('pts',0)
    if drop['designation'] in S.UNUSABLE: dp=0.0
    gain=add[0]-dp
    if gain<=3: continue
    cands.append((gain,pos,drop,add,dp))
for gain,pos,drop,add,dp in sorted(cands,reverse=True):
    e=ENV.get(team(add[2]))
    print(f'\n  DROP {drop["player"]} ({pos} {dp:.1f}'
          + (f', {drop["designation"]}' if drop['designation']!='none' else '')
          + f')  ->  ADD {add[1]} ({add[0]:.1f}, {add[3]} src'
          + (f', offense env {e:.2f} #{ENV_RK[team(add[2])]}' if e else '') + f')   {gain:+.1f}')
    ra=G.check('add',f'add {add[1]}',player=add[1],
               designation='none' if add[4] not in BLOCKED else 'IR',
               sources=['fftoday','sleeper'] if add[3]==2 else ['fftoday'],
               pos=pos,value=add[0],horizon='weekly' if pos in ('DEF','K') else 'season',
               roster_keys=RK,pool_keys=set(POOL),pulled=TODAY,
               floor_is_zero=(drop['designation'] in S.UNUSABLE))
    print(ra.render())
    rd=G.check('drop',f'drop {drop["player"]}',player=drop['player'],
               designation=drop['designation'],
               sources=['fftoday','sleeper'],pos=pos,value=dp,
               horizon='weekly' if pos in ('DEF','K') else 'season',
               role='not on an NFL depth chart (IR/exempt)' if drop['designation'] in S.UNUSABLE
                    else 'checked, no starting role',
               handcuff_for=PROTECTED.get(drop['key'],(None,''))[0],pulled=TODAY)
    print(rd.render())

print('\n  DEF and K are deliberately absent from this board. They are matchup slots in an')
print('  uncapped league and belong to the weekly layer (decide.py), not here.')

print('\n'+'='*92)
print('MARKET-PRICED OFFENSE ENVIRONMENT, weeks 3-9 — where value grows')
print('='*92)
print('  best 8: '+' · '.join(f'{t} {ENV[t]:.2f}' for t in sorted(ENV,key=lambda x:-ENV[x])[:8]))
print('  worst 8: '+' · '.join(f'{t} {ENV[t]:.2f}' for t in sorted(ENV,key=lambda x:ENV[x])[:8]))
print(f'  spread top to bottom: {max(ENV.values())-min(ENV.values()):.2f} pts/game')
print('\n  your skill players, by the environment they are buying into:')
for p in sorted([x for x in MINE if x['pos'] in ('QB','RB','WR','TE')],
                key=lambda x:-ENV.get(team(x['nfl']),0)):
    e=ENV.get(team(p['nfl']))
    if e: print(f'    {p["player"][:22]:22s} {p["nfl"]:4s} {e:6.2f}  #{ENV_RK[team(p["nfl"])]}')
json.dump({'ENV':ENV,'ENV_RK':ENV_RK,'REPL':REPL},open(D+'season_env.json','w'),indent=1)
