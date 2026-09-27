"""HERITAGE HOUSE weekly layer — lineup + free agency, same gate as BSB.

Heritage House has been running on the old pipeline while BSB got rebuilt. This
puts it on the same foundation: one scorer, one eligibility model, one gate, one
set of numbers that do not move between questions.

HH differs from BSB in four ways that actually change decisions:
  - superflex (Q/W/R/T), so a second QB is a real starter
  - six IDP starters, which is where most of the weekly leverage sits
  - 7 acquisitions/week, so roster spots are NOT free the way they are in BSB
  - 3 IR slots, so an injured stud is a stash rather than a dead spot
"""
import sys, csv, json, datetime as dt
from collections import defaultdict
sys.path.insert(0, '/home/claude/bsb2')
import numpy as np
from scipy.optimize import linear_sum_assignment
from lib import gate as G
from lib import hh_score as H
from lib.leagues import HH
from lib.names import key, team, audit_phantoms

D = '/home/claude/bsb2/data/'
ME = 'Tecmo Bowlers'
TODAY = dt.date.today().isoformat()
PULLED = '2026-09-15'          # rosters; Sleeper projections pulled 2026-09-16

def rows(fn):
    try: return list(csv.DictReader(open(D + fn)))
    except FileNotFoundError: return []

# ---------------------------------------------------------------- projections
PROJ = {}
def put(name, tm, pos, pts, fam, opp='', src='sleeper'):
    k = key(name)
    if k in PROJ and PROJ[k]['pts'] >= pts: return
    PROJ[k] = dict(name=name, tm=tm, pos=pos, fam=fam, pts=pts, opp=opp, src=src)

for r in rows('sleeper_off_wk2.csv'):
    p = (r['pos'] or '').upper()
    if p not in ('QB','RB','WR','TE'): continue
    put(r['player'], r['team'], p, H.score_off(r, p), p, r.get('opp',''))

IDP_FAM = {'DE':'DL','DT':'DL','NT':'DL','DL':'DL','LB':'LB','OLB':'LB','ILB':'LB',
           'MLB':'LB','CB':'DB','S':'DB','FS':'DB','SS':'DB','DB':'DB'}
for r in rows('sleeper_idp_wk2.csv'):
    p = (r['pos'] or '').upper()
    fam = IDP_FAM.get(p)
    if not fam: continue
    put(r['player'], r['team'], p, H.score_idp(r, fam), fam, r.get('opp',''))

# K and DEF come from the week-2 offense/special pull used by the BSB engine
for r in rows('sleeper_wk2.csv'):
    p = (r['pos'] or '').upper()
    if p == 'K':   put(r['player'], r['team'], 'K',   H.score_k(r),   'K',   r.get('opp',''))
    elif p == 'DEF': put(r['player'], r['team'], 'DEF', H.score_dst(r), 'DEF', r.get('opp',''))

# ---------------------------------------------------------------- rosters
rost = rows('hh_rosters.csv')
for r in rost:
    r['key'] = key(r['player'])
    r['elig'] = H.yahoo_elig(r['pos'])          # Yahoo's own string — authoritative
    b = PROJ.get(r['key'])
    r['pts'] = b['pts'] if b else None
    r['src'] = b['src'] if b else None
    r['opp'] = b['opp'] if b else ''
RK = {r['key'] for r in rost}
byteam = defaultdict(list)
for r in rost: byteam[r['team_name']].append(r)
MINE = byteam[ME]
assert MINE, f'{ME} not found in hh_rosters.csv'

print('=' * 96)
print(f'HERITAGE HOUSE — Tecmo Bowlers, week 2        rosters {PULLED} · projections 2026-09-16')
print('=' * 96)

missing = [r for r in MINE if r['pts'] is None and r['designation'] not in ('IR','IR-R')]
if missing:
    print('\nNO PROJECTION COVERS THESE ROSTERED PLAYERS — reported as UNKNOWN, never as 0:')
    for r in missing:
        print(f'   {r["player"]:26s} {r["pos"]:8s} {r["nfl"]:4s}  slot {r["slot"]}')

# ---------------------------------------------------------------- lineup
SLOTS = HH.slots
def fill(players, verbose=False):
    R = [p for p in players
         if p['designation'] not in ('IR','IR-R','O','NA','PUP','PUP-R','SUSP')
         and p['pts'] is not None]
    C = np.full((len(R), len(SLOTS)), 1e6)
    for i, p in enumerate(R):
        for j, s in enumerate(SLOTS):
            if p['elig'] & HH.accepts[s]: C[i, j] = -p['pts']
    ri, ci = linear_sum_assignment(C)
    out = {s: None for s in SLOTS}
    for i, j in zip(ri, ci):
        if C[i, j] < 1e5: out[SLOTS[j]] = R[i]
    return out

opt = fill(MINE)
cur = {r['slot']: r for r in MINE if r['slot'] not in ('BN', 'IR')}

print('\n' + '=' * 96)
print('LINEUP — exact max-weight assignment over all 15 slots, Yahoo eligibility')
print('=' * 96)
print(f'{"slot":8s} {"currently starting":26s} {"pts":>7s}   {"optimal":26s} {"pts":>7s}  {"delta":>7s}')
tot_c = tot_o = 0.0
changes = []
for s in SLOTS:
    c, o = cur.get(s), opt.get(s)
    cp = c['pts'] if c and c['pts'] is not None else 0.0
    op = o['pts'] if o else 0.0
    tot_c += cp; tot_o += op
    same = c and o and c['key'] == o['key']
    d = '' if same else f'{op-cp:+7.2f}'
    flag = '' if same else '  <<<'
    if not same: changes.append((s, c, o, op - cp))
    print(f'{s:8s} {(c["player"] if c else "—")[:26]:26s} {cp:7.2f}   '
          f'{(o["player"] if o else "—")[:26]:26s} {op:7.2f}  {d:>7s}{flag}')
print(f'{"":8s} {"TOTAL":26s} {tot_c:7.2f}   {"":26s} {tot_o:7.2f}  {tot_o-tot_c:+7.2f}')

bench = [r for r in MINE if r['slot'] == 'BN']
print('\nbench:')
for r in sorted(bench, key=lambda x: -(x['pts'] or -1)):
    v = f'{r["pts"]:7.2f}' if r['pts'] is not None else '    ???'
    print(f'   {r["player"][:26]:26s} {r["pos"]:8s} {r["nfl"]:4s} {v}'
          + (f'  [{r["designation"]}]' if r['designation'] != 'none' else ''))
ir = [r for r in MINE if r['slot'] == 'IR']
for r in ir:
    print(f'   IR  {r["player"][:22]:22s} {r["pos"]:8s} {r["nfl"]:4s}  [{r["designation"]}]')

NOISE = 1.5
# A max-weight solver will happily PERMUTE two players between two slots both of
# them fill. The per-slot deltas look large and cancel to zero. Reporting that as
# "make these two moves" is noise dressed as analysis, so strip it: a change only
# counts if the SET of starters changes.
cur_set = {r['key'] for r in cur.values() if r}
opt_set = {r['key'] for r in opt.values() if r}
real_in, real_out = opt_set - cur_set, cur_set - opt_set
perm = [s for s, c, o, d in changes if (not c or c['key'] in opt_set) and (not o or o['key'] in cur_set)]
if perm:
    print(f'\n  ({len(perm)} slot(s) are a pure permutation of the same players — net 0.00. Ignored.)')

if not real_in:
    print('\n  LINEUP IS ALREADY OPTIMAL. Nobody on the bench outscores anybody starting.')
for s, c, o, d in changes:
    if not o or o['key'] not in real_in: continue
    print()
    fam = (PROJ.get(o['key']) or {}).get('fam')
    if d < NOISE:
        print(f'  PROVISIONAL  {s}: {o["player"]} ({o["pts"]:.2f}) over '
              f'{c["player"] if c else "empty"} ({c["pts"]:.2f}) is only {d:+.2f} —')
        print(f'               inside the {NOISE}-pt noise band, and no player market is posted')
        print(f'               for this game yet. Not a move. Re-check Saturday.')
        continue
    print(f'  {s}: START {o["player"]} ({o["pts"]:.2f}) over '
          f'{c["player"] if c else "empty slot"}' + (f' ({c["pts"]:.2f})' if c and c["pts"] is not None else ''))
    r = G.check('start', f'{s}: {o["player"]}', player=o['player'],
                designation=o['designation'],
                sources=[o['src']] if o['src'] else [],
                pos=fam, value=o['pts'], horizon='weekly',
                market_ready=False, pulled='2026-09-16', league='HH')
    print(r.render('     '))

# ---- self-check against an independently documented property of this league.
# The league profile (written before this engine existed, off the settings page)
# states: "QB scoring is dominated by completions ... the curve is nearly flat
# (QB1 to QB20 ~ 5 points a week)". If this scorer is right, it must reproduce
# that. If it does not, the scorer is wrong, not the profile.
qbs = sorted([v['pts'] for v in PROJ.values() if v['fam'] == 'QB'], reverse=True)
if len(qbs) >= 20:
    spread = qbs[0] - qbs[19]
    ok = 2.0 <= spread <= 9.0
    print(f'\n  self-check  QB1 {qbs[0]:.1f} - QB20 {qbs[19]:.1f} = {spread:.1f} pts/wk. '
          f'League profile says ~5. {"CONSISTENT" if ok else "*** SCORER DISAGREES WITH THE SETTINGS PAGE ***"}')

# ---------------------------------------------------------------- free agency
print('\n' + '=' * 96)
print('FREE AGENCY — pool derived by subtraction, then audited')
print('=' * 96)
POOL = {k: v for k, v in PROJ.items() if k not in RK}
META = {k: {'tm': v['tm'], 'pos': v['pos']} for k, v in PROJ.items()}
META.update({r['key']: {'tm': r['nfl'], 'pos': r['pos']} for r in rost})
ph, near = audit_phantoms(set(POOL), RK, meta=META)
if ph:
    print(f'  *** {len(ph)} PHANTOM(S) — already rostered, removed before anything downstream:')
    for a, b, rr, why in ph: print(f'      {a} == rostered {b}  ({why})')
    for a, _, _, _ in ph: POOL.pop(a, None)
else:
    print('  no phantoms — every pool entry checked by surname and first-name variant')
if near:
    print(f'  {len(near)} surname near-miss(es) KEPT in the pool, shown so a real one cannot hide:')
    for a, b, rr, why in near[:10]:
        print(f'      kept {a:22s} vs rostered {b:20s} — {why}')
print(f'  {len(POOL)} free agents across {len(set(v["fam"] for v in POOL.values()))} position families')
print(f'  acquisition cap: {HH.acq_cap}/week — a spot here is NOT free, unlike BSB')

FA = defaultdict(list)
for k, v in POOL.items(): FA[v['fam']].append((v['pts'], v['name'], v['tm'], v['pos'], k))
for f in FA: FA[f].sort(reverse=True)

print('\nBEST AVAILABLE, by the slot it would fill:')
for fam in ('QB','RB','WR','TE','DL','LB','DB','K','DEF'):
    for pts, nm, tm, pos, k in FA[fam][:3]:
        print(f'   {fam:4s} {nm[:24]:24s} {tm:4s} {pos:4s} {pts:7.2f}')

# what my worst starter at each family is worth, vs the best free agent
print('\n' + '=' * 96)
print('UPGRADE BOARD — best free agent vs the weakest thing occupying that slot')
print('=' * 96)
FAM_SLOT = {'QB':('QB','Q/W/R/T'),'RB':('RB','W/R','W/R/T'),'WR':('WR','W/R','W/R/T'),
            'TE':('TE','W/R/T'),'DL':('DL','D'),'LB':('LB','D'),'DB':('DB','CB','S','D'),
            'K':('K',),'DEF':('DEF',)}
cands = []
for fam, slots in FAM_SLOT.items():
    if not FA[fam]: continue
    holders = [opt[s] for s in slots if opt.get(s) and fam in
               {IDP_FAM.get(x, x) for x in opt[s]['elig']} | opt[s]['elig']]
    holders = [h for h in holders if h and h['pts'] is not None]
    if not holders: continue
    worst = min(holders, key=lambda x: x['pts'])
    best = FA[fam][0]
    gain = best[0] - worst['pts']
    if gain > 2.0: cands.append((gain, fam, worst, best))

if not cands:
    print('  Nothing on the wire beats a current starter at any position. Hold.')
for gain, fam, worst, best in sorted(cands, reverse=True):
    print(f'\n  {fam}: ADD {best[1]} ({best[0]:.2f}) over {worst["player"]} ({worst["pts"]:.2f})  {gain:+.2f}/wk')
    ra = G.check('add', f'add {best[1]}', player=best[1], designation='__UNREAD__',
                 sources=['sleeper'], pos=fam, value=best[0], horizon='weekly',
                 market_ready=False, roster_keys=RK, pool_keys=set(POOL),
                 pool_meta=META, pulled='2026-09-16', league='HH')
    print(ra.render('     '))

# ---------------------------------------------------------------- bench audit
# "Upside is more important than expected points on the bench. That wins seasons."
# So a bench spot is NOT judged on its mean. It is judged on whether it can win a
# week. BOOM SHARE = the fraction of a player's projected points that comes from
# categories with a fat tail -- touchdowns, sacks, interceptions, forced fumbles,
# recoveries, defensive scores -- rather than from volume (tackles, catches,
# completions, yards). A tackle-driven linebacker projecting 14 is a floor; an
# edge rusher projecting 12 off sacks can put up 30. This is computed from the
# same Sleeper stat lines, not asserted.
BOOM = {}
for r in rows('sleeper_idp_wk2.csv'):
    k = key(r['player']); fam = IDP_FAM.get((r['pos'] or '').upper())
    if not fam: continue
    def f(x):
        try: return float(r.get(x) or 0)
        except ValueError: return 0.0
    vol = f('solo')*H.SOLO + f('ast')*H.ASSIST
    big = (f('sack')*H.IDP_SACK + f('int')*H.IDP_INT + f('pd')*H.PD
           + f('ff')*H.FF + f('fr')*H.FR + f('def_td')*H.IDP_TD + f('tfl')*H.TFL)
    if vol+big > 0: BOOM[k] = big/(vol+big)
for r in rows('sleeper_off_wk2.csv'):
    k = key(r['player'])
    def f(x):
        try: return float(r.get(x) or 0)
        except ValueError: return 0.0
    big = (f('pass_td')+f('rush_td')+f('rec_td'))*5.0
    tot = PROJ.get(k, {}).get('pts') or 0
    if tot > 0: BOOM[k] = max(min(big/tot, 1.0), 0.0)

print('\n' + '=' * 96)
print('BENCH AUDIT — a spot is capital. 7 acquisitions/week here, so it is not free.')
print('=' * 96)
print('  judged on UPSIDE, not mean: boom% = share of projected points from TDs and')
print('  defensive big plays rather than from volume.\n')
print(f'{"bench player":26s} {"fam":4s} {"proj":>7s} {"boom%":>6s}  {"best FA at that family":26s} {"proj":>7s} {"boom%":>6s}')
wasted = []
for r in sorted(bench, key=lambda x: (x['pts'] if x['pts'] is not None else -1)):
    fam = (PROJ.get(r['key']) or {}).get('fam')
    if not fam: continue
    bp = BOOM.get(r['key'])
    alt = FA[fam][0] if FA[fam] else None
    ab = BOOM.get(alt[4]) if alt else None
    print(f'{r["player"][:26]:26s} {fam:4s} {r["pts"]:7.2f} '
          f'{(f"{bp*100:5.0f}%" if bp is not None else "    —"):>6s}  '
          + (f'{alt[1][:26]:26s} {alt[0]:7.2f} ' + (f'{ab*100:5.0f}%' if ab is not None else '    —')
             if alt else ''))
    if alt and alt[0] - r['pts'] > 4 and (bp is None or ab is None or ab >= bp - 0.05):
        wasted.append((alt[0] - r['pts'], r, fam, alt, bp, ab))

# a second DEF or a second K cannot both start. That is a spot spent on nothing.
dups = defaultdict(list)
for r in MINE:
    if r['slot'] != 'IR': dups[(PROJ.get(r['key']) or {}).get('fam')].append(r)
for fam in ('DEF', 'K'):
    if len(dups.get(fam, [])) > 1:
        names = ', '.join(x['player'] for x in dups[fam])
        print(f'\n  ** {len(dups[fam])} {fam}s rostered ({names}) but only one {fam} slot.')
        print(f'     In a 7-acquisition league the backup is a spot spent on a player who')
        print(f'     cannot score. Drop the weaker one for a real bench asset.')

if wasted:
    print('\n  BENCH SPOTS WORTH LESS THAN THE WIRE — both mean AND upside:')
for gain, r, fam, alt, bp, ab in sorted(wasted, reverse=True)[:4]:
    print(f'\n  DROP {r["player"]} ({fam} {r["pts"]:.2f})  ->  ADD {alt[1]} ({alt[0]:.2f})  {gain:+.2f}/wk')
    print(G.check('add', f'add {alt[1]}', player=alt[1], designation='__UNREAD__',
                  sources=['sleeper'], pos=fam, value=alt[0], horizon='weekly',
                  market_ready=False, roster_keys=RK, pool_keys=set(POOL),
                  pool_meta=META, pulled='2026-09-16', league='HH').render('     '))
    print(G.check('drop', f'drop {r["player"]}', player=r['player'],
                  designation=r['designation'], sources=['sleeper'], pos=fam,
                  value=r['pts'], horizon='weekly', role=None,
                  pulled=PULLED, league='HH').render('     '))

json.dump({k: v for k, v in PROJ.items()}, open(D + 'hh_proj_wk2.json', 'w'), indent=0)
print('\nwrote data/hh_proj_wk2.json')
