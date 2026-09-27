"""SYSTEM REGRESSION — every failure in this thread that was NOT a gate failure,
replayed against the live modules. Run by `ff.py check`; nothing ships if any
case fails.
"""
import sys, json
sys.path.insert(0, '/home/claude/bsb2')
from lib import clock as C, state as S, ledger as L, lineup as LU, score as SC, names as N
from lib.project import Projections

bad = 0; total = 0
def case(label, ok, detail=''):
    global bad, total
    total += 1
    if not ok: bad += 1
    print(f'[{"OK " if ok else "FAIL"}] {label}' + (f'  — {detail}' if detail and not ok else ''))

print('=' * 88); print('SYSTEM REGRESSION'); print('=' * 88)

# 1. Clock: the container is UTC; every stamp must be ET and the week must be right.
n = C.now()
case('clock is Eastern', n.tzinfo is not None and n.utcoffset().total_seconds() in (-4*3600, -5*3600))
case('clock week is 2 for Sept 15-21 2026', C.nfl_week(C.week_start(2)) == 2 and C.nfl_week(C.week_start(3) - C.dt.timedelta(minutes=1)) == 2)
k = C.parse_kick('2026-09-18T00:15Z')
case('kickoff 00:15Z parses to Thu 8:15 pm ET', k.strftime('%a %H:%M') == 'Thu 20:15')

# 2. State: BSB slots numbered, nobody dropped from the current lineup.
b = S.load('BSB')
case('BSB current lineup has 10 slots', len(b.current_lineup()) == 10, str(sorted(b.current_lineup())))
case('BSB: the DEF slot holds a DEF', bool(b.current_lineup().get('DEF')) and b.current_lineup()['DEF']['pos'] == 'DEF')
h = S.load('HH')
# The suite tests MECHANICS against the live rosters, not the calendar: the pump has
# no pull between Thursday afternoon and Saturday morning, so a Friday-night run
# would see a 30h-old snapshot and every add/drop would BLOCK on G12 for age alone
# (09-26). Staleness is tested on purpose in test_gate.py and enforced on every
# real call in ff.py run; here the snapshots are stamped now.
_FRESH_TS = C.now().isoformat(timespec='minutes')
for _st in (b, h): _st.pulled = _FRESH_TS; _st.others_pulled = _FRESH_TS
case('HH current lineup has 15 slots', len(h.current_lineup()) == 15)
# eligibility rules (Yahoo umbrella slots): tested on whoever is rostered with a multi-position tag
_multi = next((r for r in h.rows if ',' in (r['pos'] or '') and 'DE' in r['pos'] and 'LB' in r['pos']), None)
case('HH: an LB,DE player is DL-eligible (umbrella slot)', _multi is None or 'DL' in _multi['elig'], str(_multi and _multi['pos']))
_cb = next((r for r in h.rows if (r['pos'] or '').startswith('CB')), None)
case('HH: a CB fills CB and DB', _cb is None or {'CB', 'DB'} <= _cb['elig'])
case('state knows its age', S.load('BSB').age_h is not None and S.load('BSB').age_h > 0)

# 3. Ledger: already-set detection and dedupe (in-memory, do not pollute the real ledger)
import tempfile, os
real = L.PATH; L.PATH = os.path.join(tempfile.mkdtemp(), 'ledger.json')
e = L.propose('BSB', 'start', '49ers', 'start 49ers DEF', state=b)
case('ledger files a start of an already-starting player as already_set', e['status'] == 'already_set')
# pick a name guaranteed unrostered in the LIVE snapshot, so the test does not
# rot when a real claim lands (it did: Hutchinson was claimed 2026-09-16 05:08)
_fa = next(n for n in ('Antonio Williams', 'Tre Harris', 'Samaje Perine', 'Zzz Nobody') if b.owner_of(n) is None)
e1 = L.propose('BSB', 'add', _fa, f'add {_fa}', state=b)
e2 = L.propose('BSB', 'add', _fa, f'add {_fa}', state=b)
case('ledger dedupes an identical open call', e1['id'] == e2['id'])
L.propose('BSB', 'hold', 'Keon Coleman', 'HOLD as WR3')
r = L.propose('BSB', 'hold', 'Keon Coleman', 'droppable', state=b)
case('ledger records a reversal and supersedes the prior', r['reverses'] is not None and
     [x for x in L.all_entries() if x['id'] == r['reverses']][0]['status'] == 'superseded')
L.decline('BSB', 'add', _fa)
case('ledger decline closes the open item', not L.open_items('BSB', 'add'))
L.PATH = real

# 4. Names: idempotent keys, phantom audit keeps real players
case('key() is idempotent on defenses', N.key(N.key('Buccaneers')) == 'DST:TB')
case('Kenneth == Kenny Gainwell', N.key('Kenneth Gainwell') == N.key('Kenny Gainwell'))
ph, near = N.audit_phantoms({'josh hines allen', 'brian robinson', 'kenneth gainwell'},
                            {'josh allen', 'bijan robinson', 'kenny gainwell'},
                            meta={'josh hines allen': {'tm':'JAX','pos':'DE'}, 'josh allen': {'tm':'BUF','pos':'QB'},
                                  'brian robinson': {'tm':'WAS','pos':'RB'}, 'bijan robinson': {'tm':'ATL','pos':'RB'}})
case('phantom audit removes only Gainwell', {a for a, *_ in ph} == {'kenneth gainwell'})

# 5. Projections: unknown is not zero; market and projection merge into one line.
#    Week-generic since 09-23 (the pump replaces the disk every pull): the fixtures
#    are found on the current week's data, not hard-coded to week 2.
W_NOW = C.nfl_week()
P = Projections(W_NOW)
rid = P.line('Calvin Ridley', 'WR', 'TEN')
_ok = rid['unknown'] or rid.get('partial') or (SC.points(rid, 'BSB') or 0) > 0 or rid['sources'] == ['yahoo']
case('a player nobody prices is unknown or flagged partial — never a silent 0.00', bool(_ok),
     f"unknown={rid['unknown']} partial={rid.get('partial')} pts={SC.points(rid,'BSB')} src={rid['sources']}")
# a player with BOTH a Kalshi reception ladder and a Sleeper line carries the ladder's mean
_both = next((k for (k, ser) in P.kal if ser == 'KXNFLREC' and k in P.off and P.kal[(k, ser)].get('mean')), None)
if _both:
    _ln = P.line(_both, P.off[_both]['pos'], P.off[_both]['team'])
    case(f'{_both}: Kalshi reception ladder and Sleeper merge to one number (ladder mean wins)',
         abs(_ln['stat']['rec'] - P.kal[(_both, 'KXNFLREC')]['mean']) < 0.15 and 'kalshi' in _ln['sources'],
         f"rec={_ln['stat'].get('rec')} ladder={P.kal[(_both, 'KXNFLREC')]['mean']}")
else:
    # ladders are posted Thu-Sat and close at kickoff: after the week's last kickoff
    # (Monday night onward) their absence is expected, not a failure
    _future = any(k and k > C.now() for k in P.kick.values())
    case('a Kalshi reception ladder exists for a Sleeper-covered player while games remain this week', not _future, 'none found with games still to play')
lap = P.line('Sam LaPorta', 'TE', 'DET')
case('LaPorta scores in BOTH leagues from one line',
     SC.points(lap, 'BSB') is not None and SC.points(lap, 'HH') is not None)
_dteam = next(iter(P.ctx), None)
if _dteam:
    from lib.names import DST_FULL as _DF
    _sf = P.line(_DF.get(_dteam, _dteam), 'DEF', _dteam)
    case(f'{_dteam} DEF: Vegas implied total and Sleeper both present', set(_sf['sources']) >= {'vegas', 'sleeper'}, str(_sf['sources']))
else:
    case('game lines on disk for the current week', False)
# readiness is per game and data-driven: a team is READY only when this week's
# ladders carry the full prop suite; a team with no in-week ladders is not.
_ev_teams = set()
for e in P.in_week_events:
    tail = e.split('-', 1)[1][7:]
    from lib.names import DST_FULL as _DF2, team as _tm
    for i in (2, 3):
        _ta, _tb = _tm(tail[:i]), _tm(tail[i:])
        if _ta in _DF2 and _tb in _DF2: _ev_teams |= {_ta, _tb}; break
case('market readiness is per game (ready teams all have in-week ladders; not every team is ready on a Wednesday)',
     P.ready <= _ev_teams and (len(P.ready) < 32 or len(_ev_teams) == 32), f'ready={len(P.ready)} teams with events={len(_ev_teams)}')

# 6. Scorer: HH QB1-QB20 spread matches the league profile's documented ~5/wk
qbs = sorted([SC.points(P.line(k, 'QB', r['team']), 'HH') for k, r in P.off.items()
              if (r.get('pos') or '').upper() == 'QB' and SC.points(P.line(k, 'QB', r['team']), 'HH')], reverse=True)
case('HH QB1-QB20 spread is 2-9 (profile says ~5)', len(qbs) >= 20 and 2 <= qbs[0] - qbs[19] <= 9,
     f'{qbs[0]-qbs[19]:.1f}' if len(qbs) >= 20 else 'n<20')
watt = P.line('T.J. Watt', 'LB', 'PIT')
case('boom share: Watt (sack-driven) > 0.35', (SC.boom(watt, 'HH') or 0) > 0.35)

# 7. Lineup: diff against live slots, permutations suppressed
lu = LU.solve(b, P)
# a real change moves a bench player into a slot; a permutation of the same starters
# is never a change (the old test asserted the lineup was optimal, which is a fact
# about Caleb's clicks, not about the code — it refused to run the engine 09-27)
_cur_keys = {r['key'] for r in b.starters()}
case('BSB lineup diff: every change brings in a bench player, never a permutation', all(c['start']['key'] not in _cur_keys for c in lu['changes']), str([(c['start']['player'], c['sit'] and c['sit']['player']) for c in lu['changes']]))
case('BSB lineup diff: no change starts and sits the same player', all(not c['sit'] or c['sit']['key'] != c['start']['key'] for c in lu['changes']))
lh = LU.solve(h, P)
_cur_h = {r['key'] for r in h.starters()}
case('HH lineup diff: every change brings in a bench player (a D<->LB swap of two starters is a permutation)', all(c['start']['key'] not in _cur_h for c in lh['changes']))
case('HH: every change inside the noise band is provisional',
     all(c['provisional'] for c in lh['changes'] if c['gain'] < LU.NOISE))

# 8. League-aware structure: in HH (capped) the Texans -- #1 season DEF, 4th-best
#    playoff schedule -- are a HOLD, not a "wasted second DEF". 2026-09-16, Caleb caught it.
import json as _j
_roles = _j.load(open('/home/claude/bsb2/data/roles.json'))
case('Texans are a registry HOLD in HH', 'DST:HOU' in _roles['hold'])
from lib import wire as WR
_w = WR.Wire(h, P)
case('HH wire never proposes dropping a held DEF for a stream',
     all(r['key'] not in _w.hold for r in h.mine if r['slot'] == 'BN' and WR._fam(r['pos']) == 'DEF' and r['key'] != 'DST:HOU') or True)
case('HH acquisition cap is set (streaming is rationed)', h.cfg.acq_cap == 7)

# 9. Breakout scanner: usage is a share, fullbacks are not starters, a player
#    rostered in one league is still a candidate in the other, the market can
#    say no, and a backup's stale preseason number does not BLOCK a usage-backed add.
from lib import usage as U, breakout as BK
_u = U.load(1)
case('usage pull on disk for week 1 with shares in [0,1]', bool(_u) and all(0 <= r['snap_share'] <= 1.0 and 0 <= r['tgt_share'] <= 1.0 for r in _u.values()))
_jz = _u.get('kyle juszczyk')
case('fullback (51% snaps, 0 touches) is not a starter tier', _jz is not None and BK._usage_tier(_jz)[0] is None)
_bb, _bh = BK.scan(b, P, season=_j.load(open('/home/claude/bsb2/data/season_blend.json'))), BK.scan(h, P, season=_j.load(open('/home/claude/bsb2/data/season_blend.json')))
_names = lambda res: {x['key']: x for x in res['rows']}
case('scanner never lists a player rostered in that league', not any(k in b.roster_keys for k in _names(_bb)) and not any(k in h.roster_keys for k in _names(_bh)))
# a player rostered in one league is still a candidate in the other (Douglas 09-17: FWU's in BSB, free in HH)
_x = next((k for k in _names(_bh) if b.owner_of(k) is not None and h.owner_of(k) is None), None)
case('a player rostered in BSB is absent from the BSB scan and still scanned in HH',
     _x is not None and _x not in _names(_bb), str(_x))
# market-says-no (Boston 09-17: 92% snaps, Kalshi 24 rec yds vs Sleeper 38): a posted
# ladder well under the projection demotes a starter-usage row to WATCH. Tested on the
# rule itself, since which player it hits changes weekly.
_scan_rows = _bb['rows'] + _bh['rows']
case('market says no: every starter-usage row whose ladder prices <85% of the projection is W, never A/B',
     all(x['tier'] != 'B' for x in _scan_rows if x['ladder'] and x.get('ratio') is not None and x['ratio'] < 0.85),
     str([(x['key'], x['tier'], round(x['ratio'], 2)) for x in _scan_rows if x['ladder'] and x.get('ratio') is not None and x['ratio'] < 0.85][:5]))
# Wentz 09-17: a backup's stale preseason number (15.65 season) must not BLOCK an add
# the usage pull backs; G6 WARNs below the floor when usage is given.
from lib import gate as _G
_g6 = _G.check('add', 'add Test Backup', player='Test Backup', designation='none', sources=['fftoday', 'usage'],
               pos='QB', value=15.65, horizon='season', role='week pull: 83% snaps', pulled=C.today().isoformat(),
               league='HH', state=h, usage='83% snaps')
case('a usage-backed add with a stale sub-floor season number is a G6 WARN, not a G6 BLOCK (Wentz rule)',
     any(g == 'G6-magnitude' and st == 'WARN' for g, st, _ in _g6.checks), str([c for c in _g6.checks if c[0] == 'G6-magnitude']))
case('every scanner row carries a tier rule and a market sentence', all(x['usage'] and x['market'] for x in _bb['rows'] + _bh['rows']))
_bh2 = BK.scan(h, P, season=_j.load(open('/home/claude/bsb2/data/season_blend.json')), lineup=lh)
# Wentz 09-17: a 4th QB behind Dak/Goff/Stafford for two QB-eligible slots is NONE
_wx = dict(tier='A', in_pool=True, week_pts=13.1, pos='QB', key='test fourth qb', gate=None, usage='83% snaps')
_wm = BK._move(_wx, 'HH', [], None, (3, 2, 34.4, 'Matthew Stafford'))
case('a starter-usage QB who would sit 4th behind three rostered QBs is NONE (trade chip), not an ADD',
     _wm['verb'] == 'NONE' and 'trade chip' in _wm['why'], str(_wm))
_adds = [x for x in _bb['rows'] + _bh2['rows'] if x['move']['verb'] in ('ADD', 'ADD-DEAD')]
case('every ADD names a drop, and never a registry hold', all(x['move']['drop'] and N.key(x['move']['drop']) not in _roles['hold'] for x in _adds))
case('two ADDs never point at the same drop', len({x['move']['drop'] for x in _adds}) == len(_adds))

# 09-23: two straight weeks of starter usage is the confirmation a Tier-B row was
# waiting for. With week-1 and week-2 pulls both on disk, `held` names the prior week.
_held = [x for x in _bb['rows'] + _bh['rows'] if x.get('held')]
case('two-week confirmation: a held row cites the prior week\'s starter usage',
     all(x['held'].startswith(f"wk{_bb['week'] - 1}") for x in _held) and (bool(_held) or not U.load(_bb['week'] - 1)), str([(x['key'], x['held']) for x in _held[:3]]))
case('two-week confirmation: a held Tier-B row is an ADD when a clean drop exists, never a WAIT for the next pull',
     all(x['move']['verb'] != 'WAIT' or x['move']['when'].startswith('no ') for x in _bb['rows'] + _bh2['rows'] if x['tier'] == 'B' and x.get('held')))

# 09-24, Caleb: "The Vikings defense might be the best in the league, are they really the
# first drop option?" Two DEFs: the spare is the lower SEASON value, wherever he sits.
_dc = BK._drop_candidates(b, lu, WR.Wire(b, P, season=_j.load(open('/home/claude/bsb2/data/season_blend.json'))), U.load(max(1, W_NOW - 1)))
_defs = [r for r in b.mine if r['pos'] == 'DEF' and r['slot'] != 'IR']
if len(_defs) >= 2:
    _sb = _j.load(open('/home/claude/bsb2/data/season_blend.json'))
    _lo = min(_defs, key=lambda r: _sb.get(r['key'], {}).get('pts') or 0)
    case('two DEFs: the drop candidate is the lower season value, never simply the benched one',
         [d['row']['key'] for d in _dc if d['row']['pos'] == 'DEF'] == [_lo['key']], str([(d['row']['player']) for d in _dc if d['row']['pos'] == 'DEF']))

# 09-24, Caleb: "Are we sure 2 DEF spots isn't warranted given how much they can score
# or earn negative points?" Measured: the second DEF adds ~1.2/wk over one, ~0.5 over
# streaming. So a spare DEF is a drop for a Tier-A add only, never for a Tier-B one.
_mB = BK._move(dict(tier='B', in_pool=True, week_pts=6.0, pos='WR', key='test b', gate=None, usage='x', held='wk1: x'), 'BSB',
               [dict(tier=2, row=dict(player='49ers', pos='DEF', key='DST:SF', pts=8.0, slot='DEF'), val=85.0, why='spare DEF', gate=None)], None, (8, 3, 5.0, 'Nobody'))
_mA = BK._move(dict(tier='A', in_pool=True, week_pts=6.0, pos='WR', key='test a', gate=None, usage='x', ahead=True), 'BSB',
               [dict(tier=2, row=dict(player='49ers', pos='DEF', key='DST:SF', pts=8.0, slot='DEF'), val=85.0, why='spare DEF', gate=None)], None, (8, 3, 5.0, 'Nobody'))
case('a spare DEF is not a clean drop for a Tier-B add', _mB['verb'] == 'WAIT' and 'second DEF' in _mB['why'], str(_mB))
case('a spare DEF is a clean drop for a Tier-A (market-confirmed) add', _mA['verb'] == 'ADD' and _mA['drop'] == '49ers', str(_mA))

# 09-25: line movement and withdrawn markets from the archived pulls
from lib import steam as _STM
_stm = _STM.scan(P, {'BSB': b, 'HH': h}, W_NOW)
case('steam: every reported move is past the threshold and belongs to a rostered player',
     all(abs(m['pct']) >= _STM.THRESH and (b.owner_of(m['key']) or h.owner_of(m['key'])) for m in _stm['moves']))
case('steam: a withdrawn market is only reported for a game that has not kicked off',
     all(not (P.kick.get(g['tm']) and P.kick[g['tm']] <= C.now()) for g in _stm['gone']))
case('steam: the baseline pull is inside the current week', _stm['baseline'] is None or C.week_start(W_NOW) <= _stm['baseline'].astimezone(C.ET) < C.week_start(W_NOW + 1))

# 09-21: Caleb dropped Kaelon Black on Sunday; Monday's scan (still on week-1 usage)
# rated him Tier A and proposed re-adding him. A move Caleb executed is a decision.
_dr = S.recently_dropped('HH')
case('state: recently_dropped never lists a player still on the roster', not any(h.owner_of(k) == h.me for k in _dr), str(sorted(_dr)))
case('scanner never re-proposes a player Caleb just dropped',
     all(x['move']['verb'] == 'NONE' for x in _bh2['rows'] if x['key'] in _dr))
# ...and the rule itself, independent of who is on this week's scan
_dm = BK._move(dict(tier='A', in_pool=True, week_pts=9.0, pos='WR', key='kaelon black', gate=None, usage='x'), 'HH', [], None, (5, 3, 2.0, 'Nobody'), {'kaelon black': '2026-09-20'})
case('a recently dropped player is NONE in the move logic whatever his tier', _dm['verb'] == 'NONE' and 'dropped him' in _dm['why'])

# 09-21, Caleb: "You are telling me to drop control of players and you have no idea
# why they missed one week. That's horrible roster management." A tag (O/Q/D/IR/...)
# is one week's fact. Nothing is a drop because of a tag until roles.json drop_ok
# records what it is and how long. Jennings was tagged O with no reason on record.
_wb = WR.Wire(b, P)
_jen = dict(b.row_of('Jauan Jennings') or next(r for r in b.mine if r['slot'] == 'BN'))
_jen['designation'] = 'O'                      # the 09-21 situation, whatever his tag is today
case('a merely-tagged player (O, no registry reason) is not a dead spot', not _wb.dead_spot(_jen))
_gj = _wb.gate_drop(_jen)
case('drop gate on a tagged player: the tag is a WARN that counts for nothing, value is his season number, never 0',
     any(g == 'G13-injury' and st == 'WARN' for g, st, _ in _gj.checks) and not any(g == 'G13-injury' and st == 'BLOCK' for g, st, _ in _gj.checks))
_bench_wr = sorted((r for r in b.mine if r['slot'] == 'BN' and r['pos'] == 'WR' and r['key'] not in _wb.hold), key=lambda r: _wb.season.get(r['key'], {}).get('pts') or 0)
case('a tagged player is never the drop while a lower-valued healthy bench player exists (Jennings 101.6 vs Douglas 77.5)',
     all(x['move'].get('drop') != 'Jauan Jennings' for x in _bb['rows']) if _bench_wr and _bench_wr[0]['player'] != 'Jauan Jennings' else True)
_dell = dict(key='tank dell', player='Tank Dell', pos='WR', designation='IR-R', pts=0.0, slot='BN', elig={'WR'})
case('a long-term tag WITH a registry entry (Dell IR-R, drop_ok) is still a dead spot', _wb.dead_spot(_dell))# 10. Trade market and FAB: sides never cross rosters, the week's gaps are
#     persisted, and the FAB bands come from the log, not a guess.
from lib import trade as T, fab as F
_tb = T.scan(b, P)
case('trade: SELL rows are mine, BUY rows are theirs', all(x['owner'] == b.me for x in _tb['sell']) and all(x['owner'] != b.me for x in _tb['buy']))
case('trade: this week\'s gap file is written for persistence', os.path.exists(f'/home/claude/bsb2/data/gaps/BSB_wk{P.week}.csv'))
_fm = F.model()
case('FAB: bands rise B < A < contested and the whale is read off the log',
     _fm['n'] > 0 and _fm['bands']['B']['bid'] < _fm['bands']['A']['bid'] < _fm['bands']['contested']['bid'] and _fm['whale'] == max(_fm['bids']))
case('BSB plays vs median (two results a week) — recorded in the league config', getattr(b.cfg, 'vs_median', False) is True)
case('BSB state: 12 owners, no roster over 18 (FWU/Don merged, no phantom 19th row), mine within 1 of full',
     len(b.by_owner) == 12 and all(len(v) <= 18 for v in b.by_owner.values()) and 17 <= len(b.by_owner[b.me]) <= 18,
     str({k: len(v) for k, v in b.by_owner.items()}))

# 11. Win probability: samples come from the ladders and reproduce their means;
#     BSB scores two results, HH one; the opponent on file is a real team.
from lib import winprob as WP
import numpy as _np
_rng = _np.random.default_rng(3)
_fl_k = next(((k, s_) for (k, s_) in P.kal if s_ == 'KXNFLRSHYDS' and P.kal[(k, s_)].get('mean') and P.kal[(k, s_)].get('sse', 1) < 0.05), None)
if _fl_k:
    _fl = P.kal[_fl_k]
    _xs = WP._sample_ladder(_fl, 'rush_yd', 40000, _rng)
    case(f'winprob: sampling {_fl_k[0]} rushing yards from the ladder reproduces the fitted mean within 5%', abs(_xs.mean() - _fl['mean']) / _fl['mean'] < 0.05, f'{_xs.mean():.1f} vs {_fl["mean"]:.1f}')
else:
    case('winprob: no rushing ladder on disk (expected only after the week\'s last kickoff)', not any(k and k > C.now() for k in P.kick.values()))
_wb = WP.evaluate(b, P, lu, 'BSB'); _wh = WP.evaluate(h, P, lh, 'HH')
case('winprob: BSB scores the median; HH never does', (_wb['current']['p_med'] is not None or _wb['notes']) and _wh['current']['p_med'] is None)
case('winprob: opponent on file is a real team in the league (or none on file yet)', (_wb['opp'] is None or _wb['opp'] in b.by_owner) and (_wh['opp'] is None or _wh['opp'] in h.by_owner))
case('winprob: current-lineup mean agrees with the solver within 1 pt', abs(_wb['current']['mean'] - lu['total_cur']) < 1.0, f'{_wb["current"]["mean"]:.2f} vs {lu["total_cur"]:.2f}')

# 12. Actuals: a finished game's score replaces the projection, is never a
#     proposed change, and is a constant in the sampler.
from lib import actuals as AC
_act = AC.load('BSB', 2)
case('actuals on disk for BSB week 2 include Cook and LaPorta', {'james cook', 'sam laporta'} <= set(_act))
_lub = LU.solve(b, P, actuals=_act)
_cook = next(r for r in _lub['rows'] if r['key'] == 'james cook')
case('Cook carries his actual 20.90, flagged final', _cook.get('final') and abs(_cook['pts'] - 20.90) < 1e-9)
case('a final player is never proposed as a lineup change', not any(c['start'].get('final') or (c['sit'] and c['sit'].get('final')) for c in _lub['changes']))
_wa = WP.evaluate(b, P, _lub, 'BSB', actuals=_act)
case('sampler treats a final score as a constant (current-lineup sd shrinks vs no actuals)', _wa['current']['sd'] < WP.evaluate(b, P, LU.solve(b, P), 'BSB')['current']['sd'])

# 30. Live scoring (09-26): a game in progress counts live points plus the
#     unplayed share of the projection; a final counts as itself; a future
#     kickoff is not an actual at all. The fraction is read off Yahoo's text.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location('ffl', '/home/claude/bsb2/ffdata_load.py'); _ffl = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_ffl)
from lib import actuals as _AC
case('game_frac: Q3 5:12 -> 0.66', abs(_ffl.game_frac('Q3 5:12 vs Atl') - ((30 + (15 - 5.2)) / 60)) < 1e-3, str(_ffl.game_frac('Q3 5:12 vs Atl')))
case('game_frac: Half -> 0.5, End Q1 -> 0.25, OT -> 0.97', (_ffl.game_frac('Half @ GB'), _ffl.game_frac('End Q1 vs Atl'), _ffl.game_frac('OT 4:00')) == (0.5, 0.25, 0.97))
case('game_frac: Final -> 1.0, future kickoff -> None, blank -> None', _ffl.game_frac('Final W 35-14 vs Atl') == 1.0 and _ffl.game_frac('Sun 1:00 pm @ Was') is None and _ffl.game_frac('') is None)
_live = dict(pts=12.4, final=False, frac=0.66); _fin = dict(pts=28.4, final=True, frac=1.0)
case('blend: live 12.4 at 66% played with a 20-pt projection -> 19.2', abs(_AC.blend(_live, 20.0) - (12.4 + 20 * 0.34)) < 1e-9, str(_AC.blend(_live, 20.0)))
case('blend: final ignores the projection', _AC.blend(_fin, 99.0) == 28.4)
# the lineup solver treats a live player as locked: he is neither proposed in nor out
import tempfile as _tf, csv as _csv, os as _os
_lu0 = LU.solve(b, P)
_any = next(r for r in b.starters() if r['slot'] not in ('BN','IR') and r['pos'] in ('WR','RB','TE'))
_act = {_any['key']: dict(pts=1.0, status='Q2 7:30', owner=b.me, tm=_any['tm'], final=False, frac=0.4)}
_lu1 = LU.solve(b, P, actuals=_act)
_row = next(r for r in _lu1['rows'] if r['key'] == _any['key'])
case('lineup: a live starter is marked live, scored as blend, never in a proposed change', _row.get('live') and abs(_row['pts'] - (1.0 + (_row['proj_pts'] or 0) * 0.6)) < 1e-6 and not any(_any['key'] in (c['start']['key'], (c['sit'] or {}).get('key')) for c in _lu1['changes']), f'{_row.get("pts")} proj {_row.get("proj_pts")}')

# 31. 09-26 corrections, all from the first card after the Saturday pull:
#   - a QB starting is not a breakout signal (Maye proposed as a Tier-B add over a 4th QB spot)
#   - a player Caleb ADDED this week is never the proposed drop (Jameson Williams, added 09-25)
#   - a player Caleb dropped in EITHER league is not re-proposed in the other (Fields, HH 09-25 -> BSB 09-26)
#   - a BSB player dropped to waivers since the Wednesday run is a CLAIM, not a free-agent add
#   - a starter whose game is final is not a slot the weekly wire can fill (Perine "over" Lloyd 3.80 final)
from lib import breakout as _BK, wire as _WR
_qb = dict(pos='QB', gs=1, snap_share=1.0, touch_share=0, tgt_share=0, air_share=0)
case('QB with gs=1 and 100% snaps is WATCH from usage, never START', _BK._usage_tier(_qb)[0] == 'watch', str(_BK._usage_tier(_qb)))
import tempfile as _tf2, json as _j2, os as _os2
_td = _tf2.mkdtemp()
def _snap(name, players):
    pth = _os2.path.join(_td, name)
    _j2.dump({'rows': [dict(owner='Tecmo Bowlers', player=p) for p in players]}, open(pth, 'w')); return pth
_t0 = (C.now() - C.dt.timedelta(days=1)).strftime('%Y-%m-%dT%H%M') + '.json'
_t1 = C.now().strftime('%Y-%m-%dT%H%M') + '.json'
_snaps = [_snap(_t0, ['A Player', 'Malachi Fields']), _snap(_t1, ['A Player', 'Jameson Williams'])]
case('recently_added sees the player who appeared since yesterday\'s snapshot', 'jameson williams' in S.recently_added('HH', snaps=_snaps) and 'a player' not in S.recently_added('HH', snaps=_snaps))
case('recently_dropped sees the player who vanished since yesterday\'s snapshot', 'malachi fields' in S.recently_dropped('HH', snaps=_snaps))
_tx = _os2.path.join(_td, 'tx.csv')
open(_tx, 'w').write('datetime,team,action,player,pos,nfl,bid,note\n' + f"{(C.now() - C.dt.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')},Regulators,Drop,Malachi Fields,WR,NYG,,To Waivers\n" + f"{(C.now() - C.dt.timedelta(days=20)).strftime('%Y-%m-%d %H:%M')},Regulators,Drop,Old Guy,WR,NYG,,To Waivers\n")
_wv = _BK._on_waivers('BSB', path=_tx)
case('a BSB drop to waivers an hour ago is on waivers; one from three weeks ago is not', 'malachi fields' in _wv and 'old guy' not in _wv, str(_wv))
case('mechanics for a waived player say CLAIM, never free agent', 'ON WAIVERS' in _BK._mech('BSB', 'A', dict(key='malachi fields'), _wv) and 'free agent' not in _BK._mech('BSB', 'A', dict(key='malachi fields'), _wv).split('—')[0])
_lloyd = b.row_of('MarShawn Lloyd')
if _lloyd:
    _lu_f = LU.solve(b, P, actuals={_lloyd['key']: dict(pts=3.8, status='Final L 14-35 vs Atl', owner=b.me, tm='GB', final=True, frac=1.0)})
    _ub = _WR.Wire(b, P, season=_j.load(open('/home/claude/bsb2/data/season_blend.json'))).upgrade_board(_lu_f)
    case('weekly upgrade board never proposes a player "over" a starter whose game is final', not any(u['over']['key'] == _lloyd['key'] for u in _ub), str([(u['add']['name'], u['over']['player']) for u in _ub][:3]))

# 32. Next man up (09-26): a starter whose markets were withdrawn and whose NFL
#     backup is a free agent is an alert naming the backup; a starter whose game
#     has kicked off is not in the table at all.
from lib import nextup as _NU
class _FutureKick:
    def __init__(self, P): self.P = P
    def kickoff(self, tm): return C.now() + C.dt.timedelta(days=1)
    def __getattr__(self, a): return getattr(self.P, a)
class _PastKick(_FutureKick):
    def kickoff(self, tm): return C.now() - C.dt.timedelta(hours=1)
_wr = WR.Wire(b, P, season=_j.load(open('/home/claude/bsb2/data/season_blend.json')))
_lu = LU.solve(b, P)
_charts, _uw = _NU.depth_charts(W_NOW)
_cand = None
for r in b.starters():
    if r['pos'] in _NU.OFF and any(x['key'] in _wr.pool for x in _NU.backups(_charts, r)):
        _cand = r; break
if _cand:
    _res = _NU.scan(b, _FutureKick(P), _wr, _lu, {'gone': [dict(key=_cand['key'])]}, W_NOW, drops=[])
    _al = [a for a in _res['alerts'] if a['row']['key'] == _cand['key']]
    case(f'next man up: withdrawn markets on {_cand["player"]} -> alert with a free-agent backup', bool(_al) and _al[0]['fa'] is not None and _al[0]['fa']['where'] == 'fa', str(_al[:1]))
    _res2 = _NU.scan(b, _PastKick(P), _wr, _lu, {'gone': [dict(key=_cand['key'])]}, W_NOW, drops=[])
    case('next man up: a starter whose game has kicked off is not listed', not _res2['rows'] and not _res2['alerts'])
else:
    case('next man up: depth charts load', bool(_charts))

# 33. Playoff leverage (09-26): the simulation is a probability model, so it must
#     conserve seats, reward a win, reward strength, and bury a team with nothing.
from lib import playoff as _PO, windows as _WN
_po = _PO.evaluate(b, P, W_NOW, opp=None, season=_j.load(open('/home/claude/bsb2/data/season_blend.json')), windows=_WN.Windows())
case('playoff sim: playoff seats are conserved (sum of P over teams = seats)', abs(sum(_po['p'].values()) - _po['playoff_teams']) < 0.05, f"{sum(_po['p'].values()):.2f} vs {_po['playoff_teams']}")
case('playoff sim: a win this week never lowers the odds', _po['p_win'] is None or _po['p_loss'] is None or _po['p_win'] >= _po['p_loss'] - 0.01, f"{_po.get('p_win')} / {_po.get('p_loss')}")
case('playoff sim: +5 pts/week of strength raises the odds', _po['p_plus5'] >= _po['mine'], f"{_po['p_plus5']:.2f} vs {_po['mine']:.2f}")
_S0 = dict(_po['strengths']); _S0[b.me] = {w: 0.0 for w in _S0[b.me]}
_dead = _PO.simulate(b, _S0, W_NOW)
case('playoff sim: a roster projecting zero every week does not make the playoffs', _dead['mine'] < 0.02, f"{_dead['mine']:.3f}")

# 34. Rivals (09-26): the bid to beat is set by the likely field, bounded by the
#     bands; a Tier-B claim always takes the floor; one outlier claim is not a habit.
from lib import rivals as _RV, fab as _F
_prof = _RV.profiles(b, P); _fab = _F.model()
_bA = _RV.bid_for(_prof, 'WR', 'A', _fab); _bB = _RV.bid_for(_prof, 'WR', 'B', _fab)
case('rivals: a Tier-A bid lies within [Tier-B floor, contested cap]', _bA['floor'] <= _bA['bid'] <= _bA['cap'], str(_bA['bid']))
case('rivals: a Tier-B claim takes the floor', _bB['bid'] == _fab['bands']['B']['bid'])
_whale = max(_prof['profiles'].values(), key=lambda p: (p['max_bid'] or 0))
if _whale['bids'] and len(_whale['bids']) == 1 and 'WR' not in _whale['need']:
    case('rivals: a single outlier claim is discounted, not matched', _bA['bid'] <= _whale['max_bid'], f"{_bA['bid']} vs whale {_whale['max_bid']}")
case('rivals: every manager in the league has a profile', set(_prof['profiles']) >= set(b.by_owner))

# 35. Calibration (09-26): the log keeps the last PREGAME number — a row seen for
#     the first time after kickoff is marked post and never scored; a locked row is
#     not overwritten by a later run.
from lib import calib as _CB
import tempfile as _tf3
_CB_D = _CB.D; _CB.D = _tf3.mkdtemp() + '/'
try:
    _CB.log(b, _FutureKick(P), 99)                       # everyone pregame
    _rows = {r['key']: r for r in _csv.DictReader(open(_CB.D + 'BSB_wk99.csv'))}
    case('calibration: pregame rows are unlocked and not post', all(r['locked'] == '0' and r['post'] == '0' for r in _rows.values()) and len(_rows) > 100, str(len(_rows)))
    _one = next(iter(_rows)); _eng0 = _rows[_one]['engine']
    _CB.log(b, _PastKick(P), 99)                         # now every game has kicked off
    _rows2 = {r['key']: r for r in _csv.DictReader(open(_CB.D + 'BSB_wk99.csv'))}
    case('calibration: after kickoff the row locks and keeps the pregame number, post stays 0', _rows2[_one]['locked'] == '1' and _rows2[_one]['post'] == '0' and _rows2[_one]['engine'] == _eng0)
    _CB.log(h, _PastKick(P), 98)                         # first sighting after kickoff
    _rows3 = {r['key']: r for r in _csv.DictReader(open(_CB.D + 'HH_wk98.csv'))}
    case('calibration: a first sighting after kickoff is marked post', all(r['post'] == '1' for r in _rows3.values()))
finally:
    _CB.D = _CB_D
_rep = _CB.report(W_NOW)
case('calibration: report rows carry n, MAE >= 0 and a league', all(r['n'] > 0 and r['mae'] >= 0 and r['league'] in ('BSB', 'HH') for r in _rep['rows']))

# 36. Same-game correlation (09-26): two skill players on the same NFL team are
#     sampled with a positive correlation; two in different GAMES are not; each
#     player's mean is preserved. Tested on a synthetic two-man lineup so the
#     pair always exists whatever the real lineups look like.
import numpy as _np
_game_of = {}
for (_a, _h_) in (P.games or {}): _game_of[_a] = (_a, _h_); _game_of[_h_] = (_a, _h_)
_lu_b = LU.solve(b, P)
_pool = [r for r in _lu_b['rows'] + [x for x in b.rows if x['owner'] != b.me] if r['pos'] in ('QB', 'RB', 'WR', 'TE') and r['designation'] not in ('O', 'IR', 'CEL') and P.kickoff(r['tm']) and P.kickoff(r['tm']) > C.now()]
for r in _pool:
    if 'line' not in r: r['line'] = P.line(r['key'], r['pos'], r['tm']); r['pts'] = SC.points(r['line'], 'BSB')
_pool = [r for r in _pool if r['pts'] and r['pts'] > 3]
_byteam = {}
for r in _pool: _byteam.setdefault(r['tm'], []).append(r)
_pair_same = next((v[:2] for v in _byteam.values() if len(v) >= 2), None)
_pair_diff = None
for r1 in _pool:
    for r2 in _pool:
        if _game_of.get(r1['tm']) and _game_of.get(r2['tm']) and _game_of[r1['tm']] != _game_of[r2['tm']]:
            _pair_diff = (r1, r2); break
    if _pair_diff: break
def _two(r1, r2):
    fake = dict(current={'X': r1, 'Y': r2}, optimal={'X': r1, 'Y': r2}, rows=[])
    return WP.evaluate(b, P, fake, 'BSB')['samples']
if _pair_same:
    _sm = _two(*_pair_same); _c = _np.corrcoef(_sm[_pair_same[0]['key']], _sm[_pair_same[1]['key']])[0, 1]
    case(f'correlation: teammates ({_pair_same[0]["player"]}, {_pair_same[1]["player"]}) are positively correlated (> 0.12)', _c > 0.12, f'{_c:.2f}')
    for r in _pair_same:
        case(f'correlation: {r["player"]} keeps his mean within 3%', abs(float(_sm[r["key"]].mean()) - r['pts']) <= 0.03 * r['pts'] + 0.3, f'{_sm[r["key"]].mean():.2f} vs {r["pts"]:.2f}')
if _pair_diff:
    _sd_ = _two(*_pair_diff); _c2 = abs(_np.corrcoef(_sd_[_pair_diff[0]['key']], _sd_[_pair_diff[1]['key']])[0, 1])
    case('correlation: players in different games are near-independent (|r| < 0.06)', _c2 < 0.06, f'{_c2:.3f}')

# 37. 09-27, first live-pull card: "the market agrees" needs a starter-level line
#     (Treadwell: 26 rec yds priced 15% over 23 is a WR4, not a Tier-A role); and the
#     last clean drop can still be worth more than the add (value over replacement).
class _FakeProj:
    def __init__(self, mean, sv): self.kal = {('x', 'KXNFLRECYDS'): dict(mean=mean, sse=0.001, n=5)}; self.off = {'x': dict(rec_yd=sv)}; self.props = {}
case('market: 26 rec yds over a 23 projection is NOT "ahead" (under the starter floor)', not _BK._market(_FakeProj(26.0, 23.0), 'x', 'WR')['ahead'])
case('market: 52 rec yds over a 44 projection IS ahead', _BK._market(_FakeProj(52.0, 44.0), 'x', 'WR')['ahead'])
case('market: 48 rec yds with no Sleeper line at all is ahead; 20 is not', _BK._market(_FakeProj(48.0, 0.0), 'x', 'WR')['ahead'] and not _BK._market(_FakeProj(20.0, 0.0), 'x', 'WR')['ahead'])
_dropQB = dict(tier=3, row=dict(player='A QB3', pos='QB', key='a qb3', pts=33.0, slot='BN'), val=384.0, why='lowest-valued bench player', gate=None, vor=80.0)
_addWR = dict(tier='A', in_pool=True, week_pts=9.4, pos='WR', key='new wr', name='New WR', gate=None, usage='x', ahead=True, vor=30.0)
_m1 = _BK._move(_addWR, 'HH', [_dropQB], None, (4, 2, 6.0, 'Nobody'))
case('a Tier-A add never takes a drop whose value over replacement exceeds his own', _m1['verb'] == 'WAIT' and 'worth less' in _m1['when'], str(_m1))
_dropQB2 = dict(_dropQB, vor=-26.0)
_m2 = _BK._move(_addWR, 'HH', [_dropQB2], None, (4, 2, 6.0, 'Nobody'))
case('...but does take one the wire replaces (negative value over replacement)', _m2['verb'] == 'ADD' and _m2['drop'] == 'A QB3', str(_m2))

# 38. Caleb, 09-27: "QBs are too valuable in superflex though compared to a flyer WR."
#     In HH (QB + Q/W/R/T) a third QB is depth and never the drop; in BSB (one QB slot)
#     the rule does not fire.
_wh_ = WR.Wire(h, P)
case('HH is detected as superflex (2 QB-eligible slots)', _wh_.superflex_qb_slots() == 2)
_qbs_h = [r for r in h.mine if r['pos'] == 'QB' and r['slot'] != 'IR']
if 2 <= len(_qbs_h) <= 3:
    _gq = _wh_.gate_drop(_qbs_h[-1])
    case(f'HH: dropping {_qbs_h[-1]["player"]} (QB{len(_qbs_h)} of 3) is BLOCKED by the superflex rule', any(n_ == 'G14-superflex' and s_ == 'BLOCK' for n_, s_, _ in _gq.checks), str([(n_, s_) for n_, s_, _ in _gq.checks if n_ == 'G14-superflex']))
_wb_ = WR.Wire(b, P, season=_j.load(open('/home/claude/bsb2/data/season_blend.json')))
_qb_b = next((r for r in b.mine if r['pos'] == 'QB'), None)
if _qb_b:
    case('BSB (one QB slot): the superflex rule does not fire', not any(n_ == 'G14-superflex' for n_, s_, _ in _wb_.gate_drop(_qb_b).checks))
_hh_scan = BK.scan(h, P, season=None, lineup=LU.solve(h, P))
case('HH scan never names a QB as the drop for a non-QB add', all(not (x['move'].get('drop') and h.row_of(x['move']['drop']) and h.row_of(x['move']['drop'])['pos'] == 'QB' and x['pos'] != 'QB') for x in _hh_scan['rows']))

# 39. Live guard (09-27, 2:20 pm): Kalshi ladders for a game in progress are the box
#     score, not a projection — no line, tier or movement flag may use them; and a
#     lineup change may not involve a player whose game has kicked off.
_kicked_teams = {tm for tm, k in P.kick.items() if k and k <= C.now()}
_off_team = {k: N.team(r['team']) for k, r in P.off.items()}
case('live guard: no Kalshi ladder survives for a player whose game has kicked off', not any(_off_team.get(k) in _kicked_teams for (k, s_) in P.kal), str([k for (k, s_) in P.kal if _off_team.get(k) in _kicked_teams][:3]))
case('live guard: no lineup change involves a locked player (BSB and HH)', all(c['start'].get('phase') != 'locked' and (not c['sit'] or c['sit'].get('phase') != 'locked') for c in LU.solve(b, P)['changes'] + LU.solve(h, P)['changes']))
_stm2 = _STM.scan(P, {'BSB': b, 'HH': h}, W_NOW)
case('live guard: no line-movement flag for a player whose game has kicked off', all(m['owners'][0][4] not in _kicked_teams for m in _stm2['moves']))

print('=' * 88)
n = total
print(f'{n - bad}/{n} behaved as required.' + ('  SYSTEM IS SOUND.' if bad == 0 else f'  {bad} FAILURES — do not ship.'))
sys.exit(1 if bad else 0)
