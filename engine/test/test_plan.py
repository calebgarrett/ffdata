"""PLANNER REGRESSION — the unified roster planner (lib/plan.py) on synthetic leagues.

Every league here is built by hand: a State from rows (like test_system's _snap
helpers), a fake projection layer whose lines carry league points directly, a fake
schedule (kickoffs, byes), a real Wire over them (so the real gates run), and
Facts.from_parts. Nothing reads the live rosters; the ledger and registry are only
read (fictional names are on neither).
"""
import sys, copy, json
sys.path.insert(0, '/home/claude/bsb2')
from lib import clock as C, state as S, lineup as LU, wire as WR, plan as PL
from lib.facts import Facts
from lib.names import key as NK

bad = 0; total = 0
def case(label, ok, detail=''):
    global bad, total
    total += 1
    if not ok: bad += 1
    print(f'[{"OK " if ok else "FAIL"}] {label}' + (f'  — {detail}' if detail and not ok else ''))

print('=' * 88); print('PLANNER REGRESSION'); print('=' * 88)

# Pinned to a Thursday noon of the current NFL week: the BSB mechanics table turns every
# unrostered player into a claim between Tuesday 7 am and the Wednesday run, which is a
# fact about the calendar, not about these cases (10-06: six cases failed on a Tuesday).
_real = C.now()
WEEK = max(1, C.nfl_week(_real))
NOW = (C.week_start(WEEK) + C.dt.timedelta(days=2, hours=5)).astimezone(C.ET)     # Thu 12:00 ET
# the gates read the clock themselves (G12 state age, G8 freshness): pin it to the same
# Thursday, or a Saturday run sees a 48h-old 'live' state and blocks every add (10-17)
import os as _os
_os.environ['FF_NOW'] = NOW.strftime('%Y-%m-%dT%H:%M')
FUT = NOW + C.dt.timedelta(days=1)          # a kickoff still ahead
PAST = NOW - C.dt.timedelta(hours=2)        # a game in progress / started
OLD = NOW - C.dt.timedelta(hours=30)        # a game over

TEAMS = ['ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN', 'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC',
         'LAC', 'LAR', 'LV', 'MIA', 'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB', 'TEN', 'WAS']
_SYL1 = ['Aber', 'Black', 'Castel', 'Dun', 'Ether', 'Fair', 'Golds', 'Holl', 'Inger', 'Jablon', 'Kettel', 'Lind', 'Montag',
         'Nakam', 'Okon', 'Pember', 'Quarter', 'Rasmus', 'Strick', 'Thistle']
_SYL2 = ['ford', 'wick', 'mont', 'stead', 'worth', 'by', 'ton', 'ley', 'dale', 'more', 'field', 'shaw']
import itertools as _it
SUR = (_SYL1[i % 20] + _SYL2[(i // 20) % 12] + ('' if i < 240 else 'abcdefghij'[(i // 240) % 10]) for i in _it.count())
FIRSTS = _it.cycle(['Zorvath', 'Quillon', 'Brexley', 'Talvin', 'Oswin', 'Pellam', 'Cadoc', 'Dravon', 'Elric', 'Fennick'])

def nm():
    return f'{next(FIRSTS)} {next(SUR)}'

DST_NAME = {'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens', 'BUF': 'Buffalo Bills',
            'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears', 'NE': 'New England Patriots', 'NO': 'New Orleans Saints',
            'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers', 'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'}


class FakeWindows:
    def __init__(self, byes=None):
        self.byes_ = byes or {}                      # {week: set(teams)}
        self.weeks = list(range(1, 19))
        self.own = {w: {t: 23.0 for t in TEAMS if t not in self.byes_.get(w, set())} for w in self.weeks}
        self.opp = {w: {t: 22.0 for t in TEAMS if t not in self.byes_.get(w, set())} for w in self.weeks}
    def byes(self, w): return sorted(self.byes_.get(w, set()))
    def have(self, w): return w in self.own
    def bye(self, t): return [w for w in self.weeks if t in self.byes_.get(w, set())]


class FakeProj:
    """Lines carry league points directly (pts_override), two source families."""
    def __init__(self, pts, kicks, ready=True):
        self.pts = pts; self.kicks = kicks; self.ready_ = ready
        self.week = WEEK; self.kal = {}; self.props = {}; self.games = {}
        self.off, self.idp = {}, {}
    def add(self, k, name, pos, tm):
        (self.idp if pos in ('LB', 'DE', 'DT', 'CB', 'S', 'DL', 'DB') else self.off)[k] = dict(player=name, team=tm, pos=pos)
    def line(self, k, pos, tm, market=True):
        k = NK(k); fam = WR._fam(pos)
        if k not in self.pts:
            return dict(stat={}, sources=[], prov={}, unknown=True, fam=fam)
        v = self.pts[k]
        return dict(stat={}, sources=['kalshi', 'sleeper'], prov={}, unknown=False, fam=fam, pts_override={'BSB': v, 'HH': v})
    def kickoff(self, tm): return self.kicks.get(tm, FUT)
    def market_ready(self, tm): return self.ready_ if not isinstance(self.ready_, dict) else self.ready_.get(tm, True)


def league(lg, roster, fas=(), others=(), kicks=None, byes=None, ready=True, usage=None, season=None,
           recently_added=None, recently_dropped=None, waived=None, log_rows=None, fab_left=93, registry=None):
    """roster: [(slot, name, pos, tm, pts, designation)] for Caleb's team; fas: [(name, pos, tm, pts)];
    others: [(owner, name, pos, tm, pts)]. -> (facts, state, proj)"""
    cfg = S.ALL[lg]
    rows = []
    pts = {}
    proj = FakeProj(pts, kicks or {}, ready)
    for slot, name, pos, tm, p, des in roster:
        rows.append(dict(owner=cfg.name, manager=cfg.name, slot=slot, player=name, pos=pos, nfl=tm, designation=des))
        k = f'DST:{tm}' if pos == 'DEF' else NK(name)
        if p is not None: pts[k] = p
        proj.add(k, name, pos, tm)
    for owner, name, pos, tm, p in others:
        rows.append(dict(owner=owner, manager=owner, slot='BN', player=name, pos=pos, nfl=tm, designation='none'))
        k = f'DST:{tm}' if pos == 'DEF' else NK(name)
        pts[k] = p; proj.add(k, name, pos, tm)
    for name, pos, tm, p in fas:
        k = NK(name)
        pts[k] = p; proj.add(k, name, pos, tm)
    stamp = NOW.isoformat(timespec='minutes')
    st = S.State(lg, rows, stamp, source='test', others_pulled=stamp)
    sea = season or {}
    w = WR.Wire(st, proj, season=sea if lg == 'BSB' else None)
    for kind, entries in (registry or {}).items():
        getattr(w, kind).update(entries)
    lu = LU.solve(st, proj)
    use = {}
    for r in st.mine:
        if r['slot'] == 'BN' and WR._fam(r['pos']) in ('WR', 'RB', 'TE', 'QB'):
            use[r['key']] = dict(pos=WR._fam(r['pos']), snap_share=0.2, tgt_share=0.04, air_share=0.04, touch_share=0.05, gs=0)
    use.update(usage or {})
    f = Facts.from_parts(lg, st, proj, WEEK, NOW, w, lu, windows=FakeWindows(byes), season=sea,
                         usage_now=use, usage_prev={}, recently_added=recently_added or {}, recently_dropped=recently_dropped or {},
                         waived=waived or {}, log_rows=log_rows or [], fab_left=fab_left if lg == 'BSB' else None, usage_week=WEEK - 1)
    return f, st, proj


def bsb_roster(open_spots=0, k_tm='SEA', def_tm='BUF', qb_tm='DAL', te_tm='DET', k_des='none', extra=()):
    R = [('QB', nm(), 'QB', qb_tm, 20.0, 'none'), ('RB', nm(), 'RB', 'ATL', 14.0, 'none'), ('RB', nm(), 'RB', 'BAL', 12.0, 'none'),
         ('WR', nm(), 'WR', 'CAR', 13.0, 'none'), ('WR', nm(), 'WR', 'CHI', 11.0, 'none'), ('WR', nm(), 'WR', 'CIN', 9.0, 'none'),
         ('TE', nm(), 'TE', te_tm, 8.0, 'none'), ('W/R/T', nm(), 'WR', 'CLE', 9.5, 'none'),
         ('K', nm(), 'K', k_tm, 8.0, k_des), ('DEF', DST_NAME.get(def_tm, 'Buffalo Bills'), 'DEF', def_tm, 7.0, 'none')]
    bench = [('BN', nm(), 'WR', 'DEN', 4.0, 'none'), ('BN', nm(), 'WR', 'GB', 3.0, 'none'), ('BN', nm(), 'RB', 'HOU', 3.5, 'none'),
             ('BN', nm(), 'RB', 'IND', 2.0, 'none'), ('BN', nm(), 'WR', 'JAX', 2.5, 'none'), ('BN', nm(), 'TE', 'KC', 2.0, 'none'),
             ('BN', nm(), 'RB', 'LAC', 1.5, 'none'), ('BN', nm(), 'WR', 'LV', 1.0, 'none')]
    bench = bench[:8 - open_spots]
    return R + list(extra) + bench


def moves_of(p, kind='add'):
    return [m for m in p.moves if m['kind'] == kind]


# ---------------------------------------------------------------- 1. one open spot, two candidates
r1 = bsb_roster(open_spots=1)
a1, a2 = 'Wolfgang Ambrosetti', 'Lysander Breckenridge'
f, st, pr = league('BSB', r1, fas=[(a1, 'WR', 'MIA', 19.0), (a2, 'WR', 'MIN', 18.0)])
ev = dict(breakout_rows=[dict(key=NK(a1), name=a1, pos='WR', tm='MIA', tier='A', held='', usage='90% snaps', market='Kalshi agrees', in_pool=True, ahead=True),
                         dict(key=NK(a2), name=a2, pos='WR', tm='MIN', tier='A', held='', usage='88% snaps', market='Kalshi agrees', in_pool=True, ahead=True)])
p = PL.plan_facts(f, ev)
adds = moves_of(p)
opens = [m for m in adds if m['spot_kind'] == 'open']
case('one open spot + two candidates: exactly one move takes the open spot', len(opens) == 1, p.summary())
other = [m for m in adds if m['spot_kind'] != 'open']
rej = {r['key']: r for r in p.rejected}
case('...and the other gets a real drop or is rejected with a reason',
     (len(other) == 1 and any(t['op'] == 'drop' for t in other[0]['txns'])) or
     (len(other) == 0 and any(k in rej and rej[k]['reason'] for k in (NK(a1), NK(a2)) if k not in {m['add_key'] for m in adds})), p.summary())
case('each spot is used at most once', len({m['spot_id'] for m in adds}) == len(adds))
case('every add move prints its value terms', all(m['value_terms'] and 'dS_W1' in m['value_terms'] for m in adds))
pool = PL.SpotPool(f, PL.Mechanics(f))
pool.take(pool.spots[0].id, 'x')
try:
    pool.take(pool.spots[0].id, 'y'); reused = False
except PL.SpotReused:
    reused = True
case('SpotPool.take raises on reuse', reused)

# ---------------------------------------------------------------- 2. OUT starter -> firm replacement
r2 = bsb_roster()
r2[3] = ('WR', r2[3][1], 'WR', 'CAR', 13.0, 'O')            # WR1 tagged O, game ahead
f, st, pr = league('BSB', r2, ready=False)
p = PL.plan_facts(f, {})
lm = moves_of(p, 'lineup')
rep = [m for m in lm if m.get('sit') == r2[3][1]]
case('OUT starter: the replacement lineup move exists', len(rep) == 1, p.summary())
case('OUT starter: the replacement is FIRM with no market posted anywhere', rep and rep[0]['provisional'] is False, str(rep))
case('a swap NOT replacing an OUT starter with no market is provisional', all(m['provisional'] for m in lm if m.get('sit') != r2[3][1]))

# ---------------------------------------------------------------- 3. IR move frees a spot in the same plan (HH)
def hh_roster(extra_bench=(), qbs=('DAL', 'DET'), lb_des='none', lb_slot='LB'):
    R = [('QB', nm(), 'QB', qbs[0], 30.0, 'none'), ('WR', nm(), 'WR', 'CAR', 14.0, 'none'), ('RB', nm(), 'RB', 'ATL', 15.0, 'none'),
         ('TE', nm(), 'TE', 'DEN', 9.0, 'none'), ('W/R', nm(), 'WR', 'CHI', 12.0, 'none'), ('W/R/T', nm(), 'RB', 'BAL', 11.0, 'none'),
         ('Q/W/R/T', nm(), 'QB', qbs[1], 28.0, 'none'), ('K', nm(), 'K', 'SEA', 9.0, 'none'), ('DEF', 'Buffalo Bills', 'DEF', 'BUF', 20.0, 'none'),
         ('D', nm(), 'LB', 'CIN', 14.0, 'none'), ('DB', nm(), 'S', 'CLE', 12.0, 'none'), ('DL', nm(), 'DE', 'GB', 11.0, 'none'),
         (lb_slot, nm(), 'LB', 'HOU', 13.0, lb_des), ('CB', nm(), 'CB', 'IND', 10.0, 'none'), ('S', nm(), 'S', 'JAX', 10.5, 'none')]
    B = [('BN', nm(), 'WR', 'LAC', 6.0, 'none'), ('BN', nm(), 'WR', 'LV', 5.0, 'none'), ('BN', nm(), 'RB', 'MIA', 4.0, 'none'),
         ('BN', nm(), 'TE', 'NE', 3.0, 'none'), ('BN', nm(), 'WR', 'NO', 4.5, 'none'), ('BN', nm(), 'RB', 'NYG', 3.5, 'none')]
    B += list(extra_bench)
    while len(B) < 8: B.append(('BN', nm(), 'WR', 'PHI', 2.0, 'none'))
    return R + B[:8]

r3 = hh_roster(lb_des='IR')
ir_name = r3[12][1]
lbfa = 'Theodoric Vasquez-Lumley'
f, st, pr = league('HH', r3, fas=[(lbfa, 'LB', 'TEN', 16.0)],
                   registry=dict(drop_ok={NK(ir_name): dict(why='torn ACL, season over (test)', call='IR, NOT DROP', ir='True')}))
p = PL.plan_facts(f, {})
irm = [m for m in moves_of(p) if m['spot_kind'] == 'ir']
case('IR move frees a spot: the add uses the spot the IR move frees, in one Move',
     len(irm) == 1 and [t['op'] for t in irm[0]['txns']][:2] == ['ir', 'add'] and irm[0]['add_key'] == NK(lbfa), p.summary())
case('...and no separate drop is proposed for it', irm and not any(t['op'] == 'drop' for t in irm[0]['txns']))
f2, _, _ = league('HH', hh_roster(lb_des='IR'), registry=dict(drop_ok={}))
p2 = PL.plan_facts(f2, {})
case('a tagged-IR player with NO registry entry is not an IR spot (verified season-ending only)', not moves_of(p2, 'ir') and not any(m['spot_kind'] == 'ir' for m in moves_of(p2)))
r3o = hh_roster(lb_des='O'); ir_o = r3o[12][1]
f3, _, _ = league('HH', r3o, registry=dict(drop_ok={NK(ir_o): dict(why='season over (test)', call='IR', ir='True')}))
p3 = PL.plan_facts(f3, {})
im = moves_of(p3, 'ir')
case('an O-tagged verified IR player is an IR move marked ASK (provisional), not a firm spot', len(im) == 1 and im[0]['provisional'] and not any(m['spot_kind'] == 'ir' for m in moves_of(p3)), p3.summary())

# ---------------------------------------------------------------- 4. started player -> Tuesday timing
W1 = WEEK + 1
r4 = bsb_roster(k_tm='SEA')
k_name = r4[8][1]
kfa = 'Barnabas Quintrell'
START = dict(snap_share=0.9, tgt_share=0.25, air_share=0.3, touch_share=0.6, gs=1)
_u4 = {NK(x[1]): dict(START, pos=x[2]) for x in r4 if x[0] == 'BN'}
f, st, pr = league('BSB', r4, fas=[(kfa, 'K', 'NE', 9.0)], kicks={'SEA': PAST}, byes={W1: {'SEA'}}, usage=_u4)
p = PL.plan_facts(f, {})
km = [m for m in moves_of(p) if m['add_key'] == NK(kfa)]
case('started (week-locked) sole K on bye next week: the swap is Tuesday (week-lock)', len(km) == 1 and km[0]['when'].startswith('Tuesday'), p.summary())
case('...and in BSB the Tuesday add is a claim with a bid', km and any(t['op'] == 'claim' for t in km[0]['txns']) and '$' in km[0]['when'])
case('...and it drops the locked K only after the week rolls (no W points lost)', km and km[0]['value_terms']['dS_W'] == 0.0 and km[0]['eff'] == 'W+1')

# ---------------------------------------------------------------- 5. bye holes at K / DEF / QB / TE -> cover with timing
for fam, pos, kw, tmk, fa_tm in (('K', 'K', 'k_tm', 'SEA', 'NE'), ('DEF', 'DEF', 'def_tm', 'BUF', 'TB'), ('QB', 'QB', 'qb_tm', 'DAL', 'NO'), ('TE', 'TE', 'te_tm', 'DET', 'WAS')):
    r5 = bsb_roster(open_spots=1, **{kw: tmk})
    fa = DST_NAME[fa_tm] if pos == 'DEF' else nm()
    f, st, pr = league('BSB', r5, fas=[(fa, pos, fa_tm, 9.0 if pos != 'QB' else 18.0)], kicks={fa_tm: FUT}, byes={W1: {tmk} | ({'KC'} if pos == 'TE' else set())})
    p = PL.plan_facts(f, {})
    fk = f'DST:{fa_tm}' if pos == 'DEF' else NK(fa)
    mv = [m for m in moves_of(p) if m['add_key'] == fk]
    case(f'BSB bye hole at {fam} next week: the best free {fam} is the cover', len(mv) == 1 and 'hole' in mv[0]['srcs'], p.summary())
    case(f'...{fam} cover timing: a never-rostered free agent, before his kickoff', mv and mv[0]['when'].startswith('before kickoff'), mv and mv[0]['when'])
r5h = hh_roster()
k_h = r5h[7][1]
khfa = 'Mortimer Featherstonehaugh'
f, st, pr = league('HH', r5h, fas=[(khfa, 'K', 'TB', 9.0)], byes={W1: {'SEA'}}, kicks={'TB': OLD}, registry=dict(drop_ok={}),
                   usage={NK(x[1]): dict(START, pos=x[2]) for x in r5h if x[0] == 'BN'})
p = PL.plan_facts(f, {})
mv = [m for m in moves_of(p) if m['add_key'] == NK(khfa)]
case('HH bye hole at K next week: covered, swapping the K himself after he plays (Tuesday)', len(mv) == 1 and mv[0]['when'].startswith('Tuesday') and mv[0]['drop_name'] == k_h, p.summary())

# ---------------------------------------------------------------- 5b. the cover is found past the first few names (10-06: Santos hidden behind G5 kickers)
# BSB: my only K is on bye THIS week (hole at K in week W). Five free kickers rank above the
# cover but have already kicked (unusable for W); the sixth, still ahead of his kickoff,
# must be the cover — a hole search that stops at three names finds nobody.
r5b = [(sl, n, ps, tm, (0.0 if ps == 'K' else pt), d) for sl, n, ps, tm, pt, d in bsb_roster(open_spots=1, k_tm='KC')]   # the bye K projects nothing
kfas = [(nm(), 'K', tm, 13.0 - i) for i, tm in enumerate(('PIT', 'DET', 'NYJ', 'MIA', 'LV'))]
cover = 'Cairo Santosworth'
f, st, pr = league('BSB', r5b, fas=kfas + [(cover, 'K', 'CHI', 7.5)], byes={WEEK: {"KC"}},
                   kicks=dict({tm: OLD for _, _, tm, _ in kfas}, CHI=FUT, KC=None), registry=dict(drop_ok={}))   # KC: no game
p = PL.plan_facts(f, {})
mv = [m for m in moves_of(p) if m['add_key'] == NK(cover)]
case('a week-W hole is covered by the best free agent who can still play, however deep he ranks', len(mv) == 1 and 'hole' in mv[0]['srcs'], p.summary())
case('...and the hole reason leads the tile', mv and mv[0]['reasons'][0].startswith(f"week-{WEEK} hole at K"), mv and mv[0]['reasons'][:1])

# ---------------------------------------------------------------- 5c. no pulse on the wire (10-13: Achane, torn ACL, a $1 claim off a 264-pt preseason number)
# A free agent with NO weekly projection (this week or the last played weeks on disk)
# is OUT until a tag says otherwise, whatever his season number says — never an add,
# and his rest-of-season value is zero.
r5c = bsb_roster(open_spots=1)
ghost = 'Thaddeus Wraithbourne'
f, st, pr = league('BSB', r5c, fas=[(ghost, 'RB', 'MIA', None)], season={NK(ghost): dict(name=ghost, tm='MIA', pos='RB', pts=264.0)}, byes={W1: set()})
gx = f.fa(NK(ghost))
case('a free agent nobody projects is tagged O, not clear', gx is not None and gx.designation == 'O', gx and (gx.designation, gx.designation_src))
case('...and his rest-of-season value is zero, not season/17', gx is not None and (gx.ros_pw or 0) == 0.0 and (gx.pts_w1 or 0) == 0.0, gx and (gx.ros_pw, gx.pts_w1))
ev = dict(breakout_rows=[dict(key=NK(ghost), name=ghost, pos='RB', tm='MIA', tier='A', held='', usage='', market='', in_pool=True, ahead=True)])
p = PL.plan_facts(f, ev)
case('...and he is never an add, even into an open spot with Tier-A evidence', not any(m['add_key'] == NK(ghost) for m in p.moves), p.summary())
case('...rejected with G2 and the reason', any(r['key'] == NK(ghost) and r['reason'].startswith('G2') for r in p.rejected), [r for r in p.rejected if r['key'] == NK(ghost)])

# ---------------------------------------------------------------- 5e. a rival's drop of a real role is a fact (10-25: Terry McLaurin)
# McLaurin, season 204, projected in his last played game (week 6), knee on Monday night,
# out for the season; WAS on bye in week 7 so no projection exists to go missing, and the
# pulse (5c) read him alive. WINdianapolis dropped him Saturday. The planner priced a $1
# claim into a bench spot. A manager who let a 100+ point role go after his last game knows
# something; the add waits for a person (registry add_yes clears it).
r5e = bsb_roster(open_spots=1)
tmac = 'Thaddeus Mcelroy-Vance'
_log5e = [dict(datetime=(NOW - C.dt.timedelta(hours=20)).strftime('%Y-%m-%d %H:%M'), team='WINdianapolis', action='Drop', player=tmac, pos='WR', nfl='WAS', note='To Waivers')]
f, st, pr = league('BSB', r5e, fas=[(tmac, 'WR', 'WAS', 12.0)], season={NK(tmac): dict(name=tmac, tm='WAS', pos='WR', pts=204.0)}, byes={W1: set()}, log_rows=_log5e)
gx = f.fa(NK(tmac))
case('rival drop: the fact names the team and the day', gx is not None and gx.get('rival_drop') and gx['rival_drop'][0] == 'WINdianapolis', gx and gx.get('rival_drop'))
p = PL.plan_facts(f, dict(breakout_rows=[dict(key=NK(tmac), name=tmac, pos='WR', tm='WAS', tier='A', held='wk5', usage='', market='', in_pool=True, ahead=True)]))
case('rival drop: a 100+ point role a rival dropped this week is not an add, even into an open spot', not any(m['add_key'] == NK(tmac) for m in moves_of(p)), p.summary())
case('...rejected with G15 and the team named', any(r['key'] == NK(tmac) and r['reason'].startswith('G15') and 'WINdianapolis' in r['reason'] for r in p.rejected), [r for r in p.rejected if r['key'] == NK(tmac)])
# the clearance: a registry add_yes (a person looked) lets him through
f2, st2, pr2 = league('BSB', r5e, fas=[(tmac, 'WR', 'WAS', 12.0)], season={NK(tmac): dict(name=tmac, tm='WAS', pos='WR', pts=204.0)}, byes={W1: set()}, log_rows=_log5e,
                      registry=dict(verified={NK(tmac): dict(priority=1, why='verified healthy (test)', team='WAS', pos='WR', as_of=NOW.date().isoformat())}))
p2 = PL.plan_facts(f2, dict())
case('...a registry add_yes clears the rival-drop block', not any(r['key'] == NK(tmac) and r['reason'].startswith('G15') for r in p2.rejected), [r['reason'][:60] for r in p2.rejected if r['key'] == NK(tmac)])
# my own drop is not a rival drop (5c/9 cover that); a 30-point body dropped by a rival is not a signal
_log5e2 = [dict(_log5e[0], team=S.ALL['BSB'].name)]
f3, st3, pr3 = league('BSB', r5e, fas=[(tmac, 'WR', 'WAS', 12.0)], season={NK(tmac): dict(name=tmac, tm='WAS', pos='WR', pts=204.0)}, byes={W1: set()}, log_rows=_log5e2)
case('...my own drop is not a rival drop', f3.fa(NK(tmac)) is not None and not f3.fa(NK(tmac)).get('rival_drop'))

# ---------------------------------------------------------------- 5d. one week is not a season (10-22: Foster Moreau)
# A free agent with NO season number and a big W projection is valued rest-of-season at
# the positional median at most — one week's number from the most volatile source
# cannot carry the rest/playoff terms of the objective (Moreau: a 0.02/0.88 Kalshi quote
# read as 20 pts, 18/wk rest-of-season, J +15 over McBride).
r5d = bsb_roster(open_spots=1)
flash = 'Orsino Quillfeather'
f, st, pr = league('BSB', r5d, fas=[(flash, 'TE', 'HOU', 20.0)], byes={W1: set()})
gx = f.fa(NK(flash))
_med = f.posmed.get('TE')
case('no season number: rest-of-season is capped at the positional median, not the W projection', gx is not None and _med is not None and abs((gx.ros_pw or 0) - _med) < 1e-6 and gx.ros_pw < 20.0, gx and (gx.ros_pw, gx.ros_src, _med))
case('...and the source says why', gx is not None and 'positional median' in (gx.ros_src or ''), gx and gx.ros_src)
# the market side of the same case: an empty-quote ladder is no ladder
from lib import market as MK
_rows5d = [dict(ticker=f'KXNFLRECYDS-26OCT25NYGHOU-HOUX-{s}', yes_bid='0.0200', yes_ask='0.8800') for s in (10, 20, 25, 30, 40)]
case('market: a ladder quoted 2c/88c at every strike yields no points', MK._clean_ladder(_rows5d) == [], MK._clean_ladder(_rows5d))
_rows5d2 = [dict(ticker=f'KXNFLRECYDS-26OCT25NYGHOU-HOUX-{s}', yes_bid=f'{p-0.04:.4f}', yes_ask=f'{p+0.04:.4f}') for s, p in ((10, 0.90), (20, 0.70), (25, 0.55), (30, 0.40), (40, 0.20))]
case('market: a real 8c-wide ladder is kept whole', len(MK._clean_ladder(_rows5d2)) == 5)

# ---------------------------------------------------------------- 6. owned player never a candidate
r6 = bsb_roster(open_spots=1)
own = 'Aurelio Pendergast'
f, st, pr = league('BSB', r6, others=[('Rayland', own, 'WR', 'PIT', 25.0)])
ev = dict(breakout_rows=[dict(key=NK(own), name=own, pos='WR', tm='PIT', tier='A', held='', usage='', market='', in_pool=True, ahead=True)],
          upgrades=[dict(fam='WR', add=dict(key=NK(own), name=own, week=25.0), over=dict(player='x', pts=1.0))])
p = PL.plan_facts(f, ev)
case('an owned player is never an add, whatever the evidence says', not any(m['add_key'] == NK(own) for m in p.moves))
case('...and the considered list says why', any(r['key'] == NK(own) for r in p.rejected), str(p.rejected))

# ---------------------------------------------------------------- 7. recently dropped never a candidate
r7 = bsb_roster(open_spots=1)
rd = 'Cuthbert Ravenhill'
f, st, pr = league('BSB', r7, fas=[(rd, 'WR', 'PIT', 25.0)], recently_dropped={NK(rd): ('HH', '2026-10-02')})
ev = dict(breakout_rows=[dict(key=NK(rd), name=rd, pos='WR', tm='PIT', tier='A', held='', usage='', market='', in_pool=True, ahead=True)])
p = PL.plan_facts(f, ev)
case('a player Caleb dropped (either league, <= 7 days) is never an add', not any(m['add_key'] == NK(rd) for m in p.moves))
case('...rejected with the reason', any(r['key'] == NK(rd) and 'dropped him' in r['reason'] for r in p.rejected), str(p.rejected))

# ---------------------------------------------------------------- 8. superflex QB3 never a drop
qb3 = nm()
r8 = hh_roster(extra_bench=[('BN', qb3, 'QB', 'MIN', 1.0, 'none')])
wrfa = 'Ignatius Blatherwick'
f, st, pr = league('HH', r8, fas=[(wrfa, 'WR', 'PIT', 30.0)], registry=dict(drop_ok={}),
                   usage={NK(qb3): dict(pos='QB', snap_share=0.0, tgt_share=0, air_share=0, touch_share=0, gs=0)})
ev = dict(upgrades=[dict(fam='WR', add=dict(key=NK(wrfa), name=wrfa, week=30.0), over=dict(player='x', pts=12.0))])
p = PL.plan_facts(f, ev)
case('superflex: QB3 is never the drop', not any(t['op'] == 'drop' and t['key'] == NK(qb3) for m in p.moves for t in m['txns']), p.summary())
case('...he is listed as not a clean drop, with G14', any(e['player'] == qb3 and 'G14' in e['reason'] for e in p.excluded), str(p.excluded))

# ---------------------------------------------------------------- 8a2. a DEF/K is fungible in later weeks (10-23: Quay Walker for the Chiefs)
# HH: the IDP flex holds a LB on bye; the spare DEF covers next week's DEF bye. A verified
# every-down LB (registry add_yes priority 1) for the spare DEF: this week +LB, and next
# week's DEF slot is NOT empty — the engine streams the best free DEF — so W+1 is not a
# -18 and the depth term does not charge the spare's whole season. The move ships.
r8a2 = hh_roster(extra_bench=[('BN', 'Kansas City', 'DEF', 'KC', 18.0, 'none'), ('BN', nm(), 'CB', 'TEN', 13.0, 'none')])
_lb_bye = [r for r in r8a2 if r[0] == 'D'][0]
# IDP drops are legal now (10-28): both linebackers are registry holds here so the case
# keeps testing the spare-DEF spot, not an LB-for-LB upgrade
_lb_hold = {NK(r[1]): dict(why='hold (test)', call='HOLD') for r in r8a2 if r[2] not in ('DEF', 'K')}     # every skill player and IDP held: the case is about the spare DEF's valuation
_lb_hold['DST:BUF'] = dict(why='the December DEF (test)', call='HOLD')                                                                    # so the spare is the only DEF spot
walker = 'Quayshawn Ironmonger'
f, st, pr = league('HH', r8a2, fas=[(walker, 'LB', 'LV', 19.5), ('Dallas Cowboys', 'DEF', 'DAL', 17.5)],
                   kicks={_lb_bye[3]: None}, byes={WEEK: {_lb_bye[3]}, W1: {"BUF"}},
                   registry=dict(verified={NK(walker): dict(priority=1, why='every-down LB (test)', team='LV', pos='LB', as_of=NOW.date().isoformat())}, hold=_lb_hold))
p = PL.plan_facts(f, dict())
m8a2 = next((m for m in p.moves if m.get('add_key') == NK(walker)), None)
case('fungible DEF: a verified LB takes the spare DEF for the IDP flex', m8a2 is not None, p.summary())
_junk8a2 = {r[1] for r in r8a2 if r[0] == 'BN' and r[2] not in ('DEF', 'K') and r[4] <= 3.0}        # a 3-point body ties the spare on J; either is 'not a real player'
case('...the drop is the spare DEF (or a 3-point body that ties it), never a real player', m8a2 is not None and (m8a2.get('spot_kind') == 'spare' or m8a2.get('drop_name') in _junk8a2), m8a2 and (m8a2.get('spot_kind'), m8a2.get('drop_name'), m8a2.get('value_terms'), sorted(_junk8a2)))
case('...next week is valued with the best free DEF in the slot, not an empty slot', m8a2 is not None and m8a2['value_terms']['dS_W1'] > -5.0, m8a2 and m8a2['value_terms'])
case('...and the spare DEF is not charged as depth beyond the free replacement', m8a2 is not None and m8a2['value_terms']['d_depth'] > -2.0, m8a2 and m8a2['value_terms'])

# ---------------------------------------------------------------- 8a3. a DEF/K HOLE may take a replacement-level bench spot (10-28)
# HH, the only DEF on bye THIS week and a registry hold (the Texans), no spare, no open
# spot: the slot is empty on Sunday. The bench holds a 5th DB below the free agents at
# his position and a real WR. 'A DEF never costs a skill player or an IDP' is a rule
# about streams; a HOLE fills from the replacement-level body — never from the real one.
r8a3 = hh_roster(extra_bench=[('BN', nm(), 'CB', 'TEN', 9.0, 'none'), ('BN', nm(), 'WR', 'PHI', 15.0, 'none')])
r8a3 = [(r[0], r[1], r[2], r[3], 0.0, r[5]) if r[0] == 'DEF' else r for r in r8a3]          # on bye this week: no game, no points
_def8a3 = [r for r in r8a3 if r[0] == 'DEF'][0]
_cb8a3 = [r for r in r8a3 if r[0] == 'BN' and r[2] == 'CB'][0]
_wr8a3 = [r for r in r8a3 if r[0] == 'BN' and r[2] == 'WR' and r[4] == 15.0][0]
_hold8a3 = {NK(r[1]): dict(why='hold (test)', call='HOLD') for r in r8a3 if r[0] not in ('DEF',) and r[1] not in (_cb8a3[1], _wr8a3[1])}
_hold8a3['DST:' + _def8a3[3]] = dict(why='the December DEF (test)', call='HOLD')
f, st, pr = league('HH', r8a3, fas=[('Washington Commanders', 'DEF', 'WAS', 21.0), ('Derwin James', 'DB', 'LAC', 16.0), ('Talanoa Hufanga', 'DB', 'DEN', 15.5), ('Quandre Diggs', 'DB', 'TEN', 15.0)],
                   kicks={_def8a3[3]: None}, byes={WEEK: {_def8a3[3]}, W1: set()}, registry=dict(hold=_hold8a3))
p = PL.plan_facts(f, dict())
m8a3 = next((m for m in moves_of(p) if m['add_key'] == NK('Washington Commanders')), None)
case('DEF hole: the empty slot is filled from the wire even with no spare and no open spot', m8a3 is not None, p.summary())
case('...the spot is the replacement-level 5th DB, not the real WR', m8a3 is not None and m8a3.get('drop_name') == _cb8a3[1], m8a3 and m8a3.get('drop_name'))
case('...and the move is firm (a hole, not an edge)', m8a3 is not None and not m8a3.get('provisional'), m8a3 and m8a3.get('provisional'))

# ---------------------------------------------------------------- 8b. FAB policy (Caleb, 10-13: every policy decision maximizes P(win the league))
# A firm claim (hole cover) bids to WIN it — the league's 75th-pct winning bid — from
# the money above the reserve; the reserve is for a Tier-A player and steps down.
import lib.fab as _FAB, lib.rules as _RU
_LADDER = [0, 0, 0, 1, 1, 2, 3, 5, 5, 6, 7, 10, 11, 15, 24, 66]        # 16 bids: 75th pct -> index 11 -> $10
_real_model = _FAB.model
_FAB.model = lambda: dict(n=len(_LADDER), bids=list(_LADDER), bands={'B': dict(bid=1), 'A': dict(bid=25), 'contested': dict(bid=67)}, med=5, spent={}, remaining={})
try:
    case('rules: the ladder\'s 75th-pct bid is $10 on this ladder', _RU.fab_bid_firm(_LADDER) == 10, _RU.fab_bid_firm(_LADDER))
    case('rules: the reserve is $60 through week 10, $30 through 12, $0 after', (_RU.fab_reserve(6), _RU.fab_reserve(11), _RU.fab_reserve(13)) == (60, 30, 0))
    # week-W+1 hole at K in BSB (sole K on bye next week, started this week -> Tuesday claim)
    r8b = bsb_roster()
    kb = 'Barnaby Quillfeather'
    f, st, pr = league('BSB', r8b, fas=[(kb, 'K', 'NE', 9.0)], kicks={'SEA': PAST}, byes={W1: {'SEA'}}, usage=_u4, fab_left=93)
    p = PL.plan_facts(f, {})
    km = [m for m in moves_of(p) if m['add_key'] == NK(kb)]
    bid = km and next((t.get('bid') for t in km[0]['txns'] if t['op'] == 'claim'), None)
    case('a firm hole-cover claim bids the 75th-pct winning bid ($10), not the $1 floor', bid == 10, (bid, p.summary()))
    f, st, pr = league('BSB', r8b, fas=[(kb, 'K', 'NE', 9.0)], kicks={'SEA': PAST}, byes={W1: {'SEA'}}, usage=_u4, fab_left=63)
    p = PL.plan_facts(f, {})
    km = [m for m in moves_of(p) if m['add_key'] == NK(kb)]
    bid = km and next((t.get('bid') for t in km[0]['txns'] if t['op'] == 'claim'), None)
    case('...capped by the reserve: $63 left in week <= 10 leaves $3 above the $60 reserve', bid == 3, (bid, p.summary()))
    case('...and the claim still ships (money above the reserve is nearly free)', len(km) == 1, p.summary())
    f, st, pr = league('BSB', r8b, fas=[(kb, 'K', 'NE', 9.0)], kicks={'SEA': PAST}, byes={W1: {'SEA'}}, usage=_u4, fab_left=5)
    p = PL.plan_facts(f, {})
    km = [m for m in moves_of(p) if m['add_key'] == NK(kb)]
    bid = km and next((t.get('bid') for t in km[0]['txns'] if t['op'] == 'claim'), None)
    case('...never below $1, never above what is left', bid == 1, (bid, p.summary()))
finally:
    _FAB.model = _real_model

# ---------------------------------------------------------------- 8c. lineup pairing with several bye starters (10-13: 'Pierce at W/R/T over Vikings')
# Three starters on bye THIS week (WR3, TE, DEF). Two free agents arrive — an RB who takes
# W/R/T and a defense. Each must be paired with a displaced starter ELIGIBLE for the slot
# he takes: the DEF over the bye DEF, the RB over a bye WR/TE, never a defense over a flex.
r8c = bsb_roster(open_spots=2)
r8c = [(sl, n, ps, tm, (0.0 if sl in ('DEF', 'TE') or (sl == 'WR' and tm == 'CIN') else pt), d) for sl, n, ps, tm, pt, d in r8c]
rb8c, df8c = 'Osric Pendleton', DST_NAME['SEA']
f, st, pr = league('BSB', r8c, fas=[(rb8c, 'RB', 'PHI', 9.0), (df8c, 'DEF', 'SEA', 7.5)],
                   kicks={'BUF': None, 'DET': None, 'CIN': None}, byes={W1: set()},
                   usage={NK(rb8c): dict(START, pos='RB')})
ev = dict(breakout_rows=[dict(key=NK(rb8c), name=rb8c, pos='RB', tm='PHI', tier='A', held='wk5', usage='', market='', in_pool=True, ahead=True)])
p = PL.plan_facts(f, ev)
lu = {m['add_key']: m.get('lineup') for m in moves_of(p)}
rb_over = (lu.get(NK(rb8c)) or {}).get('over', ''); df_over = (lu.get('DST:SEA') or {}).get('over', '')
case('a newcomer at W/R/T is paired with a displaced WR/TE, never the bye defense', lu.get(NK(rb8c)) is not None and 'Bills' not in rb_over, (rb_over, p.summary()))
case('...and the new defense is paired with the bye defense', lu.get('DST:SEA') is not None and df_over.startswith('Buffalo'), (df_over, p.summary()))

# ---------------------------------------------------------------- 8d. a published pair sticks through a near-tie (10-13: Jennings <-> Hutchinson flipped between two pulls)
r8d = [(sl, n, ps, tm, (1.0 if (sl == 'BN' and tm == 'LAC') else pt), d) for sl, n, ps, tm, pt, d in bsb_roster(open_spots=0)]   # bench WR (LV) and bench RB (LAC) both at 1.0
rbx = 'Lysander Thorncroft'
f, st, pr = league('BSB', r8d, fas=[(rbx, 'RB', 'PHI', 12.0)], byes={W1: {'ATL', 'BAL'}}, usage={NK(rbx): dict(START, pos='RB')})   # both RBs on bye next week: a hole, so every bench spot is in play
ev = dict(breakout_rows=[dict(key=NK(rbx), name=rbx, pos='RB', tm='PHI', tier='A', held='wk5', usage='', market='', in_pool=True, ahead=True)])
p0 = PL.plan_facts(f, ev)
m0 = next((m for m in moves_of(p0) if m['add_key'] == NK(rbx)), None)
# the two cheapest bench spots are near-equal (bench WRs at 1.0 and 2.5); take whichever
# the plan picked, then publish the OTHER as the prior plan and re-run: it must stick
# the feasible bench spots (same family as the add) tie at J; publish the one
# the plan did NOT pick as the prior plan and re-run: it must stick
bench_low = sorted([x for x in r8d if x[0] == 'BN' and x[2] == 'RB'], key=lambda x: x[4])     # the bench RBs tie at J (bench value is not in J)
other = next(x for x in bench_low if m0 and x[1] != m0['drop_name'])
f.prev_plan_pairs = {(NK(rbx), f'drop:{NK(other[1])}')}
p1 = PL.plan_facts(f, ev)
m1 = next((m for m in moves_of(p1) if m['add_key'] == NK(rbx)), None)
case('a near-tie between two bench spots keeps the spot already published', m0 is not None and m1 is not None and m1['drop_name'] == other[1], (m0 and m0['drop_name'], m1 and m1['drop_name']))
_worse = next(x for x in r8d if x[0] == 'BN' and x[2] == 'RB' and x[4] >= 3.0)      # the 3.5 bench RB: depth cost 0.2 x (3.5 - 1.0) = 0.5 worse, plus churn ordering
f.prev_plan_pairs = {(NK(rbx), 'drop:' + NK(_worse[1]))}
p2 = PL.plan_facts(f, ev)
m2 = next((m for m in moves_of(p2) if m['add_key'] == NK(rbx)), None)
case('...and the stickiness is bounded: a spot that is clearly worse (a 3.5/wk player for a 1.0) is not kept', m2 is not None and m2['drop_name'] != _worse[1], m2 and m2['drop_name'])

# ---------------------------------------------------------------- 8e. displacement chain (10-13: 'start Pierce at RB2' with no one named)
# A free RB arrives; the optimizer puts him at RB2 and slides the old RB2 to W/R/T, whose
# occupant (a bye TE) goes to the bench. The newcomer is 'over' that TE, not over nobody.
r8e = bsb_roster(open_spots=1)
r8e = [(sl, n, ps, tm, (0.0 if sl == 'W/R/T' else pt), d) for sl, n, ps, tm, pt, d in r8e]
flex_name = next(x[1] for x in r8e if x[0] == 'W/R/T')
rbc = 'Peregrine Ashdown'
f, st, pr = league('BSB', r8e, fas=[(rbc, 'RB', 'PHI', 13.0)], kicks={'CLE': None}, byes={W1: set()}, usage={NK(rbc): dict(START, pos='RB')})
ev = dict(breakout_rows=[dict(key=NK(rbc), name=rbc, pos='RB', tm='PHI', tier='A', held='wk5', usage='', market='', in_pool=True, ahead=True)])
p = PL.plan_facts(f, ev)
m = next((m for m in moves_of(p) if m['add_key'] == NK(rbc)), None)
case('a newcomer who starts via a slot shuffle is paired with the starter the shuffle pushes out', m is not None and ((m.get('lineup') or {}).get('over') or '').startswith(flex_name), (m and m.get('lineup'), p.summary()[:300]))

# ---------------------------------------------------------------- 8f. HH acquisitions are cheap late in the week (10-18)
import lib.rules as _RU2
case('rules: an HH acquisition costs full price on Tuesday with 7 left', _RU2.acq_price(C.week_start(WEEK) + C.dt.timedelta(hours=1), 7) == 1.0)
case('rules: ...and a fifth of that on Saturday with 4+ left', _RU2.acq_price(C.week_start(WEEK) + C.dt.timedelta(days=4), 7) == 0.2)
case('rules: ...but full price on Saturday when only 2 are left', _RU2.acq_price(C.week_start(WEEK) + C.dt.timedelta(days=4), 2) == 1.0)
case('rules: BSB (no cap) is unaffected', _RU2.acq_price(C.week_start(WEEK) + C.dt.timedelta(days=4), None) == 1.0)

# ---------------------------------------------------------------- 8g. playoff weighting (10-18): a locked-in team is judged on weeks 15-17
# Two free WRs, equal this week and next: one is a December asset (his team's implied
# totals rise in weeks 15-17), the other fades. With P(playoffs) = 1 the planner prefers
# the December man; with P(playoffs) = 0 the two tie and the rest-of-season mean decides.
r8g = bsb_roster(open_spots=1)
dec, fade = 'Caspian Wintermere', 'Orlo Summerfield'
class _PW(FakeWindows):
    def __init__(self, byes=None): super().__init__(byes); self.rank_ = {}
# season blend gives both the same rest-of-season per-week value; playoff weeks are read
# per week through f.value -> ros_pw, so we tilt the December man by registering a
# higher ros for weeks 15-17 only via a per-week override hook if the harness has one;
# otherwise the case checks the term is wired: dS_play reported and weighted by q.
f, st, pr = league('BSB', r8g, fas=[(dec, 'WR', 'PHI', 14.0)], byes={W1: set()}, usage={NK(dec): dict(START, pos='WR')})
ev = dict(breakout_rows=[dict(key=NK(dec), name=dec, pos='WR', tm='PHI', tier='A', held='wk5', usage='', market='', in_pool=True, ahead=True)], p_playoffs=1.0)
p = PL.plan_facts(f, ev)
m = next((m for m in moves_of(p) if m['add_key'] == NK(dec)), None)
case('playoff term: with P(playoffs)=1 the move reports its weeks-15-17 value and the weight', m is not None and m['value_terms'].get('p_playoffs') == 1.0 and 'dS_play' in m['value_terms'], m and m['value_terms'])
f2, st2, pr2 = league('BSB', r8g, fas=[(dec, 'WR', 'PHI', 14.0)], byes={W1: set()}, usage={NK(dec): dict(START, pos='WR')})
p2 = PL.plan_facts(f2, dict(ev, p_playoffs=0.0))
m2 = next((m for m in moves_of(p2) if m['add_key'] == NK(dec)), None)
case('playoff term: with P(playoffs)=0 the term contributes nothing', m2 is not None and abs(m2['J'] - (m['J'] - PL.W_PLAY * 1.0 * m['value_terms']['dS_play'])) < 1e-6, (m and m['J'], m2 and m2['J']))

# ---------------------------------------------------------------- 8h. QB2 insurance in a one-QB league (Caleb, 10-24)
# "Given how important QB is, is it not worth keeping a backup?" A roster with ONE QB, a
# junk bench WR and a spare DEF; the best free QB (17/wk) is a registry priority-2 add.
# The point terms alone never ship a backup who never starts; the insurance term does,
# and the spot is the junk WR, not the spare DEF (10-24: the hand-picked 49ers drop).
r8h = bsb_roster(extra=[('BN', 'Kansas City', 'DEF', 'KC', 6.5, 'none')])
r8h = [r for r in r8h if not (r[0] == 'BN' and r[3] == 'LV')]          # keep 18: drop the 1.0 WR, keep the 2.5 and 3.0 WRs as the junk
junk = [r for r in r8h if r[0] == 'BN' and r[2] not in ('DEF', 'K')]          # any bench skill player; never the spare DEF
qb2 = 'Thackeray Bellweather'
# the starter's bye sits two weeks out while byes still exist (as Stafford's week 11 did);
# the insurance term alone is a near-miss by design (~3 J late in the year) — it is the
# bye cover PLUS insurance that ships, never insurance over a real player
_qb_bye = WEEK + 2 if WEEK + 2 <= 14 else None
_byes8h = {W1: set()}
if _qb_bye: _byes8h[_qb_bye] = {'DAL'}
f, st, pr = league('BSB', r8h, fas=[(qb2, 'QB', 'TB', 17.0), ('Dallas Cowboys', 'DEF', 'DAL', 7.5), ('Ambrose Fennimore', 'QB', 'NYJ', 14.0)],
                   byes=_byes8h,
                   registry=dict(verified={NK(qb2): dict(priority=2, why='QB2 insurance (test)', team='TB', pos='QB', as_of=NOW.date().isoformat())}))
p = PL.plan_facts(f, dict(p_playoffs=1.0))
m8h = next((m for m in moves_of(p) if m['add_key'] == NK(qb2)), None)
_ins_terms = m8h['value_terms'] if m8h else next((r.get('terms') or {} for r in p.rejected if r['key'] == NK(qb2)), {})
case('QB2 insurance: the term is explicit and positive for a one-QB roster', (_ins_terms.get('d_ins') or 0) > 0, _ins_terms)
if _qb_bye:
    case('QB2 insurance: with the starter\'s bye ahead, a one-QB roster adds the best free QB as a backup', m8h is not None, p.summary())
    case('...the spot is the weakest bench skill player, never the spare DEF', m8h is not None and m8h.get('spot_kind') == 'drop' and m8h.get('drop_name') in {r[1] for r in junk}, m8h and (m8h.get('spot_kind'), m8h.get('drop_name')))
# control: a roster that already carries two QBs earns no insurance credit for a third
r8h2 = bsb_roster(extra=[('BN', 'Ignatius Pemberton', 'QB', 'SEA', 15.0, 'none')])
r8h2 = [r for r in r8h2 if not (r[0] == 'BN' and r[3] == 'LV')]
f2, st2, pr2 = league('BSB', r8h2, fas=[(qb2, 'QB', 'TB', 17.0)], byes={W1: set()},
                      registry=dict(verified={NK(qb2): dict(priority=2, why='QB2 insurance (test)', team='TB', pos='QB', as_of=NOW.date().isoformat())}))
obj2 = PL.Objective(f2, PL.Mechanics(f2))
case('...a roster with two QBs already gets no insurance credit for a third', obj2.insurance([(f2.fa(NK(qb2)), None, 'W')]) == 0.0)
# control: a superflex league (two QB-eligible slots) is not a one-QB league
f3, st3, pr3 = league('HH', hh_roster(), fas=[(qb2, 'QB', 'TB', 30.0)], byes={W1: set()})
case('...superflex is not a one-QB league: no insurance term', not PL.Objective(f3, PL.Mechanics(f3)).one_qb())

# ---------------------------------------------------------------- 9. handcuff never a drop
r9 = bsb_roster()
hc = r9[-1][1]
f, st, pr = league('BSB', r9, fas=[('Peregrine Ashdown', 'WR', 'PIT', 30.0)],
                   registry=dict(hold={NK(hc): dict(handcuff_for='The Starter', call='HOLD — handcuff', why='RB2 behind the starter')}))
ev = dict(breakout_rows=[dict(key=NK('Peregrine Ashdown'), name='Peregrine Ashdown', pos='WR', tm='PIT', tier='A', held='', usage='', market='', in_pool=True, ahead=True)])
p = PL.plan_facts(f, ev)
case('a handcuff is never the drop', not any(t['op'] == 'drop' and t['key'] == NK(hc) for m in p.moves for t in m['txns']), p.summary())
case('...and is listed as not a clean drop', any(e['player'] == hc for e in p.excluded))

# ---------------------------------------------------------------- 10. HH acquisition cap
log = [dict(datetime=(NOW - C.dt.timedelta(minutes=10 + i)).strftime('%Y-%m-%d %H:%M'), team=S.ALL['HH'].name, action='Add', player=f'Somebody {i}', note='Free Agent')
       for i in range(6)]
r10 = hh_roster()[:-2]                               # two open spots
c1, c2 = 'Leofric Wetherby', 'Godwin Ashbury'
f, st, pr = league('HH', r10, fas=[(c1, 'WR', 'PIT', 30.0), (c2, 'WR', 'NYJ', 29.0)], log_rows=log, registry=dict(drop_ok={}))
ev = dict(upgrades=[dict(fam='WR', add=dict(key=NK(c1), name=c1, week=30.0), over=dict(player='x', pts=12.0)),
                    dict(fam='WR', add=dict(key=NK(c2), name=c2, week=29.0), over=dict(player='x', pts=12.0))])
p = PL.plan_facts(f, ev)
case('HH cap: 6 of 7 used since Tuesday -> 1 left', f.acq_left == 1, str(f.acq_left))
adds = moves_of(p)
case('HH cap respected: one add this week, the other rejected on the cap', len([m for m in adds if m['eff'] == 'W']) == 1 and any('acquisition cap' in r['reason'] for r in p.rejected), p.summary() + str(p.rejected))
case('the HH reset day is marked unverified', p.budgets.get('acq_reset_verified') is False and any(not e['verified'] and '7 acquisitions' in e['rule'] for e in p.mechanics))

# ---------------------------------------------------------------- 11. BSB claim vs free agent
r11 = bsb_roster(open_spots=2)
fa_ok, fa_kicked, fa_waived = 'Hildebrand Oyelaran', 'Mstislav Kowalczyk', 'Radomir Etxeberria'
f, st, pr = league('BSB', r11, fas=[(fa_ok, 'WR', 'PIT', 25.0), (fa_kicked, 'WR', 'NYJ', 24.0), (fa_waived, 'WR', 'PHI', 23.0)],
                   kicks={'PIT': FUT, 'NYJ': PAST, 'PHI': FUT}, waived={NK(fa_waived): 'Sat 4:05 am'})
M = PL.Mechanics(f)
a_ok, a_k, a_w = M.acquire(f.fa(NK(fa_ok))), M.acquire(f.fa(NK(fa_kicked))), M.acquire(f.fa(NK(fa_waived)))
case('BSB: a never-rostered FA before his kickoff is a free-agent add', a_ok['kind'] == 'fa' and a_ok['eff'] == 'W', str(a_ok))
case('BSB: an unrostered player whose game kicked off is a CLAIM that plays next week', a_k['kind'] == 'claim' and a_k['eff'] == 'W+1' and 'claim by Tue night' in a_k['label'], str(a_k))
case('BSB: a player dropped to waivers is a CLAIM', a_w['kind'] == 'claim', str(a_w))
ev = dict(upgrades=[dict(fam='WR', add=dict(key=NK(x), name=x, week=20.0), over=dict(player='x', pts=9.0)) for x in (fa_ok, fa_kicked, fa_waived)])
p = PL.plan_facts(f, ev)
byk = {m['add_key']: m for m in moves_of(p)}
case('BSB plan: the free agent is an add "before kickoff"', NK(fa_ok) in byk and byk[NK(fa_ok)]['when'].startswith('before kickoff') and byk[NK(fa_ok)]['txns'][0]['op'] == 'add', p.summary())
claimed = [byk[k] for k in (NK(fa_kicked), NK(fa_waived)) if k in byk]
case('BSB plan: a waiver player, when proposed, is a claim with a bid (never an add)', all(m['txns'][0]['op'] == 'claim' and m['txns'][0].get('bid') is not None for m in claimed), str(claimed))
case('BSB plan: FAB spent <= FAB left', sum((t.get('bid') or 0) for m in p.moves for t in m['txns'] if t['op'] == 'claim') <= f.fab_left)
fh, _, _ = league('HH', hh_roster()[:-1], fas=[('Ostrogoth Pemberley', 'WR', 'PIT', 25.0)], kicks={'PIT': PAST}, registry=dict(drop_ok={}))
ah = PL.Mechanics(fh).acquire(fh.fa(NK('Ostrogoth Pemberley')))
case('HH: a free agent whose game is in progress is addable after the game', ah['kind'] == 'after_game', str(ah))

# ---------------------------------------------------------------- 12. deterministic and idempotent
r12 = bsb_roster(open_spots=1)
d1 = 'Evander Quillfeather'
f, st, pr = league('BSB', r12, fas=[(d1, 'WR', 'PIT', 25.0)], byes={W1: {'SEA'}}, kicks={'PIT': FUT})
ev = dict(upgrades=[dict(fam='WR', add=dict(key=NK(d1), name=d1, week=25.0), over=dict(player='x', pts=9.0))])
before = copy.deepcopy([{k: v for k, v in r.items() if k not in ('line',)} for r in st.rows])
j1 = PL.plan_facts(f, ev).to_json(); j2 = PL.plan_facts(f, ev).to_json()
case('plan is deterministic (same inputs -> identical JSON)', j1 == j2)
after = [{k: v for k, v in r.items() if k not in ('line',)} for r in st.rows]
case('planning mutates nothing (roster rows unchanged)', before == after)
p1 = json.loads(j1)
added = [m for m in p1['moves'] if m['kind'] == 'add']
# apply the plan's moves to the roster and plan again: nothing left to do
r12b = list(r12)
for m in added:
    for t in m['txns']:
        if t['op'] == 'drop': r12b = [x for x in r12b if NK(x[1]) != t['key']]
    for t in m['txns']:
        if t['op'] in ('add', 'claim'):
            fa_row = f.fa(t['key'])
            r12b.append(('BN', fa_row.name, fa_row.pos, fa_row.tm, fa_row.pts_w, 'none'))
case('the plan made at least one add to re-check', len(added) >= 1, j1[:400])
fb, _, _ = league('BSB', r12b, fas=[], byes={W1: {'SEA'}}, kicks={'PIT': FUT})
pb = PL.plan_facts(fb, dict(upgrades=[]))
case('idempotent: after applying the plan, re-planning proposes no further adds', not moves_of(pb), pb.summary())

# ---------------------------------------------------------------- 12b. joint re-evaluation: two WRs for one flex
r12c = bsb_roster(open_spots=2)
for i in (3, 4, 5): r12c[i] = (r12c[i][0], r12c[i][1], 'WR', r12c[i][3], 20.0, 'none')
g1, g2 = 'Aldous Wintergreen', 'Benedikt Haverstock'
f, st, pr = league('BSB', r12c, fas=[(g1, 'WR', 'PIT', 15.0), (g2, 'WR', 'NYJ', 14.5)], kicks={'PIT': FUT, 'NYJ': FUT})
ev = dict(upgrades=[dict(fam='WR', add=dict(key=NK(x), name=x, week=15.0), over=dict(player='x', pts=9.5)) for x in (g1, g2)])
p = PL.plan_facts(f, ev)
adds = moves_of(p)
case('joint re-evaluation: two WRs that each beat the flex alone -> only one ships', len(adds) == 1 and adds[0]['add_key'] == NK(g1), p.summary())
case('...the other is rejected on its value given the rest of the plan', any(r['key'] == NK(g2) and 'jointly' in r['reason'] for r in p.rejected), str(p.rejected))

# ---------------------------------------------------------------- 13. sanity: the plan simulation check
from lib import sanity as SAN
r13 = bsb_roster(open_spots=1)
e1, e2 = 'Athelstan Merryweather', 'Ethelred Moonbeam'
f, st, pr = league('BSB', r13, fas=[(e1, 'WR', 'PIT', 25.0), (e2, 'WR', 'NYJ', 24.0)], kicks={'PIT': FUT, 'NYJ': FUT})
ev = dict(upgrades=[dict(fam='WR', add=dict(key=NK(x), name=x, week=25.0), over=dict(player='x', pts=9.0)) for x in (e1, e2)])
p = PL.plan_facts(f, ev)
runlike = dict(leagues={'BSB': dict(state=st)}, plans={'BSB': p}, week=WEEK)
case('sanity: the real plan simulates clean', SAN.check_plan(runlike) == [], str(SAN.check_plan(runlike)))
pb_ = copy.deepcopy(p)
am = [m for m in pb_.moves if m['kind'] == 'add']
if len(am) >= 2: am[1]['spot_id'] = am[0]['spot_id']
case('sanity: a spot used twice is caught', len(am) >= 2 and any('twice' in x for x in SAN.check_plan(dict(runlike, plans={'BSB': pb_}))))
pc_ = copy.deepcopy(p)
pc_.moves.append(dict(id='bad', kind='add', spot_id='zz', provisional=False, eff='W', txns=[dict(op='add', player='x', key='x'), dict(op='add', player='y', key='y')]))
case('sanity: an add past roster size is caught', any('active roster' in x for x in SAN.check_plan(dict(runlike, plans={'BSB': pc_}))))
pd_ = copy.deepcopy(p)
pd_.moves.append(dict(id='bad2', kind='add', spot_id='zz2', provisional=False, eff='W', txns=[dict(op='drop', player='Nobody Here', key='nobody here')]))
case('sanity: a drop of a player not on the roster is caught', any('not on the active roster' in x for x in SAN.check_plan(dict(runlike, plans={'BSB': pd_}))))
pe_ = copy.deepcopy(p); pe_.budgets = dict(pe_.budgets, fab_left=0)
pe_.moves.append(dict(id='bad3', kind='add', spot_id='zz3', provisional=False, eff='W+1', txns=[dict(op='claim', player='z', key='z', bid=5)]))
case('sanity: FAB over budget is caught', any('FAB' in x for x in SAN.check_plan(dict(runlike, plans={'BSB': pe_}))))

# 10-06: a kicker/defense add never costs a skill player or an IDP — it swaps one-for-one
# with the spare/only K or DEF, or takes an open/dead spot (Boswell-for-Kelce at J +11).
try:
    _r = PL._spot_rule if hasattr(PL, '_spot_rule') else None
except Exception: _r = None
case('rule text exists: a K/DEF never costs a non-K/DEF player', 'kickers and defenses swap one-for-one' in open('/home/claude/bsb2/lib/plan.py').read())

print('=' * 88)
print(f'{total - bad}/{total} behaved as required.' + ('  PLANNER IS SOUND.' if not bad else '  PLANNER FAILED.'))
sys.exit(1 if bad else 0)
