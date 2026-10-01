"""ONE LINEUP SOLVER, both leagues. Returns a DIFF against live slots.

Exact max-weight assignment (Hungarian) over every slot the league has, with
Yahoo's own eligibility. Then three things the old per-league scripts got wrong:

  1. Compared against what is ACTUALLY STARTING, so a change is only a change if
     the set of starters changes. "Swap in the 49ers" (09-16) cannot happen.
  2. A pure permutation of the same players across interchangeable slots
     (Oluokun <-> Schwesinger between D and LB, 09-16) is net zero and is not
     reported as two moves.
  3. Every change carries the game's lineup phase from the clock, so a Sunday
     call on a Tuesday is labelled 'early' and PROVISIONAL rather than shouted.
     Caleb: "Don't worry about lineup changes unless it's at least 1 day before
     the game."
"""
import numpy as np
from scipy.optimize import linear_sum_assignment
from . import clock as C, score as SC
from .state import UNUSABLE

NOISE = 1.5    # inside this many points, two players are the same player

def solve(state, proj, actuals=None):
    """-> dict(optimal={slot:row}, current={slot:row}, changes=[...], total_cur, total_opt,
               unknown=[rows nobody projects], perms=[slots that merely permuted])"""
    cfg = state.cfg; slots = cfg.slots
    rows = []
    for r in state.mine:
        if r['slot'] == 'IR': continue
        L = proj.line(r['key'], r['pos'], r['tm'])
        r['line'] = L
        r['pts'] = SC.points(L, state.league)
        r['boom'] = SC.boom(L, state.league)
        r['kick'] = proj.kickoff(r['tm'])
        r['phase'] = C.lineup_phase(r['kick'])
        r['ready'] = proj.market_ready(r['tm'])
        a = (actuals or {}).get(r['key'])
        r['final'] = bool(a) and a['final']
        r['live'] = bool(a) and not a['final']
        if a:
            from . import actuals as AC
            r['actual'] = a['pts']; r['frac'] = a['frac']; r['boom'] = None; r['ready'] = True
            r['proj_pts'] = r['pts']
            # final: the number is a fact. In progress: live points so far plus the
            # unplayed share of the projection. Either way the slot is locked.
            r['pts'] = AC.blend(a, r['pts']); r['phase'] = 'final' if a['final'] else 'live'
        rows.append(r)
    R = [r for r in rows if r['designation'] not in UNUSABLE and r['pts'] is not None]
    Cm = np.full((len(R), len(slots)), 1e6)
    for i, r in enumerate(R):
        for j, s in enumerate(slots):
            if r['elig'] & cfg.accepts[s]: Cm[i, j] = -r['pts']
    ri, ci = linear_sum_assignment(Cm)
    opt = {s: None for s in slots}
    for i, j in zip(ri, ci):
        if Cm[i, j] < 1e5: opt[slots[j]] = R[i]
    cur = state.current_lineup()

    cur_set = {r['key'] for r in cur.values() if r}
    opt_set = {r['key'] for r in opt.values() if r}
    real_in, real_out = opt_set - cur_set, cur_set - opt_set
    changes, perms = [], []
    unclaimed = set(real_out)          # each displaced starter is named once (Cross/Odunze 09-23)
    for s in slots:
        c, o = cur.get(s), opt.get(s)
        if (c and o and c['key'] == o['key']) or (c is None and o is None): continue
        # a permutation: both players are starters either way
        if (not o or o['key'] in cur_set) and (not c or c['key'] in opt_set):
            perms.append(s); continue
        if o and o['key'] in real_in:
            if o.get('final') or o.get('live') or (c and (c.get('final') or c.get('live'))): continue   # locked either way
            # Yahoo locks a player at his kickoff: a swap involving anyone whose game has
            # started is not a move that can be made (Douglas for Likely at 2:20 pm, 09-27)
            if o.get('phase') == 'locked' or (c and c.get('phase') == 'locked'): continue
            # who does he displace? the starter in real_out with the same slot-family, else any
            out = c if (c and c['key'] in unclaimed) else next((x for x in cur.values() if x and x['key'] in unclaimed), None)
            if out: unclaimed.discard(out['key'])
            gain = (o['pts'] or 0) - ((out['pts'] or 0) if out else 0)
            # a Q/D starter projected at exactly 0 is a source ASSUMING he is out
            # (Sleeper zeroes injured players; Cross 09-23). That is a game-status
            # question, not a lineup edge: provisional, with the reason named.
            q_zero = bool(out) and out.get('designation') in ('Q', 'D') and not (out['pts'] or 0)
            # a starter Yahoo tags OUT (O/IR/PUP/SUSP/NA) is a hole, not a lineup edge:
            # replacing him is FIRM whatever the market has or has not posted (Burns,
            # torn ACL, 09-29: 'Watt over Burns — not a move until the market posts')
            sit_out = bool(out) and out.get('designation') in UNUSABLE
            changes.append(dict(slot=s, start=o, sit=out, gain=gain,
                                provisional=(not sit_out) and ((gain < NOISE) or not o['ready'] or (bool(out) and not out.get('ready', True)) or bool(o['line'].get('partial')) or q_zero),
                                reason=(f"{out['player']} is {out['designation']} — the slot scores nothing until he is replaced" if sit_out else
                                        f"{out['player']} is {out['designation']} and projected 0.00 — the source assumes he is OUT; if he is active he keeps the slot" if q_zero else ''),
                                phase=o['phase'], kick=o['kick']))
    tot = lambda d: sum((r['pts'] or 0) for r in d.values() if r)
    return dict(optimal=opt, current=cur, changes=changes, perms=perms,
                total_cur=tot(cur), total_opt=tot(opt), rows=rows,
                unknown=[r for r in rows if r['pts'] is None and r['designation'] not in UNUSABLE])
