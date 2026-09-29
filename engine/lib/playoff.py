"""PLAYOFF LEVERAGE — what this week is worth, and who the race is against.

Every roster in the league is on disk, so every team's weekly strength can be
projected: its optimal lineup on per-player values (BSB: season blend / 17 where
a season number exists, else this week's projection; HH: this week's projection,
bye-week players at the league's positional median), re-solved for each future
week with that week's byes zeroed. The rest of the regular season (through week
14) is then simulated: each team's weekly score is normal around its strength,
head-to-head opponents are the known matchup this week and a random pairing after
(the league schedule is not on file — stated, not hidden), BSB adds the vs-median
result each week, standings are wins then points-for, and the top `playoff_teams`
qualify (BSB divisions are not modelled; stated).

  P(playoffs)                         where the season stands
  P(playoffs | win this week) minus
  P(playoffs | lose this week)        LEVERAGE: what this week's game is worth
  P(playoffs | +5 pts/week)           what a roster upgrade is worth
  the race                            every team's odds, so FAB and offers are
                                      judged against the two or three that matter

Individual points matter (Caleb): strengths are sums of individual numbers, no
environment haircut anywhere. Same-game correlation is not modelled here.
"""
import re, json, os
import numpy as np
from scipy.optimize import linear_sum_assignment
from . import score as SC, windows as WN
from .leagues import ALL

UNUSABLE = {'IR', 'IR-R', 'O', 'NA', 'PUP', 'PUP-R', 'SUSP', 'CEL'}
REG_SEASON_END = 14
N = 4000
CV = {'BSB': 0.15, 'HH': 0.10}     # weekly sd / mean, from the lineup sampler (122±18.5, 280±27)

def _record(txt):
    m = re.match(r'(\d+)-(\d+)-(\d+)', txt or '')
    w, l, t = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    pf = re.search(r'PF ([\d.]+)', txt or '')
    return w, l, t, float(pf.group(1)) if pf else 0.0

def player_values(state, proj, season=None):
    """{key: per-week value} for every rostered player in the league."""
    lg = state.league
    vals, wk_by_pos = {}, {}
    for r in state.rows:
        if r['slot'] == 'IR' or r['designation'] in UNUSABLE: vals[r['key']] = 0.0; continue
        L = proj.line(r['key'], r['pos'], r['tm'])
        wk = SC.points(L, lg) if not L.get('unknown') else None
        sea = (season or {}).get(r['key'], {}).get('pts') if season else None
        v = None
        if sea: v = sea / 17.0
        if v is None and wk: v = wk
        vals[r['key']] = v
        if wk: wk_by_pos.setdefault(r['pos'], []).append(wk)
    med = {p: float(np.median(v)) for p, v in wk_by_pos.items()}
    for r in state.rows:
        if vals.get(r['key']) is None:                     # on bye this week or unpriced: positional median
            vals[r['key']] = med.get(r['pos'], 0.0) * 0.8
    return vals

def _optimal(rows, vals, cfg, zero=frozenset()):
    R = [r for r in rows if r['slot'] != 'IR' and r['designation'] not in UNUSABLE]
    if not R: return 0.0
    slots = cfg.slots
    Cm = np.full((len(R), len(slots)), 1e6)
    for i, r in enumerate(R):
        v = 0.0 if r['tm'] in zero else (vals.get(r['key']) or 0.0)
        for j, s in enumerate(slots):
            if r['elig'] & cfg.accepts[s]: Cm[i, j] = -v
    ri, ci = linear_sum_assignment(Cm)
    return float(sum(-Cm[i, j] for i, j in zip(ri, ci) if Cm[i, j] < 1e5))

def strengths(state, proj, week, season=None, windows=None):
    """{owner: {week: expected points}} for weeks `week`..14, byes zeroed per week."""
    cfg = ALL[state.league]
    vals = player_values(state, proj, season)
    windows = windows or WN.Windows()
    out = {}
    for owner, rows in state.by_owner.items():
        out[owner] = {}
        for w in range(week, REG_SEASON_END + 1):
            byes = frozenset(windows.byes(w)) if windows.have(w) else frozenset()
            out[owner][w] = _optimal(rows, vals, cfg, zero=byes)
    return out

def simulate(state, strengths_, week, opp=None, seed=11, boost=0.0, n=N):
    """-> dict(p=P(playoffs) per owner, mine, p_win, p_loss, leverage, wins_now, n)"""
    lg = state.league; cfg = ALL[lg]
    owners = sorted(strengths_); T = len(owners); idx = {o: i for i, o in enumerate(owners)}
    me = idx[state.me]
    rng = np.random.default_rng(seed)
    W0 = np.zeros(T); PF0 = np.zeros(T)
    for o, i in idx.items():
        w, l, t, pf = _record((state.records or {}).get(o, {}).get('record', ''))
        W0[i] = w + 0.5 * t; PF0[i] = pf
    weeks = list(range(week, REG_SEASON_END + 1))
    mean = np.array([[strengths_[o][w] for w in weeks] for o in owners])          # T x K
    mean[me] += boost
    sd = np.maximum(mean * CV.get(lg, 0.12), 1.0)
    wins = np.tile(W0, (n, 1)); pf = np.tile(PF0, (n, 1))
    my_first = None
    for k, w in enumerate(weeks):
        S = rng.normal(mean[:, k], sd[:, k], size=(n, T))
        pf += S
        # head-to-head: known opponent this week for me, random perfect matching otherwise
        perm = np.argsort(rng.random((n, T)), axis=1)
        if k == 0 and opp in idx:
            # force me and opp adjacent in the pairing
            for s_ in range(n):
                p = perm[s_]; a = np.where(p == me)[0][0]; b = np.where(p == idx[opp])[0][0]
                partner = a ^ 1
                p[b], p[partner] = p[partner], p[b]
        a, b = perm[:, 0::2], perm[:, 1::2]
        sa = np.take_along_axis(S, a, 1); sb = np.take_along_axis(S, b, 1)
        wa = (sa > sb).astype(float) + 0.5 * (sa == sb); wb = 1.0 - wa
        np.put_along_axis(wins, a, np.take_along_axis(wins, a, 1) + wa, 1)
        np.put_along_axis(wins, b, np.take_along_axis(wins, b, 1) + wb, 1)
        if k == 0:
            mine_a = (a == me); mine_b = (b == me)
            my_first = np.full(n, 0.5)
            my_first[mine_a.any(1)] = wa[mine_a]
            my_first[mine_b.any(1)] = wb[mine_b]
        if getattr(cfg, 'vs_median', False):
            med = np.median(S, axis=1, keepdims=True)
            wins += (S > med).astype(float) + 0.5 * (S == med)
    # standings: wins, then points for
    order = np.lexsort((-pf, -wins), axis=1)
    rank = np.empty_like(order)
    np.put_along_axis(rank, order, np.tile(np.arange(T), (n, 1)), 1)
    made = rank < cfg.playoff_teams
    top = rank < max(1, cfg.playoff_teams // 2)          # the top half of the bracket: the seed worth having
    p = {o: float(made[:, i].mean()) for o, i in idx.items()}
    p_top = {o: float(top[:, i].mean()) for o, i in idx.items()}
    res = dict(p=p, mine=p[state.me], p_top=p_top, mine_top=p_top[state.me], top_k=max(1, cfg.playoff_teams // 2), n=n, weeks=weeks, playoff_teams=cfg.playoff_teams,
               wins_now={o: float(W0[i]) for o, i in idx.items()}, pf_now={o: float(PF0[i]) for o, i in idx.items()},
               strength={o: float(mean[i, 0]) for o, i in idx.items()})
    if my_first is not None:
        won = my_first >= 1.0; lost = my_first <= 0.0
        res['p_win'] = float(made[won, me].mean()) if won.any() else None
        res['p_loss'] = float(made[lost, me].mean()) if lost.any() else None
        res['leverage'] = (res['p_win'] - res['p_loss']) if res['p_win'] is not None and res['p_loss'] is not None else None
        res['top_win'] = float(top[won, me].mean()) if won.any() else None
        res['top_loss'] = float(top[lost, me].mean()) if lost.any() else None
        res['top_leverage'] = (res['top_win'] - res['top_loss']) if res['top_win'] is not None and res['top_loss'] is not None else None
    return res

def evaluate(state, proj, week, opp=None, season=None, windows=None):
    S_ = strengths(state, proj, week, season, windows)
    base = simulate(state, S_, week, opp=opp)
    up = simulate(state, S_, week, opp=opp, boost=5.0)
    base['p_plus5'] = up['mine']; base['top_plus5'] = up['mine_top']
    base['strengths'] = S_
    race = sorted(base['p'].items(), key=lambda kv: -kv[1])
    base['race'] = [dict(owner=o, p=p, p_top=base['p_top'][o], wins=base['wins_now'][o], pf=base['pf_now'][o], strength=base['strength'][o]) for o, p in race]
    base['note'] = (f"{base['n']} seasons from week {week} through {REG_SEASON_END}; {base['playoff_teams']} of {len(base['p'])} qualify. "
                    "Opponents after this week are drawn at random (the league schedule is not on file)"
                    + ("; BSB divisions are not modelled; the vs-median result is" if getattr(ALL[state.league], 'vs_median', False) else '')
                    + ". Strength = each roster's optimal lineup on individual per-week values, byes zeroed by week.")
    return base

def fmt(res, league):
    g = 'next week\'s game (opponent not on file)' if res.get('over') else 'this game'
    L = [f"PLAYOFF LEVERAGE — {league}: P(playoffs) {res['mine']:.0%}"
         + (f" · win {res['p_win']:.0%} / lose {res['p_loss']:.0%} → {g} is worth {res['leverage']:+.0%}" if res.get('leverage') is not None else '')
         + f" · +5 pts/week of roster strength → {res['p_plus5']:.0%}"]
    L.append(f"  top-{res['top_k']} seed: {res['mine_top']:.0%}" + (f" · win {res['top_win']:.0%} / lose {res['top_loss']:.0%} → {res['top_leverage']:+.0%}" if res.get('top_leverage') is not None else '') + f" · +5/wk → {res['top_plus5']:.0%}")
    L.append('  ' + res['note'])
    L.append(f"  {'playoffs':>8} {'top-'+str(res['top_k']):>6}  team                        wins    PF     strength")
    for r in res['race']:
        L.append(f"  {r['p']:8.0%} {r['p_top']:6.0%}  {r['owner'][:26]:26} {r['wins']:4.1f}  {r['pf']:7.1f}  {r['strength']:6.1f}/wk")
    return '\n'.join(L)
