"""UNIFIED ROSTER PLANNER — one decision layer for every roster move, both leagues.

Before this module every decision block (breakout.scan, Wire.upgrade_board /
bench_board / stream_board, and the week_upgrade / stream / stream_holes / IR /
next-man-up blocks in ff.build) both gathered evidence AND made a move: each picked
its own drop or open spot, measured value its own way (week points, season VOR,
implied totals, usage tier), checked only some rules, and they ran in build() order
so the first took the shared resources. Conflicts were patched pairwise. Here:

  Facts (lib/facts.py)     what is true about each player — evidence only
  Mechanics                what Yahoo lets Caleb do, when (every entry says verified or not)
  SpotPool                 the roster spots a move can use, each usable ONCE
  Candidates               who might be added and why (evidence only, merged per player)
  Objective J              one value measure for every (candidate, spot) pair
  Hard rules               infeasible pairs, each with the rule that binds
  Solve                    Hungarian with a no-move column, budgets, joint re-evaluation,
                           then the week-W lineup on the post-move roster

THE OBJECTIVE, per (candidate, spot) pair — every term is printed on every move:

  J = 1.0 * dS_W  +  0.8 * dS_W1  +  0.3 * dS_REST  +  0.1 * dBOOM
      - k_acq * acquisitions  - k_fab * bid / 10  - k_churn * transactions

  dS_t     optimal-lineup points after minus before in week t (lineup.optimal_points,
           Yahoo's locks pinned in week W; a move that takes effect after the week rolls
           — a claim, a week-locked drop — contributes 0 to dS_W)
  dS_W1    the same for week W+1 (byes and long-term tags zeroed)
  dS_REST  the MEAN over weeks W+2..17 of dS_t on rest-of-season per-week values with
           each week's byes zeroed — i.e. the sum divided by the number of rest weeks,
           one week-equivalent (REST_NORM = 'mean'). With W_REST = 0.8 (10-06; 0.3 let a season-long starter look cheaper than a one-week kicker) the whole rest of
           the season counts as 0.3 of an average week.
  dBOOM    bench upside: sum over active players NOT in the W+1 optimal lineup of
           boom share x rest-of-season per-week value, after minus before
  k_acq    HH: 1.0 per add (7 a week); BSB: 0
  k_fab    BSB: 0.1 per FAB dollar bid (bid / 10); HH: 0
  k_churn  0.5 per Yahoo transaction (an add/drop is one; an IR move is one)

A move ships when J >= 3.0 (SHIP_J). A hole (a slot with nobody to fill it in W or
W+1) clears it easily: the empty slot is a full player's points in dS. IR moves of a
verified season-ending player into a free IR slot ship regardless of J (doctrine:
'IR, not drop' — it costs nothing and frees a spot). Lineup changes on the
post-move roster ship like today's lineup calls: firm unless inside the 1.5-point
noise band or before the market posts (an OUT starter's replacement is firm).

HARD RULES (a pair that breaks one is infeasible; the binding rule is reported):
  roster <= slots + bench (every add needs a spot); IR <= IR slots and the player's
  tag is IR-eligible (IR/IR-R/PUP/PUP-R firm; O is ASK — unverified); Yahoo's week-lock
  (a started player moves only after the week rolls); mechanics (BSB claims vs free
  agents, HH in-progress games); FAB and HH acquisition budgets; gate G1 owned,
  G2 designation, G9 declined, G11 registry, handcuffs (G3), G14 superflex QB, state age
  (G12) — every add passes Wire.gate_add, every drop Wire.gate_drop with usage; no drop
  of a player Caleb added <= 7 days ago; no add of a player he dropped <= 7 days ago in
  either league; a tag is never a drop reason (values are 'as if healthy'; only a
  verified registry dead spot is worth 0); the spare DEF/K (lower season value, not a
  hold) is a spot only for a Tier-A add or a same-family stream; a sole DEF/K only for a
  same-family swap; a DEF/K stream that is not a hole never costs a real bench player;
  HH's elite second DEF is a registry hold; finished/live players never move; each spot
  once; Tier-B with one week of usage -> open / IR / dead spot only; Tier-B with two
  weeks -> a plain drop only if he out-projects it this week; Tier-A never takes a plain
  drop worth more over replacement than he is; a breakout add who would sit behind
  everyone at a position with dedicated slots is not a move.

Pure: plan() reads the run and the facts; it writes nothing. ff.py's shadow wiring
writes data/plan_{LG}.json and data/plan_diff.txt.
"""
import json
import numpy as np
from scipy.optimize import linear_sum_assignment
from . import clock as C, rules as RU, lineup as LU
from .facts import Facts, Fact, IR_TAGS

# ------------------------------------------------------------------ weights (read these)
W_NOW, W_NEXT, W_REST, W_BOOM = 1.0, 0.8, 0.8, 0.1
K_ACQ = {'HH': 1.0, 'BSB': 0.0}
K_FAB = 0.1                       # per dollar (bid / 10)
K_CHURN = 0.5                     # per Yahoo transaction
SHIP_J = 3.0
REST_NORM = 'mean'                # dS_REST = sum over weeks W+2..17 / number of those weeks
NOISE = LU.NOISE
GAME_H = 4.0
BIG = 1e9


class SpotReused(Exception):
    pass


# ================================================================== mechanics
class Mechanics:
    """What Yahoo lets Caleb do, and when. Every entry carries verified True/False."""

    def __init__(self, facts):
        self.f = facts
        lg = facts.league
        if lg == 'BSB':
            self.entries = [
                dict(rule='A never-rostered free agent is free until his game kicks off', verified=True,
                     text='RUNBOOK next-man-up; Fields/Jets cases'),
                dict(rule='A player whose game has kicked off this week is on waivers until the Wednesday run; claim by Tue 11:59 pm, bid from lib/fab + lib/rivals bid_for',
                     verified=True, text='RUNBOOK 09-27 live guard; rules.waiver_run_at (the log\'s actual run time, else Wed 06:00)'),
                dict(rule='A player dropped To Waivers is a claim until the run', verified=True, text='breakout._on_waivers (Fields 09-18 -> 09-23)'),
                dict(rule='Tue 07:00 -> Wed run: every unrostered player who played last week is a claim', verified=True, text='rules.bsb_claims_open (Jets DEF 09-29)'),
                dict(rule='A started player is locked until the week rolls; finished/live players never move', verified=True, text='Burns 09-28'),
                dict(rule='A benched player whose game is over cannot be dropped before the week rolls', verified=False,
                     text='not verified on Yahoo — treated as week-locked (the conservative reading)'),
                dict(rule='No IR slot; FAB $100, no acquisition cap', verified=True, text='leagues.BSB'),
            ]
        else:
            self.entries = [
                dict(rule='Free agents are immediate unless his game is in progress', verified=True, text='leagues.HH waivers; breakout._kicked'),
                dict(rule='7 acquisitions per week, counted from the most recent Tuesday 07:00 ET', verified=False,
                     text='the reset day is not documented for this league — Caleb\'s Adds on the log since Tue 07:00'),
                dict(rule='A player dropped To Waivers sits on waivers 1 day', verified=False, text='league setting "1-day, rolling"; the exact window is not verified'),
                dict(rule='3 IR slots; the player must carry an IR / IR-R / PUP / PUP-R tag', verified=True, text='Yahoo help SLN28136 (as recorded in roles.json)'),
                dict(rule='An O tag is IR-eligible', verified=False, text='roles.json says "O or IR"; not verified on this league\'s settings — the firm plan treats IR as tag-only and O as ASK'),
                dict(rule='A started player is locked until the week rolls; finished/live players never move', verified=True, text='Burns 09-28'),
                dict(rule='A benched player whose game is over cannot be dropped before the week rolls', verified=False,
                     text='not verified on Yahoo — treated as week-locked (the conservative reading)'),
            ]

    # ---- the clock for an add
    def acquire(self, c, tier=None):
        """-> dict(kind fa|claim|after_game, eff W|W+1, at, deadline, label, verified, bid)"""
        f = self.f; now = f.now
        ow = c.on_waivers
        if f.league == 'BSB':
            if ow:
                eff = 'W' if (ow['until'] < f.week_start_next and c.kick and c.kick > ow['until']) else 'W+1'
                bid = self.bid(c, tier)
                return dict(kind='claim', eff=eff, at=ow['until'], deadline=_tue_night(ow['until']), bid=bid,
                            label=f'claim by Tue night (${bid})', why=ow['why'], verified=True)
            return dict(kind='fa', eff='W', at=None, deadline=(c.kick if c.kick and c.kick > now else None), bid=None,
                        label='now', why='never-rostered free agent: free until his kickoff', verified=True)
        if ow:
            return dict(kind='claim', eff='W', at=ow['until'], deadline=None, bid=None,
                        label='after the 1-day waiver clears', why=ow['why'], verified=False)
        if c.kick and c.kick <= now < c.kick + C.dt.timedelta(hours=GAME_H):
            end = c.kick + C.dt.timedelta(hours=GAME_H)
            return dict(kind='after_game', eff='W', at=end, deadline=None, bid=None, label='after game',
                        why='his game is in progress — addable when it ends', verified=True)
        return dict(kind='fa', eff='W', at=None, deadline=None, bid=None, label='now', why='free agent, immediate', verified=True)

    def deferred(self, c, tier=None):
        """The same add made once the week rolls (Tuesday 07:00)."""
        f = self.f
        if f.league == 'BSB':
            run = RU.waiver_run_at(f.week + 1)
            bid = self.bid(c, tier)
            return dict(kind='claim', eff='W+1', at=run, deadline=_tue_night(run), bid=bid,
                        label=f'Tuesday (week-lock) — claim by Tue night (${bid})',
                        why='after the week rolls every unrostered player who played is a claim until the Wednesday run', verified=True)
        return dict(kind='fa', eff='W+1', at=f.week_start_next, deadline=None, bid=None, label='Tuesday (week-lock)',
                    why='after the week rolls (counts against next week\'s 7)', verified=False)

    def release(self, d):
        """-> dict(ok_now, at, lock_at, label) for dropping / IR-ing one of my players."""
        if d is None: return dict(ok_now=True, at=None, lock_at=None, label='')
        if d.locked or d.final or d.live:
            return dict(ok_now=False, at=self.f.week_start_next, lock_at=None,
                        label='Tuesday (week-lock)', why=f'{d.name} has played or kicked off this week — Yahoo locks him until the week rolls')
        return dict(ok_now=True, at=None, lock_at=d.lock_at, label='')

    def bid(self, c, tier):
        if self.f.league != 'BSB': return None
        t = tier if tier in ('A', 'B') else 'B'
        prof = self.f.rivals
        if prof is not None:
            try:
                from . import rivals as RV
                return int(RV.bid_for(prof, c.fam, t)['bid'])
            except Exception:
                pass
        try:
            from . import fab as F
            b = (F.model().get('bands') or {}).get(t)
            if b: return int(b['bid'])
        except Exception:
            pass
        return 1

    def ir_eligible(self, d):
        """True (firm) / 'ask' (O tag: unverified) / False."""
        if self.f.cfg.ir_slots <= 0: return False
        if d.designation in IR_TAGS: return True
        if d.designation == 'O': return 'ask'
        return False

    def as_list(self):
        return [dict(e) for e in self.entries]


def _tue_night(run_at):
    """The claim deadline for a Wednesday run: Tuesday 11:59 pm ET."""
    d = (run_at - C.dt.timedelta(days=1)).date()
    return C.dt.datetime(d.year, d.month, d.day, 23, 59, tzinfo=C.ET)


# ================================================================== spots
class Spot(dict):
    __getattr__ = dict.get


class SpotPool:
    """Open spots, IR-move spots, spare / sole DEF-K spots and clean drops. Each once."""

    def __init__(self, facts, mech):
        self.f, self.m = facts, mech
        self.spots, self.excluded, self.ir_moves = [], [], []
        self.taken = {}
        f = facts
        for i in range(f.open_spots):
            self.spots.append(Spot(id=f'open{i + 1}', kind='open', tier=-1, fact=None, label='an open roster spot', fam=None))
        # IR moves: a verified season-ending player (registry ir) with a free IR slot
        n_ir = 0
        ir_bound = set()
        for k in f.mine_keys:
            d = f.mine[k]
            if d.slot == 'IR' or not d.registry.ir: continue
            if f.ir_free <= n_ir:
                self.excluded.append((d, 'registry says IR, but no IR slot is free'))
                continue
            el = mech.ir_eligible(d)
            ir_bound.add(k)
            if el is True:
                n_ir += 1
                self.spots.append(Spot(id=f'ir:{k}', kind='ir', tier=-1, fact=d, fam=None, ir='firm',
                                       label=f'the spot {d.name} frees (IR move first)'))
            elif el == 'ask':
                n_ir += 1
                self.ir_moves.append(dict(fact=d, status='ask'))
            else:
                self.ir_moves.append(dict(fact=d, status='not_tagged'))
        # spare DEF/K: the lower season value of two, not a hold
        spare = {}
        for fam in ('DEF', 'K'):
            pair = [f.mine[k] for k in f.mine_keys if f.mine[k].fam == fam and f.mine[k].slot != 'IR' and not f.mine[k].registry.hold]
            allfam = [f.mine[k] for k in f.mine_keys if f.mine[k].fam == fam and f.mine[k].slot != 'IR']
            if len(allfam) >= 2 and pair:
                pair.sort(key=lambda x: ((f.season.get(x.key) or {}).get('pts') or 0.0, x.pts_w or 0.0, x.key))
                spare[fam] = pair[0].key
        for k in f.mine_keys:
            d = f.mine[k]
            if d.slot == 'IR' or k in ir_bound: continue
            why = self._why_not(d)
            if why:
                self.excluded.append((d, why)); continue
            if d.fam in ('DEF', 'K'):
                kind = 'spare' if spare.get(d.fam) == k else 'swap'
                tier = 2
            else:
                kind = 'drop'
                tier = 0 if d.registry.dead else 1 if d.registry.drop_ok else 3
            self.spots.append(Spot(id=f'drop:{k}', kind=kind, tier=tier, fact=d, fam=d.fam,
                                   label=d.name, gate=d.get('_gate')))
        self.spots.sort(key=lambda s: (s.tier, s.id))

    def _why_not(self, d):
        """Why my player is not a clean drop (None if he is)."""
        if d.registry.hold: return 'registry HOLD — ' + (d.registry.call or '')[:80]
        if d.registry.handcuff: return f'handcuff to {d.registry.handcuff}'
        if d.recently_added: return f'you added him {d.recently_added} (<= 7 days) — your decision, not the spot'
        if d.final or d.live: return 'his game is final / live — finished and live players never move'
        if d.usage_now == 'start' and not d.registry.dead and not d.registry.drop_ok:
            return 'starter-level usage in his own right (' + (d.usage_now_rule or '') + ')'
        g = self.f.gate_drop(d)
        d['_gate'] = g
        if g is not None and g.verdict == 'BLOCK':
            return 'gate: ' + '; '.join(f'{gg} {m}' for gg, s_, m in g.checks if s_ == 'BLOCK')[:160]
        return None

    def take(self, spot_id, by):
        if spot_id in self.taken:
            raise SpotReused(f'{spot_id} already taken by {self.taken[spot_id]} (asked by {by})')
        self.taken[spot_id] = by

    def by_id(self, sid):
        return next((s for s in self.spots if s.id == sid), None)


# ================================================================== candidates
class Candidate(dict):
    __getattr__ = dict.get


def _merge(cands, key, fact, reason):
    c = cands.get(key)
    if c is None:
        c = cands[key] = Candidate(key=key, fact=fact, reasons=[], tier=None, held='', hole=False, srcs=set(),
                                   firm=False, name=(fact.name if fact else reason.get('name', key)))
    c.reasons.append(reason)
    c.srcs.add(reason['src'])
    if reason.get('tier') in ('A', 'B'):
        if c.tier is None or reason['tier'] < c.tier: c['tier'] = reason['tier']
    if reason.get('held'): c['held'] = reason['held']
    if reason.get('hole'): c['hole'] = True
    if reason.get('firm'): c['firm'] = True
    return c


def produce(facts, ev):
    """Evidence -> candidates (one per player, several reasons). No drops, no verdicts."""
    f = facts
    cands = {}
    W, W1 = f.week, f.week + 1
    # 1. breakout tiers A/B (reuse breakout.scan rows)
    for x in ev.get('breakout_rows') or []:
        if x.get('tier') not in ('A', 'B'): continue
        fa = f.fa(x['key'])
        _merge(cands, x['key'], fa, dict(src='breakout', tier=x['tier'], held=x.get('held') or '', name=x.get('name'),
                                         in_pool=bool(x.get('in_pool')), ahead=bool(x.get('ahead')),
                                         text=f"breakout tier {x['tier']}: {x.get('usage', '')}; {x.get('market', '')}"
                                              + (f"; held ({x['held']})" if x.get('held') else ''),
                                         vor=x.get('vor')))
    # 2. weekly upgrades (Wire.upgrade_board: best FA vs the weakest current starter)
    for u in ev.get('upgrades') or []:
        k = u['add']['key']
        _merge(cands, k, f.fa(k), dict(src='upgrade', text=f"{u['fam']} weekly upgrade: {u['add']['name']} {(u['add'].get('week') or 0):.1f} vs starter {u['over']['player']} {(u['over'].get('pts') or 0):.1f}"))
    # 3. holes in W and W+1 at ANY position (a slot nobody on the roster can fill: bye or out)
    for t in (W, W1):
        rows, vals, locks = _week_inputs(f, [], t)
        tot, asg = LU.optimal_points(rows, f.cfg, vals, locks)
        for s, k in sorted(asg.items()):
            # a slot is a hole when nobody on the roster scores in it: empty, or held by a
            # player with NO GAME this week or tagged OUT (10-06: Butker on bye still
            # 'filled' the K slot). A zero projection with a game is not a hole.
            if k is not None:
                if (vals.get(k) or 0) > 0: continue
                if t == W:                                                 # this week: no game yet / OUT only
                    kf = f.mine.get(k)
                    if kf is None or not (getattr(kf, 'kick', None) is None or kf.designation in RU.UNUSABLE): continue
            if k is not None and k in locks: continue                     # a locked starter keeps his slot
            acc = set()
            for fm, sl in f.cfg.fam_slots.items():
                if s in sl: acc.add(fm)
            fams = sorted(acc)
            why = _hole_why(f, s, t)
            for c in f.best_fa(None, t, n=8, accept=fams):                 # deep enough that single-source (G5) kickers do not hide the cover (10-06: Santos)
                if t == W and (c.kicked or c.on_waivers): continue
                _merge(cands, c.key, c, dict(src='hole', hole=True, firm=True, slot=s, week=t,
                                             text=f'week-{t} hole at {s} ({why}); {c.name} {f.value(c, t):.1f} is the best free {c.fam} on week-{t} values'))
    # 4. DEF/K streams for W+1 (the objective decides whether the edge pays)
    for fam in ('DEF', 'K'):
        mine_best = max([f.value(f.mine[k], W1) or 0 for k in f.mine_keys if f.mine[k].fam == fam and f.mine[k].slot != 'IR'] or [0.0])
        for c in f.best_fa(fam, W1, n=2):
            if (f.value(c, W1) or 0) > mine_best:
                _merge(cands, c.key, c, dict(src='stream', week=W1,
                                             text=f'week-{W1} {fam} stream: {c.name} {f.value(c, W1):.1f} vs your best {mine_best:.1f} ({c.w1_src})'))
    # 5. next man up (a starter OUT now whose backup is a free agent)
    for a in ev.get('nextup') or []:
        if not a.get('fa'): continue
        k = a['fa']['key']
        r = a['row']
        _merge(cands, k, f.fa(k), dict(src='nextup', firm=True,
                                       text=f"next man up: {r['player']} ({r['slot']}) is {r['status']} — {a['fa']['name']} inherits the role"))
    # 6. registry add_yes
    for k, v in sorted((f.add_yes or {}).items()):
        if k.startswith('_') or k in f.state.roster_keys: continue
        _merge(cands, k, f.fa(k), dict(src='registry', text=f"registry add_yes (priority {v.get('priority', '?')}): {str(v.get('why', ''))[:90]}"))
    return [cands[k] for k in sorted(cands)]


def _hole_why(f, s, t):
    acc = f.cfg.accepts[s]
    who = [f.mine[k] for k in f.mine_keys if f.mine[k].slot != 'IR' and (f.mine[k].elig & acc)]
    if not who: return 'nobody on the roster is eligible'
    if all((f.value(x, t) or 0) > 0 for x in who): return 'every eligible player is needed in another slot'
    parts = []
    for x in who[:3]:
        v = f.value(x, t)
        if x.tm in f.byes.get(t, set()) or (t == f.week and getattr(x, 'kick', None) is None and x.designation not in RU.UNUSABLE):
            parts.append(f'{x.name} on bye')
        elif v is None or x.designation in RU.UNUSABLE: parts.append(f'{x.name} {x.designation}')
        elif v <= 0: parts.append(f'{x.name} {x.w1_src if t == f.week + 1 else "0"}')
    return ', '.join(parts) or 'no eligible player with a number'


# ================================================================== objective
def _week_inputs(f, changes, t):
    """Roster rows, values and locks for week t after `changes`
    [(add_fact|None, drop_fact|None, eff)] — the pure input to lineup.optimal_points."""
    W = f.week
    gone, added = set(), []
    for add, drop, eff in changes:
        if t == W and eff != 'W': continue
        if drop is not None: gone.add(drop.key)
        if add is not None: added.append(add)
    rows, vals, locks = [], {}, {}
    for k in f.mine_keys:
        d = f.mine[k]
        if d.slot == 'IR' or k in gone: continue
        rows.append(dict(key=k, elig=d.elig))
        vals[k] = f.value(d, t)
        if t == W and (d.locked or d.final or d.live):
            locks[k] = d.slot if d.slot not in ('BN', 'IR') else 'BN'
    for a in added:
        rows.append(dict(key=a.key, elig=a.elig))
        if t == W:
            ow = a.on_waivers
            late = bool(ow) and not (a.kick and ow['until'] < a.kick)      # still on waivers at his kickoff
            vals[a.key] = None if (a.kicked or late) else a.pts_w
        else:
            vals[a.key] = f.value(a, t)
    rows.sort(key=lambda r: r['key'])
    return rows, vals, locks


class Objective:
    def __init__(self, facts):
        self.f = facts
        self.cache = {}
        teams = {facts.mine[k].tm for k in facts.mine_keys}
        self.teams = teams

    def _S(self, changes, t, extra_teams=()):
        f = self.f
        ck = tuple(sorted((a.key if a else '', d.key if d else '', e) for a, d, e in changes))
        if t in (f.week, f.week + 1):
            sig = ('t', t)
        else:
            rel = self.teams | set(extra_teams)
            sig = ('r', frozenset(f.byes.get(t, set()) & rel))
        key = (ck, sig)
        if key not in self.cache:
            rows, vals, locks = _week_inputs(f, changes, t)
            tot, asg = LU.optimal_points(rows, f.cfg, vals, locks)
            self.cache[key] = (tot, asg)
        return self.cache[key]

    def boom(self, changes):
        f = self.f
        rows, vals, locks = _week_inputs(f, changes, f.week + 1)
        _, asg = self._S(changes, f.week + 1)
        starting = {k for k in asg.values() if k}
        facts = {r['key']: (f.mine.get(r['key']) or next((a for a, _, _ in changes if a is not None and a.key == r['key']), None)) for r in rows}
        tot = 0.0
        for k, x in facts.items():
            if k in starting or x is None: continue
            tot += (x.boom or 0.0) * (x.ros_pw or 0.0)
        return tot

    def terms(self, changes, costs):
        """J and its terms for a set of changes against the current roster."""
        f = self.f
        W, W1 = f.week, f.week + 1
        xt = {a.tm for a, _, _ in changes if a is not None}
        dW = self._S(changes, W)[0] - self._S([], W)[0]
        dW1 = self._S(changes, W1)[0] - self._S([], W1)[0]
        rest = [self._S(changes, t, xt)[0] - self._S([], t, xt)[0] for t in f.rest_weeks]
        dR = (sum(rest) / len(rest)) if rest else 0.0
        dB = self.boom(changes) - self.boom([])
        acq = costs.get('acq', 0); bid = costs.get('bid', 0) or 0; txn = costs.get('txn', 0)
        J = (W_NOW * dW + W_NEXT * dW1 + W_REST * dR + W_BOOM * dB
             - K_ACQ.get(f.league, 0.0) * acq - K_FAB * bid - K_CHURN * txn)
        return dict(J=round(J, 3), dS_W=round(dW, 3), dS_W1=round(dW1, 3), dS_rest=round(dR, 3), d_boom=round(dB, 3),
                    acq=acq, bid=bid, txn=txn,
                    pen_acq=round(K_ACQ.get(f.league, 0.0) * acq, 3), pen_fab=round(K_FAB * bid, 3), pen_churn=round(K_CHURN * txn, 3),
                    rest_weeks=f'{f.rest_weeks[0]}-{f.rest_weeks[-1]}' if f.rest_weeks else '')


def fmt_terms(t):
    return (f"J {t['J']:+.2f} = {W_NOW:.1f}x{t['dS_W']:+.2f} (wk W) + {W_NEXT:.1f}x{t['dS_W1']:+.2f} (W+1) + {W_REST:.1f}x{t['dS_rest']:+.2f} (rest, mean of wks {t['rest_weeks']})"
            f" + 0.1x{t['d_boom']:+.2f} (bench boom) - {t['pen_acq']:.2f} acq - {t['pen_fab']:.2f} FAB(${t['bid'] or 0}) - {t['pen_churn']:.2f} churn")


# ================================================================== feasibility
def candidate_block(f, c, ev):
    """Rules that bind regardless of the spot -> reason or None."""
    x = c.fact
    if x is None:
        r = next((r for r in c.reasons if r['src'] == 'breakout'), None)
        return 'not in the projection pool — usage only, no source prices him' if r and not r.get('in_pool') else 'not in this league\'s pool (owned, or no source prices him)'
    if x.owner is not None or x.key in f.state.roster_keys: return f'G1: on a roster in this league'
    if x.registry.add_no: return 'G11: registry add_no / unavailable'
    if x.recently_dropped:
        lg, d = x.recently_dropped if isinstance(x.recently_dropped, (tuple, list)) else (f.league, x.recently_dropped)
        return f'you dropped him in {lg} on {d} (<= 7 days, either league)'
    if x.final or x.live: return 'his game is final / live'
    # a breakout add who would sit behind everyone at a position with dedicated slots
    if c.srcs == {'breakout'} and c.tier in ('A', 'B'):
        same = [f.mine[k] for k in f.mine_keys if f.mine[k].slot != 'IR' and f.mine[k].fam == x.fam and f.mine[k].designation not in RU.UNUSABLE]
        dedicated = [s for s in f.cfg.fam_slots.get(x.fam, ()) if s not in ('W/R/T', 'W/R', 'Q/W/R/T')]
        nslots = len(dedicated) or len(f.cfg.fam_slots.get(x.fam, ()))
        weak = min([m.pts_w for m in same if m.pts_w is not None] or [None]) if same else None
        if len(same) >= nslots + 1 and x.pts_w is not None and weak is not None and x.pts_w < weak:
            return f'sits behind everyone: you carry {len(same)} {x.fam}s for {nslots} slot(s) and he projects {x.pts_w:.1f} under your weakest {weak:.1f}'
    g = c.get('gate')
    if g is not None and g.verdict == 'BLOCK':
        return 'gate: ' + '; '.join(f'{gg} {m}' for gg, s_, m in g.checks if s_ == 'BLOCK')[:160]
    return None


def pair_block(f, c, s, repl):
    """Rules for this (candidate, spot) -> reason or None. The candidate's own doctrine
    (breakout tiers) is checked before the spot's, so the binding reason names it."""
    x = c.fact
    only_bk = not (c.srcs - {'breakout'})
    if c.tier == 'B' and only_bk:
        if not c.held and not (s.kind in ('open', 'ir') or s.tier == 0):
            return 'Tier B on one week of usage: an open, IR or dead spot only — a real player waits for the second week'
        if c.held and s.kind == 'spare':
            return 'Tier B (unpriced) never takes the spare DEF — Tier A only'
        if c.held and s.kind == 'drop' and s.tier >= 3 and x.pts_w is not None and (s.fact.pts_w or 0) >= x.pts_w:
            return f'Tier B held, but {s.label} ({s.fact.pts_w or 0:.1f}) projects at or above him ({x.pts_w:.1f}) this week'
    if c.tier == 'A' and only_bk and s.kind == 'drop' and s.tier >= 3:
        dv = (s.fact.ros_pw or 0) - repl.get(s.fact.fam, 0.0)
        xv = (x.ros_pw or 0) - repl.get(x.fam, 0.0)
        if dv > xv:
            return f'{s.label} is worth more over replacement at his position ({dv:+.1f}/wk) than the add at his ({xv:+.1f}/wk)'
    if s.kind == 'spare':
        if not (c.tier == 'A' or (x.fam == s.fam and ({'stream', 'hole', 'upgrade'} & c.srcs))):
            return f'{s.label} is the spare {s.fam}: a spot for a Tier-A add or a same-family stream only (~1 pt/wk on its own, 09-24)'
    if s.kind == 'swap' and x.fam != s.fam:
        return f'{s.label} is your only {s.fam}: a one-for-one {s.fam} swap only'
    if x.fam in ('DEF', 'K') and not c.hole and s.kind == 'drop' and s.tier >= 3:
        return f'a {x.fam} stream that is not a hole never costs a real bench player ({s.label})'
    # a kicker or defense is fungible: it NEVER costs a skill player or an IDP, hole or
    # not — the spot is an open spot, the spare/only DEF-K (a one-for-one swap), or a
    # dead/registry spot (10-06: 'add Boswell, drop Travis Kelce' at J +11 because the
    # rest-of-season term made Kelce look cheap)
    if x.fam in ('DEF', 'K') and s.kind == 'drop' and s.fact is not None and s.fact.fam not in ('DEF', 'K') and s.tier >= 2:
        return f'a {x.fam} never costs a {s.fact.fam} ({s.label}) — kickers and defenses swap one-for-one'
    return None


# ================================================================== solve
def plan_facts(facts, ev=None):
    """The planner on prepared facts and evidence. Pure. -> Plan"""
    ev = ev or {}
    f = facts
    mech = Mechanics(f)
    pool = SpotPool(f, mech)
    obj = Objective(f)
    cands = produce(f, ev)
    # replacement level per family (best free agent's rest-of-season per-week value)
    repl = {}
    for fam in sorted({c.fact.fam for c in cands if c.fact} | {s.fam for s in pool.spots if s.fam}):
        b = f.best_fa(fam, f.week + 2 if f.rest_weeks else f.week + 1, n=1)
        repl[fam] = (b[0].ros_pw or 0.0) if b else 0.0
    rejected = {}
    pairs = {}             # (cand key, spot id) -> eval
    for c in cands:
        if c.fact is not None:
            hz = 'weekly' if c.fact.fam in ('DEF', 'K') else 'season'
            usage = None
            if c.fact.usage_now and f.usage_week:
                usage = f'wk{f.usage_week} {c.fact.usage_now_rule}'
            # a DEF/K stream or hole cover is priced on next week's posted lines: that is
            # the 'vegas' family the old stream calls named (ff.build stream_calls)
            extra = ['vegas'] if (c.fact.fam in ('DEF', 'K') and ({'stream', 'hole'} & c.srcs) and f.posted_lines_next()) else []
            c['gate'] = f.gate_add(c.fact, horizon=hz, usage=usage, extra_sources=extra)
        why = candidate_block(f, c, ev)
        if why:
            rejected[c.key] = dict(cand=c, reason=why, J=None); continue
        best = None
        for s in pool.spots:
            e = _eval_pair(f, mech, obj, c, s, repl)
            pairs[(c.key, s.id)] = e
            if best is None or (e['J'] if e['feasible'] else -BIG) > (best['J'] if best['feasible'] else -BIG) \
                    or (not best['feasible'] and not e['feasible'] and e['J'] > best['J']):
                best = e
        c['best'] = best
    live = [c for c in cands if c.key not in rejected]
    # ---- assignment with a no-move column per candidate; budgets enforced by removal
    excluded = set()
    while True:
        rows_ = [c for c in live if c.key not in excluded]
        chosen = _assign(rows_, pool.spots, pairs)
        over = _budget_violation(f, mech, chosen, pairs)
        if not over: break
        ck, why = over
        excluded.add(ck)
        rejected[ck] = dict(cand=next(c for c in live if c.key == ck), reason=why, J=pairs[(ck, chosen[ck])]['J'])
    # ---- joint re-evaluation: the set as a whole, each move on its marginal value
    sel = dict(chosen)
    while sel:
        marg = _marginals(f, obj, sel, pairs, live)
        worst = min(sel, key=lambda k: (marg[k]['J'], k))
        if marg[worst]['J'] >= SHIP_J: break
        rejected[worst] = dict(cand=next(c for c in live if c.key == worst),
                               reason=f"jointly with the rest of the plan it adds only J {marg[worst]['J']:+.2f} (< {SHIP_J}) — {fmt_terms(marg[worst])}",
                               J=marg[worst]['J'])
        del sel[worst]
    marg = _marginals(f, obj, sel, pairs, live) if sel else {}
    # ---- the moves, in a deterministic order (by spot timing then J)
    moves = []
    for ck in sorted(sel, key=lambda k: (-marg[k]['J'], k)):
        c = next(x for x in live if x.key == ck)
        e = pairs[(ck, sel[ck])]
        s = pool.by_id(sel[ck])
        pool.take(s.id, c.name)
        moves.append(_add_move(f, c, s, e, marg[ck]))
    # ---- IR moves: verified season-ending, tag-eligible, free slot — ship whether or not an add uses the spot
    for s in pool.spots:
        if s.kind != 'ir' or s.id in pool.taken: continue
        pool.take(s.id, f'IR move {s.fact.name}')
        moves.append(_ir_move(f, mech, s.fact, firm=True))
    for im in pool.ir_moves:
        if im['status'] == 'ask':
            moves.append(_ir_move(f, mech, im['fact'], firm=False))
    # ---- unassigned candidates: the binding reason
    for c in live:
        if c.key in sel or c.key in rejected: continue
        b = c.best
        if b is None:
            rejected[c.key] = dict(cand=c, reason='no roster spot exists', J=None)
        elif not b['feasible']:
            rejected[c.key] = dict(cand=c, reason=f"best spot {b['spot_label']}: {b['reason']}", J=b['J'])
        elif b['J'] < SHIP_J:
            rejected[c.key] = dict(cand=c, reason=f"J {b['J']:+.2f} < {SHIP_J} at its best spot ({b['spot_label']}) — {fmt_terms(b['terms'])}", J=b['J'])
        else:
            who = next((m for m in moves if m.get('spot_id') == b['spot_id']), None)
            rejected[c.key] = dict(cand=c, reason=f"its best spot ({b['spot_label']}) went to {who['add_name'] if who else 'another move'} at higher value", J=b['J'])
    # ---- the week-W lineup on the post-move roster -> slot transactions
    lineup_after, lmoves = _lineup_after(f, moves, ev)
    moves += lmoves
    plan = Plan(league=f.league, week=f.week, made=C.iso(f.now), moves=moves, lineup_after=lineup_after,
                rejected=[dict(key=k, name=v['cand'].name, reason=v['reason'], J=v['J'],
                               reasons=[r['text'] for r in v['cand'].reasons]) for k, v in sorted(rejected.items())],
                mechanics=mech.as_list(), excluded=[dict(player=d.name, reason=w) for d, w in pool.excluded],
                spots=[dict(id=s.id, kind=s.kind, label=s.label, tier=s.tier, taken_by=pool.taken.get(s.id)) for s in pool.spots],
                budgets=dict(acq_used=f.acq_used, acq_left=f.acq_left, acq_reset=C.iso(f.acq_reset) if f.league == 'HH' else None,
                             acq_reset_verified=False if f.league == 'HH' else None, fab_left=f.fab_left,
                             ir_free=f.ir_free, open_spots=f.open_spots),
                weights=dict(W_NOW=W_NOW, W_NEXT=W_NEXT, W_REST=W_REST, W_BOOM=W_BOOM, K_ACQ=K_ACQ.get(f.league), K_FAB=K_FAB,
                             K_CHURN=K_CHURN, SHIP_J=SHIP_J, REST_NORM=REST_NORM),
                notes=list(f.notes))
    wp = ev.get('winprob')
    if wp is not None:
        try: plan.winprob = wp(lineup_after)
        except Exception as e: plan.winprob = dict(error=repr(e))
    return plan


def _eval_pair(f, mech, obj, c, s, repl):
    x = c.fact
    base = dict(cand=c.key, spot_id=s.id, spot_label=s.label, feasible=False, reason=None, J=-BIG, terms=None, timing=None)
    why = pair_block(f, c, s, repl)
    d = s.fact
    rel = mech.release(d)
    options = []
    if rel['ok_now']:
        a = mech.acquire(x, c.tier)
        options.append(('earliest', a))
        if d is not None and (f.value(d, f.week) or 0) > 0 and a['eff'] == 'W':
            options.append(('deferred', mech.deferred(x, c.tier)))
    else:
        options.append(('deferred', mech.deferred(x, c.tier)))
    best = None
    for how, a in options:
        # the drop must not lock before the add can happen
        if how == 'earliest' and a.get('at') and rel.get('lock_at') and rel['lock_at'] <= a['at']:
            a = mech.deferred(x, c.tier); how = 'deferred'
        eff = a['eff']
        ch = [(x, d, eff)]
        # an IR move of a verified season-ending player ships whether or not an add
        # uses its spot, so its transaction is not charged to the add
        txn = 1
        costs = dict(acq=1, bid=(a.get('bid') or 0) if f.league == 'BSB' and a['kind'] == 'claim' else 0, txn=txn)
        t = obj.terms(ch, costs)
        timing = _timing(f, x, d, a, rel, how, s)
        cand = dict(base, terms=t, J=t['J'], timing=timing, acquire=a, how=how, eff=eff)
        if f.league == 'BSB' and a['kind'] == 'claim' and f.fab_left is not None and (a.get('bid') or 0) > f.fab_left:
            cand['reason'] = f"bid ${a['bid']} exceeds the FAB left (${f.fab_left})"
        if best is None or cand['J'] > best['J']: best = cand
    if why:
        best['reason'] = why
    best['feasible'] = best.get('reason') is None
    return best


def _timing(f, x, d, a, rel, how, s):
    now = f.now
    if how == 'deferred':
        lab = a['label'] if f.league == 'BSB' else 'Tuesday (week-lock)'
        return dict(label=lab, at=C.iso(a['at']) if a.get('at') else None,
                    deadline=C.iso(a['deadline']) if a.get('deadline') else None,
                    why=(rel.get('why') or 'held through this week: he plays for you first, the swap is after the week rolls'))
    if a['kind'] == 'claim':
        return dict(label=a['label'], at=C.iso(a['at']), deadline=C.iso(a['deadline']) if a.get('deadline') else None, why=a['why'])
    if a['kind'] == 'after_game':
        return dict(label='after game', at=C.iso(a['at']), deadline=None, why=a['why'])
    ks = [k for k in ((x.kick if (x.kick and x.kick > now) else None), rel.get('lock_at')) if k]
    if f.league == 'HH' and x.kick and x.kick > now and (f.value(x, f.week) or 0) <= 0:
        ks = [k for k in (rel.get('lock_at'),) if k]
    if ks:
        k0 = min(ks)
        return dict(label=f'before kickoff {C.stamp(k0)}', at=None, deadline=C.iso(k0), why=a['why'])
    return dict(label='now', at=None, deadline=None, why=a['why'])


def _assign(rows_, spots, pairs):
    """Hungarian over candidates x (spots + one no-move column each). Only pairs with
    J >= SHIP_J may be chosen. -> {cand key: spot id}"""
    if not rows_ or not spots: return {}
    n, m = len(rows_), len(spots)
    Cm = np.full((n, m + n), BIG)
    for i, c in enumerate(rows_):
        Cm[i, m + i] = 0.0
        for j, s in enumerate(spots):
            e = pairs.get((c.key, s.id))
            if e and e['feasible'] and e['J'] >= SHIP_J:
                # tie-break only (1e-3 per spot tier): on equal value an open / IR / dead
                # spot is used before a real player is cut, and a move made NOW takes the
                # open spot before a claim that only processes after the week rolls
                Cm[i, j] = -e['J'] + 1e-3 * (s.tier + 1) * (1.0 if e.get('eff') == 'W' else 0.5)
    ri, ci = linear_sum_assignment(Cm)
    out = {}
    for i, j in zip(ri, ci):
        if j < m and Cm[i, j] < BIG / 2: out[rows_[i].key] = spots[j].id
    return out


def _budget_violation(f, mech, chosen, pairs):
    """-> (cand key to drop, reason) or None. HH: adds effective this week <= acquisitions
    left; adds after the week rolls <= the cap. BSB: bids <= FAB left."""
    if not chosen: return None
    if f.league == 'HH' and f.acq_left is not None:
        now_ = [k for k, s in chosen.items() if pairs[(k, s)]['eff'] == 'W']
        nxt = [k for k, s in chosen.items() if pairs[(k, s)]['eff'] == 'W+1']
        if len(now_) > f.acq_left:
            k = min(now_, key=lambda k: (pairs[(k, chosen[k])]['J'], k))
            return k, f'HH acquisition cap: {f.acq_used} of {f.acq_cap} used since {C.stamp(f.acq_reset)} (reset day UNVERIFIED), {f.acq_left} left — higher-value adds take them'
        if len(nxt) > (f.acq_cap or 7):
            k = min(nxt, key=lambda k: (pairs[(k, chosen[k])]['J'], k))
            return k, f'HH acquisition cap for next week ({f.acq_cap})'
    if f.league == 'BSB' and f.fab_left is not None:
        tot = sum((pairs[(k, s)]['acquire'].get('bid') or 0) for k, s in chosen.items() if pairs[(k, s)]['acquire']['kind'] == 'claim')
        if tot > f.fab_left:
            ks = [k for k, s in chosen.items() if pairs[(k, s)]['acquire']['kind'] == 'claim']
            k = min(ks, key=lambda k: (pairs[(k, chosen[k])]['J'], k))
            return k, f'FAB budget: the plan\'s bids total ${tot}, ${f.fab_left} left'
    return None


def _marginals(f, obj, sel, pairs, live):
    """Each selected move's value given all the others (leave-one-out on the joint set)."""
    byk = {c.key: c for c in live}
    def chg(keys):
        out, costs = [], dict(acq=0, bid=0, txn=0)
        for k in keys:
            e = pairs[(k, sel[k])]
            c = byk[k]
            sid = sel[k]
            spot_fact = f.mine.get(sid.split(':', 1)[1]) if ':' in sid else None
            out.append((c.fact, spot_fact, e['eff']))
            costs['acq'] += 1
            costs['txn'] += 1
            if f.league == 'BSB' and e['acquire']['kind'] == 'claim': costs['bid'] += e['acquire'].get('bid') or 0
        return out, costs
    keys = sorted(sel)
    allc, allcost = chg(keys)
    full = obj.terms(allc, allcost)
    res = {}
    for k in keys:
        rest = [x for x in keys if x != k]
        rc, rcost = chg(rest)
        part = obj.terms(rc, rcost)
        res[k] = {kk: (round(full[kk] - part[kk], 3) if isinstance(full[kk], (int, float)) and not isinstance(full[kk], bool) else full[kk]) for kk in full}
    return res


def _gate_dict(g):
    if g is None: return None
    return dict(verdict=g.verdict, checks=[dict(gate=a, status=b, msg=c) for a, b, c in g.checks if b != 'PASS'])


def _add_move(f, c, s, e, terms):
    x = c.fact
    d = s.fact
    txns = []
    if s.kind == 'ir':
        txns.append(dict(op='ir', player=d.name, key=d.key))
    a = e['acquire'] if e['how'] == 'earliest' else None
    if e['acquire']['kind'] == 'claim':
        txns.append(dict(op='claim', player=x.name, key=x.key, bid=e['acquire'].get('bid')))
    else:
        txns.append(dict(op='add', player=x.name, key=x.key))
    if d is not None and s.kind != 'ir':
        txns.append(dict(op='drop', player=d.name, key=d.key))
    # an add that passed every hard rule and J >= 3 is a decision, not a provisional
    # call; WARN checks ride on the tile as 'check first' (as today)
    firm = True
    reasons = [r['text'] for r in c.reasons]
    if s.kind == 'open': reasons.append('the spot: an open roster spot — no drop needed')
    elif s.kind == 'ir': reasons.append(f'the spot: {d.name} moves to IR ({d.registry.why[:80]}) — his spot takes the add')
    else:
        dwhy = ('dead spot — verified in the registry' if s.tier == 0 else
                (d.registry.call or 'registry drop_ok')[:80] if s.tier == 1 else
                f'the {"spare" if s.kind == "spare" else "only"} {s.fam}' if s.kind in ('spare', 'swap') else
                f'rest-of-season {d.ros_pw or 0:.1f}/wk ({d.ros_src})' + (f'; tagged {d.designation} — the tag is not counted' if d.designation in RU.TAGGED else ''))
        reasons.append(f'the spot: {d.name} — {dwhy}')
    return dict(id=f'{f.league}:{x.key}', league=f.league, kind='add', add_name=x.name, add_key=x.key, fam=x.fam, tm=x.tm,
                drop_name=(d.name if d is not None and s.kind != 'ir' else None), spot_id=s.id, spot_kind=s.kind, spot_label=s.label,
                txns=txns, value_terms=terms, J=terms['J'], when=e['timing']['label'], at=e['timing'].get('at'),
                deadline=e['timing'].get('deadline'), timing_why=e['timing'].get('why'), eff=e['eff'],
                gates=dict(add=_gate_dict(c.get('gate')), drop=_gate_dict(s.gate)), reasons=reasons,
                tier=c.tier, srcs=sorted(c.srcs), provisional=not firm,
                values=dict(add=dict(w=x.pts_w, w1=x.pts_w1, w1_src=x.w1_src, ros=x.ros_pw, ros_src=x.ros_src, boom=x.boom),
                            drop=(dict(w=d.pts_w, w1=d.pts_w1, ros=d.ros_pw, ros_src=d.ros_src) if d is not None else None)))


def _ir_move(f, mech, d, firm):
    rel = mech.release(d)
    when = rel['label'] if not rel['ok_now'] else ('now' if firm else 'ask first')
    why = (f"{d.name} ({d.designation}) — {d.registry.why[:110]}. IR, not drop: a free IR slot keeps him and frees the roster spot"
           if firm else f"{d.name} is tagged O: whether O is IR-eligible in this league is UNVERIFIED — ask / check the IR slot before relying on the spot")
    return dict(id=f'{f.league}:ir:{d.key}', league=f.league, kind='ir', add_name=None, add_key=None, fam=d.fam, tm=d.tm,
                drop_name=None, spot_id=f'ir:{d.key}', spot_kind='ir', spot_label=d.name,
                txns=[dict(op='ir', player=d.name, key=d.key)], value_terms=None, J=None, when=when,
                at=C.iso(rel['at']) if rel.get('at') else None, deadline=None, timing_why=rel.get('why'),
                eff='W' if rel['ok_now'] else 'W+1', gates=dict(add=None, drop=None), reasons=[why],
                tier=None, srcs=['ir'], provisional=not firm, ir_name=d.name, ir_slot=d.slot)


def _lineup_after(f, moves, ev):
    """Optimal week-W lineup on the post-move roster; changes vs the current slots
    become slot transactions (in the add's Move when he is the one who starts)."""
    W = f.week
    changes = []
    for m in moves:
        if m['kind'] == 'add' and m['eff'] == 'W':
            add = f.fa(m['add_key'])
            # the player who leaves the active roster: dropped, or moved to IR (10-06:
            # an IR'd starter stayed in the lineup pairing as 'bench Kam Curl')
            drop = f.mine.get(next((t['key'] for t in m['txns'] if t['op'] in ('drop', 'ir')), None) or '')
            changes.append((add, drop, 'W'))
        if m['kind'] == 'ir' and m['eff'] == 'W' and not m['provisional']:
            changes.append((None, f.mine.get(m['txns'][0]['key']), 'W'))
    rows, vals, locks = _week_inputs(f, changes, W)
    tot, asg = LU.optimal_points(rows, f.cfg, vals, locks)
    r0, v0, l0 = _week_inputs(f, [], W)
    cur_tot, _ = LU.optimal_points(r0, f.cfg, v0, l0)
    gone = {d.key for _, d, _ in changes if d is not None}
    # the dropped starter's slot stays mapped to him so the lineup pairing says
    # 'over Butker (dropped)' at K instead of borrowing an unrelated displaced
    # starter (10-06: 'start Mevis at K over Chiefs')
    cur = {f.mine[k].slot: k for k in f.mine_keys if f.mine[k].slot not in ('BN', 'IR')}
    gone_slots = {f.mine[k].slot: k for k in gone if k in f.mine and f.mine[k].slot not in ('BN', 'IR')}
    for sl in gone_slots: cur.pop(sl, None)
    cur_set, opt_set = set(cur.values()), {k for k in asg.values() if k}
    real_in, real_out = opt_set - cur_set, cur_set - opt_set
    fact = lambda k: f.mine.get(k) or f.fa(k)
    unclaimed = set(real_out)
    lmoves = []
    by_add = {m['add_key']: m for m in moves if m['kind'] == 'add'}
    for s in f.cfg.slots:
        o = asg.get(s); c_ = cur.get(s)
        if o is None or o not in real_in: continue
        dropped_here = gone_slots.get(s)
        if dropped_here:
            out = None; of, xf = fact(o), fact(dropped_here)
        else:
            out = c_ if (c_ and c_ in unclaimed) else next((x for x in sorted(unclaimed)), None)
            if out: unclaimed.discard(out)
            of, xf = fact(o), (fact(out) if out else None)
        gain = (vals.get(o) or 0.0) - ((vals.get(out) or 0.0) if out else 0.0)
        bye_out = xf is not None and xf.designation not in RU.UNUSABLE and getattr(xf, 'kick', None) is None and not (vals.get(out or dropped_here) or 0)
        sit_out = xf is not None and (xf.designation in RU.UNUSABLE or bye_out)      # OUT or no game this week: a hole (10-06)
        hole = c_ is None and out is None
        q_zero = xf is not None and xf.designation in ('Q', 'D') and not (vals.get(out) or 0)
        prov_why = []
        if not (sit_out or hole):
            if gain < NOISE: prov_why.append(f'inside the {NOISE}-pt noise band')
            if not of.market_ready or (xf is not None and not xf.market_ready): prov_why.append('no player market posted yet for his game')
            if (of.line or {}).get('partial'): prov_why.append('thin market (TD price only)')
            if q_zero: prov_why.append(f'{xf.name} is {xf.designation} and projected 0.00 — the source assumes he is OUT')
            lr = ev.get('lineup_reason')
            if lr is not None:
                try:
                    r_ = lr(of.kick)
                    if r_: prov_why.append(f'inputs degraded ({r_})')
                except Exception: pass
        txns = [dict(op='start', player=of.name, key=o, slot=s)] + ([dict(op='bench', player=xf.name, key=out)] if (xf and out) else [])
        if o in by_add:
            by_add[o]['txns'] += txns
            by_add[o]['lineup'] = dict(slot=s, over=((xf.name + ' (dropped)') if dropped_here else xf.name) if xf else 'empty', gain=round(gain, 2))
            continue
        kick = of.kick
        lmoves.append(dict(id=f'{f.league}:lineup:{s}', league=f.league, kind='lineup', add_name=None, add_key=None,
                           fam=of.fam, tm=of.tm, drop_name=None, spot_id=None, spot_kind=None, spot_label=None,
                           txns=txns, value_terms=dict(J=round(gain, 3), dS_W=round(gain, 3)), J=round(gain, 3),
                           when=(f'before kickoff {C.stamp(kick)}' if kick and kick > f.now else 'now'),
                           at=None, deadline=C.iso(kick) if kick else None, timing_why='', eff='W', gates=dict(add=None, drop=None),
                           reasons=[((f"{xf.name} has no game this week (bye) — the slot scores nothing until he is replaced" if bye_out else f"{xf.name} is {xf.designation} — the slot scores nothing until he is replaced") if sit_out else
                                     'the slot is empty' if hole else f'{gain:+.2f} this week')] + prov_why,
                           tier=None, srcs=['lineup'], provisional=bool(prov_why), slot=s, start=of.name,
                           sit=(xf.name if xf else None), gain=round(gain, 2), phase=C.lineup_phase(kick) if kick else 'unknown'))
    after = dict(total=round(tot, 2), optimal_before_moves=round(cur_tot, 2),
                 slots={s: (fact(k).name if k else None) for s, k in asg.items()},
                 keys={s: k for s, k in asg.items()})
    return after, lmoves


# ================================================================== the plan
class Plan:
    def __init__(self, **kw):
        self.winprob = None
        self.__dict__.update(kw)

    def to_json(self):
        def clean(o):
            if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items() if not str(k).startswith('_')}
            if isinstance(o, (list, tuple)): return [clean(v) for v in o]
            if isinstance(o, set): return sorted(clean(v) for v in o)
            if isinstance(o, (np.floating,)): return float(o)
            if isinstance(o, (np.integer,)): return int(o)
            if hasattr(o, 'isoformat'): return o.isoformat()
            return o
        d = {k: v for k, v in self.__dict__.items()}
        return json.dumps(clean(d), indent=1, sort_keys=True, default=str)

    def summary(self):
        L = [f'PLAN — {self.league} week {self.week} ({self.made}) — {sum(1 for m in self.moves if not m["provisional"])} firm move(s), '
             f'{sum(1 for m in self.moves if m["provisional"])} provisional, {len(self.rejected)} considered and rejected']
        for m in self.moves:
            L.append(f"  {'PROV' if m['provisional'] else 'MOVE'} [{m['kind']}] " + ' ; '.join(_txn_txt(t) for t in m['txns']) + f"   when: {m['when']}")
            if m.get('value_terms') and m['kind'] == 'add': L.append('       ' + fmt_terms(m['value_terms']))
            for r in m['reasons'][:4]: L.append(f'       - {r}')
        return '\n'.join(L)


def _txn_txt(t):
    op = t['op']
    if op == 'claim': return f"claim {t['player']} (${t.get('bid')})"
    if op == 'start': return f"start {t['player']} at {t['slot']}"
    if op == 'bench': return f"bench {t['player']}"
    if op == 'ir': return f"{t['player']} -> IR"
    return f"{op} {t['player']}"


def evidence_from_run(run, lg):
    R = run['leagues'][lg]
    ev = dict(breakout_rows=(R.get('breakout') or {}).get('rows', []),
              upgrades=R['wire'].upgrade_board(R['lineup']),
              nextup=(R.get('nextup') or {}).get('alerts', []))
    CR = run.get('contract')
    if CR is not None and hasattr(CR, 'lineup_reason'): ev['lineup_reason'] = CR.lineup_reason
    ev['winprob'] = lambda after: _winprob(run, lg, after)
    return ev


def _winprob(run, lg, after):
    """P(beat opponent) / P(beat median) on the FINAL lineup only."""
    R = run['leagues'][lg]
    w = R.get('win') or {}
    cur = {s: (r['key'] if r else None) for s, r in R['lineup']['current'].items()}
    if all(cur.get(s) == after['keys'].get(s) for s in R['state'].cfg.slots) and w.get('current'):
        c = w['current']
        return dict(p_opp=c.get('p_opp'), p_med=c.get('p_med'), mean=c.get('mean'), note='final lineup = current lineup (the engine\'s own number)')
    from . import winprob as WP
    rows = {r['key']: r for r in R['lineup']['rows']}
    P = run['proj']
    lu_rows = []
    for s, k in after['keys'].items():
        if not k: continue
        r = rows.get(k)
        if r is None:
            e = R['wire'].pool.get(k) or {}
            L = P.line(k, e.get('pos'), e.get('tm'))
            from . import score as SC
            r = dict(key=k, player=e.get('name', k), pos=e.get('pos'), tm=e.get('tm'), line=L, pts=SC.points(L, lg), designation='none')
        lu_rows.append(r)
    fake = dict(current={i: r for i, r in enumerate(lu_rows)}, optimal={i: r for i, r in enumerate(lu_rows)}, rows=[])
    res = WP.evaluate(R['state'], P, fake, lg, actuals=R.get('actuals'))
    c = res['current']
    return dict(p_opp=c.get('p_opp'), p_med=c.get('p_med'), mean=c.get('mean'), note='sampled on the planner\'s final lineup')


def plan(run, lg):
    """Shadow entry point: facts from the run, evidence from the run, the plan. Pure."""
    f = Facts.build(run, lg)
    return plan_facts(f, evidence_from_run(run, lg))
