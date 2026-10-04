"""REGRESSION TEST — every recommendation that had to be corrected today,
replayed through the gate exactly as it was originally made.

If any of these returns PASS, the gate does not work and nothing built on it
should be trusted. Run this before shipping any recommendation.
"""
import sys, csv, datetime as dt
from lib import clock as C
sys.path.insert(0,'/home/claude/bsb2')
from lib import gate as G
from lib.names import key
from lib import state as ST
BSB=ST.load('BSB')
D='/home/claude/bsb2/data/'
TODAY = C.today().isoformat()   # Eastern, like the gate (09-30)
ROSTER={r['key'] for r in BSB.rows}   # live snapshot, not the legacy csv
# the contaminated pool as it actually was: FFToday spelling, no injury field
POOL_BAD={'kenneth gainwell','jordyn tyson','ty johnson','germie bernard'}

CASES=[]

# 1. Gainwell — recommended as the league's best FA running back. He is rostered.
CASES.append(('Kenny/Kenneth Gainwell add', G.check(
    'add','add Kenneth Gainwell as RB',player='Kenneth Gainwell',designation='none',
    sources=['fftoday','sleeper'],pos='RB',value=148.4,horizon='season',
    roster_keys=ROSTER,pool_keys=POOL_BAD,pulled=TODAY)))

# 2. Tyson — top WR add. On IR, designated to return. Pool carried no injury field.
CASES.append(('Jordyn Tyson add (designation never read)', G.check(
    'add','add Jordyn Tyson as WR',player='Jordyn Tyson',
    sources=['fftoday','sleeper'],pos='WR',value=123.7,horizon='season',
    roster_keys=ROSTER,pulled=TODAY)))
CASES.append(('Jordyn Tyson add (designation read = IR)', G.check(
    'add','add Jordyn Tyson as WR',player='Jordyn Tyson',designation='IR',
    sources=['fftoday','sleeper'],pos='WR',value=123.7,horizon='season',
    roster_keys=ROSTER,pulled=TODAY)))

# 3. Ray Davis — flagged as a drop. He is the James Cook handcuff.
CASES.append(('drop Ray Davis for Ty Johnson', G.check(
    'drop','drop Ray Davis',player='Ray Davis',designation='none',
    sources=['fftoday','sleeper'],pos='RB',value=66.3,horizon='season',
    role='Bills RB2',handcuff_for='James Cook',pulled=TODAY)))

# 4. 49ers — recommended as a drop off a SEASON projection.
CASES.append(('drop 49ers DEF on season numbers', G.check(
    'drop','drop 49ers DEF',player='49ers',designation='none',
    sources=['fftoday','sleeper'],pos='DEF',value=85.5,horizon='season',
    role='team defense',pulled=TODAY)))

# 5. Yahoo's roster "points" column, which is actually a RANKING.
CASES.append(('Josh Jacobs valued off the Yahoo rank column', G.check(
    'start','start Josh Jacobs',player='Josh Jacobs',designation='CEL',
    sources=['yahoo'],pos='RB',value=739,horizon='season',pulled=TODAY)))

# 6. Yahoo + Sleeper presented as two independent sources.
CASES.append(('Yahoo + Sleeper called two sources', G.check(
    'add','add a WR on Yahoo+Sleeper agreement',player='Germie Bernard',
    designation='none',sources=['yahoo','sleeper'],pos='WR',value=115.2,
    horizon='season',roster_keys=ROSTER,pulled=TODAY)))

# 7. A Sunday start/sit answered on Tuesday with no market posted.
CASES.append(('Sunday start/sit answered before the market posts', G.check(
    'start','start Jauan Jennings at WR3',player='Jauan Jennings',designation='none',
    sources=['sleeper'],pos='WR',value=9.1,horizon='weekly',market_ready=False,
    pulled=TODAY)))

# 8. Stale inputs.
CASES.append(('replacement level pulled 4 days ago', G.check(
    'drop','drop a bench WR',player='Keon Coleman',designation='none',
    sources=['fftoday','sleeper'],pos='WR',value=63.7,horizon='season',
    role='Bills WR3',pulled='2026-09-11')))

# 9. The phantom audit eating REAL free agents. On 2026-09-16 it flagged
#    "Josh Hines-Allen" as Josh Allen and "Brian Robinson" as Bijan Robinson,
#    and the caller deleted both from the pool. A silent deletion is the one
#    failure mode a pool audit must not have.
from lib.names import audit_phantoms as _ap
_META={'josh hines allen':{'tm':'JAX','pos':'DE'},'brian robinson':{'tm':'WAS','pos':'RB'},
       'kenneth gainwell':{'tm':'TB','pos':'RB'},
       'josh allen':{'tm':'BUF','pos':'QB'},'bijan robinson':{'tm':'ATL','pos':'RB'},
       'kenny gainwell':{'tm':'TB','pos':'RB'}}
_ph,_near=_ap({'josh hines allen','brian robinson','kenneth gainwell'},
              {'josh allen','bijan robinson','kenny gainwell'},meta=_META)
_names={a for a,_,_,_ in _ph}
_phantom_ok = (_names=={'kenneth gainwell'})
print('='*88)
print('POOL-AUDIT REGRESSION (runs before the gate cases)')
print('='*88)
print(f'  removed as phantoms : {sorted(_names) or "none"}')
for a,b,r,why in _near: print(f'  KEPT {a:22s} vs rostered {b:18s} — {why}')
print(f'[{"OK " if _phantom_ok else "FAIL"}] Gainwell caught, Hines-Allen and Brian Robinson kept')

# 10. Germie Bernard: 115 projected points, THREE offensive snaps in week 1.
#     The projection-only model ranked him the best available WR in the league.
CASES.append(('Germie Bernard add on projection alone (3 snaps wk1)', G.check(
    'add','add Germie Bernard as WR',player='Germie Bernard',designation='none',
    sources=['fftoday','sleeper'],pos='WR',value=115.2,horizon='season',
    roster_keys=ROSTER,pulled=TODAY)))

# 11. Ty Johnson: best available RB by projection. Buffalo RB3, behind Ray Davis,
#     inactive in week 1 with a hamstring.
CASES.append(('Ty Johnson add as best FA RB', G.check(
    'add','add Ty Johnson as RB',player='Ty Johnson',designation='none',
    sources=['fftoday'],pos='RB',value=81.1,horizon='season',
    roster_keys=ROSTER,pulled=TODAY,floor_is_zero=True)))

# 12. Dropping Josh Jacobs to fill the dead spot. Exempt-list games count toward
#     the suspension; he is a top-10 RB likely back before the playoff weeks.
CASES.append(('drop Josh Jacobs off the exempt list', G.check(
    'drop','drop Josh Jacobs',player='Josh Jacobs',designation='CEL',
    sources=['fftoday','sleeper'],pos='RB',value=0.0,horizon='season',
    role='Commissioner Exempt List',pulled=TODAY)))

# --- controls: these SHOULD pass, or the gate is merely a blocker
# A start call must be for a player NOT already starting, with a posted market
# and two families, against fresh state. Ray Davis is on the bench in live state
# and his game (BUF, Thursday) is market-priced. Mechanics control only — so
# the state copy is stamped fresh: the pump has no Friday pull, and a control
# that fails on wall-clock age (2026-09-25, 20h-old snapshot) tests the
# calendar, not the gate. Staleness itself is tested by G12 in ff.py run.
import copy as _copy
_FRESH=_copy.copy(BSB); _FRESH.pulled=C.now().isoformat(timespec='minutes'); _FRESH.others_pulled=_FRESH.pulled
CASES.append(('CONTROL start a benched player with a posted market (should PASS)', G.check(
    'start','start Ray Davis at W/R/T',player='Ray Davis',designation='none',
    sources=['kalshi','sleeper'],pos='RB',value=3.86,horizon='weekly',
    market_ready=True,pulled=TODAY,state=_FRESH)))
# Controls are DERIVED from live state, never hard-coded: on 2026-09-16 the
# Dell drop and the Hutchinson add both executed overnight, and the hard-coded
# controls then failed for the right reason (already true / already rostered).
import json as _json
_R=_json.load(open(D+'roles.json'))
_drop=next((r for r in BSB.bench() if r['key'] in _R['drop_ok']), None)
# A registry add_yes entry older than 14 days is demoted (lib/rules.py, contract C16):
# week-1 usage is not evidence in week 4. The control's premise is a free agent with
# OBSERVED usage, so it takes a still-fresh add_yes entry when one is free, else the
# player's row in the newest weekly usage pull (the other form G11 accepts).
from lib import rules as _RU, usage as _U
_fresh=[k for k in _RU.load_roles(D+'roles.json').get('add_yes',{}) if not k.startswith('_')]
_add=next((n for n in _fresh+['Antonio Williams','Malachi Fields','T.J. Hockenson'] if BSB.owner_of(n) is None), None)
_use=None
if _add and key(_add) not in _fresh:
    for _w in range(C.nfl_week(), 0, -1):
        _row=_U.load(_w).get(key(_add))
        if _row: _use=f"{_row['snap_share']:.0%} of snaps, {_row['tgt_share']:.0%} target share, week {_w} usage pull"; break
if _drop:
    CASES.append((f'CONTROL drop a drop_ok bench player ({_drop["player"]}) (should PASS)', G.check(
        'drop',f'drop {_drop["player"]}',player=_drop['player'],designation=_drop['designation'],
        sources=['sleeper','usage'],pos='WR',value=60.0,horizon='season',
        role=_R['drop_ok'][_drop['key']]['why'],pulled=TODAY,state=_FRESH)))
if _add:
    _fresh = _FRESH
    CASES.append((f'CONTROL add a usage-verified free agent ({_add}) with a fresh league read (should PASS)', G.check(
        'add',f'add {_add}',player=_add,designation='none',
        sources=['fftoday','usage'],pos='WR',value=78.0,horizon='season',
        roster_keys={r['key'] for r in BSB.rows},pulled=TODAY,state=_fresh,usage=_use)))
    # 14. Fields 09-23: 'unrostered, checked against every roster' — against a league read
    #     three days old, from BEFORE Wednesday's waiver run. He had been claimed.
    _stale = _copy.copy(BSB); _stale.others_pulled = (C.bsb_waiver_deadline() - C.dt.timedelta(days=3)).isoformat(timespec='minutes')
    CASES.append((f'add {_add} on a league read older than the last waiver run', G.check(
        'add',f'add {_add}',player=_add,designation='none',
        sources=['fftoday','usage'],pos='WR',value=78.0,horizon='season',
        roster_keys={r['key'] for r in BSB.rows},pulled=TODAY,state=_stale)))

# 13. The 49ers were ALREADY in the DEF slot when the card said "swap them in".
#     A start call on a player who is already starting must not come back PASS.
#     (whichever DEF is in the slot NOW — 10-01: the Vikings replaced the 49ers and the
#      literal name made the case fail on the runner)
_cur_def = next((r['player'] for r in BSB.starters() if r['pos'] == 'DEF'), '49ers')
CASES.append((f'start {_cur_def} when they are already starting', G.check(
    'start',f'start {_cur_def} DEF',player=_cur_def,designation='none',
    sources=['vegas','sleeper'],pos='DEF',value=10.16,horizon='weekly',
    market_ready=True,pulled=TODAY,state=BSB)))

bad=0 if _phantom_ok else 1
print('='*88)
print('GATE REGRESSION — replaying every call that had to be corrected')
print('='*88)
for label,r in CASES:
    expect_pass = label.startswith('CONTROL')
    ok = (r.verdict=='PASS') == expect_pass
    if not ok: bad+=1
    print(f'\n[{"OK " if ok else "FAIL"}] {label}')
    print(r.render())
print('\n'+'='*88)
print(f'{len(CASES)+1-bad}/{len(CASES)+1} behaved as required.'
      + ('  GATE IS SOUND.' if bad==0 else f'  {bad} FAILURES — do not ship.'))
sys.exit(1 if bad else 0)
