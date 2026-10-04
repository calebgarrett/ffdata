"""WIN PROBABILITY — the lineup that wins, not the lineup that projects highest.

Caleb (09-17): everyone in these leagues is savvy; get one to three steps
ahead in finding value in the lineup. The step everyone else has not taken:
they optimise the projected mean. But a Kalshi ladder is a full distribution,
BSB scores TWO results a week (head-to-head and vs the league median), and a
lineup's job is to win those, not to maximise a mean. The mean-optimal lineup
and the win-optimal lineup differ exactly in the WR3/flex noise band, where the
solver currently shrugs: behind, take the boom; ahead, take the floor.

Method, stated plainly:
  * every rostered player in the league is sampled N times for the week. A stat
    with a Kalshi ladder is sampled FROM THE LADDER (inverse CDF through the
    posted strike probabilities; nothing fitted, nothing assumed). A stat with
    no ladder is sampled around the Sleeper mean: Poisson for counts and TDs,
    gamma with CV 0.55 for yardage (a stated assumption, flagged per player).
    DEF and K are sampled around their mean with a stated spread.
  * points are the league's own scorer at the mean, plus the scorer's linear
    coefficient on each sampled stat's deviation (exact for BSB, which is
    linear; within a point for HH).
  * every other team's CURRENT starters are summed the same way. The median is
    the median of all 12 team totals in each sample, mine included.
  * my current lineup, the mean-optimal lineup, and every legal one-for-one
    bench swap are scored on P(beat opponent) and P(beat median).

Same-game correlation (09-26): every skill player's sample is scaled by a shared
GAME factor (1 + 0.15 z, both offences in the game: pace, a shootout) and a
shared TEAM factor (1 + 0.25 z, one offence's day), the idiosyncratic part
shrunk 4% so each player's spread is preserved. That gives teammates a
correlation of roughly 0.25-0.35 (QB with his WR1 the highest) and opposing
offences about 0.1, in line with what the box scores show. DEF, K and IDP are
left independent — a stated gap, smaller than the one this closes.
"""
from . import paths as _paths
import json, os
import numpy as np
from . import score as SC
from .state import UNUSABLE

N = 6000
SG, ST, SHRINK = 0.15, 0.25, 0.96     # game factor sd, team factor sd, idiosyncratic shrink
CORR_POS = {'QB', 'RB', 'WR', 'TE'}
CV_YARDS = 0.55
SERIES = {'rec': 'KXNFLREC', 'rec_yd': 'KXNFLRECYDS', 'rush_yd': 'KXNFLRSHYDS',
          'pass_yd': 'KXNFLPASSYDS', 'pass_td': 'KXNFLPASSTDS'}
COEF = {'BSB': dict(rec=1.0, rec_yd=0.1, rush_yd=0.1, pass_yd=0.05, pass_td=6.0, rush_td=6.0, rec_td=6.0),
        'HH':  dict(rec=0.9, rec_yd=1/12, rush_yd=1/20, pass_yd=1/50, pass_td=5.0, rush_td=5.0, rec_td=5.0)}
COUNTS = ('rec', 'pass_td', 'rush_td', 'rec_td')
MATCHUPS = _paths.data('matchups.json')

def _sample_ladder(f, field, n, rng):
    lad = sorted(f['ladder'])                     # [(strike, P(X>=strike)), ...]
    u = rng.random(n)
    if field in COUNTS:
        # X = number of strikes k with P(X>=k) > 1-u  (integer inverse CDF)
        ps = np.array([p for _, p in lad]); ks = np.array([s for s, _ in lad])
        out = np.zeros(n)
        for k, p in zip(ks, ps): out = np.where(p > 1 - u, k, out)
        # a count ladder is posted from strike 1 or 2 up to ~8: the tail above the
        # top strike is invisible, so the sampled mean runs a few percent under
        # the fitted one. Hold the shape, pin the mean (same rule as yards).
        m = float(out.mean())
        if m > 0 and f.get('mean'): out = out * (float(f['mean']) / m)
        return out
    xs = [0.0] + [s for s, _ in lad]
    Fs = [0.0] + [1 - p for _, p in lad]
    gap = (lad[-1][0] - lad[-2][0]) if len(lad) > 1 else lad[-1][0] / 2
    xs.append(lad[-1][0] + 2 * gap); Fs.append(1.0)
    Fs = np.maximum.accumulate(np.array(Fs))       # monotone
    x = np.interp(u, Fs, np.array(xs))
    # a ladder that was posted (or read) without its low strikes leaves the
    # bottom of the distribution to interpolation. The fitted mean is the
    # market's own centre, so hold the ladder's SHAPE and pin its mean to the
    # fit (Likely 09-20: strikes 40-90 only; a full ladder moves <2%).
    m = float(x.mean())
    if m > 0 and f.get('mean'): x = x * (float(f['mean']) / m)
    return x

def _sample_field(proj, k, field, mean, n, rng):
    """-> (samples, 'ladder'|'assumed')"""
    f = proj.kal.get((k, SERIES[field])) if field in SERIES else None
    if f and f.get('ladder') and f['sse'] < 0.05 and len(f['ladder']) >= 3:
        return _sample_ladder(f, field, n, rng), 'ladder'
    if mean <= 0: return np.zeros(n), 'assumed'
    if field in COUNTS: return rng.poisson(mean, n).astype(float), 'assumed'
    shape = 1 / CV_YARDS ** 2
    return rng.gamma(shape, mean / shape, n), 'assumed'

def sample_player(proj, row, league, n, rng):
    """-> (array of weekly points, provenance string) or (None, why)"""
    L = row.get('line') or proj.line(row['key'], row['pos'], row['tm'])
    if L.get('unknown'): return None, 'no source'
    mean = SC.points(L, league)
    if mean is None: return None, 'unscored'
    fam, st = L['fam'], L['stat']
    if L.get('pts_override') is not None:
        return rng.gamma(4.0, max(mean, 0.1) / 4.0, n), 'assumed yahoo cv.5'
    if fam == 'DEF': return np.clip(rng.normal(mean, 6.0 if league == 'BSB' else 9.0, n), -10, 45), 'assumed sd'
    if fam == 'K': return rng.gamma(4.0, max(mean, 0.1) / 4.0, n), 'assumed cv.5'
    if fam in ('DL', 'LB', 'DB'): return rng.gamma(5.0, max(mean, 0.1) / 5.0, n), 'assumed cv.45'
    coef = COEF[league]
    tot = np.full(n, float(mean)); src = []
    for field, c in coef.items():
        m = float(st.get(field) or 0.0)
        if m <= 0 and field not in ('rec',): continue
        s, how = _sample_field(proj, row['key'], field, m, n, rng)
        tot += c * (s - m); src.append(f'{field}:{how[0]}')
    return tot, ' '.join(src)

def matchup(league, week):
    try: return json.load(open(MATCHUPS)).get(str(week), {}).get(league)
    except Exception: return None

def evaluate(state, proj, lineup, league, seed=7, actuals=None):
    """-> dict(opp, p_opp, p_med, mean, options=[...], teams={owner: mean}, notes)"""
    rng = np.random.default_rng(seed)
    cache, prov = {}, {}
    actuals = actuals or {}
    # shared game and team factors for same-game correlation
    game_of = {}
    for (a, h) in getattr(proj, 'games', {}) or {}:
        game_of[a] = (a, h); game_of[h] = (a, h)
    gz, tz = {}, {}
    def factor(tm):
        g = game_of.get(tm)
        if g not in gz: gz[g] = rng.normal(0.0, SG, N)
        if tm not in tz: tz[tm] = rng.normal(0.0, ST, N)
        return np.clip((1.0 + gz[g]) * (1.0 + tz[tm]), 0.1, None)
    def correlated(r, s):
        if s is None or r['pos'] not in CORR_POS: return s
        m = float(s.mean())
        return (m + (s - m) * SHRINK) * factor(r['tm'])
    def S(r):
        if r['key'] in actuals and r['key'] not in cache:
            a = actuals[r['key']]
            if a.get('final', True):
                cache[r['key']] = np.full(N, float(a['pts'])); prov[r['key']] = 'final:l'
            else:
                # in progress: the points so far are a fact; only the unplayed share
                # of the game is still a distribution
                s, why = sample_player(proj, r, league, N, rng)
                cache[r['key']] = float(a['pts']) + correlated(r, s) * (1.0 - a['frac']); prov[r['key']] = f'live:{a["frac"]:.2f}'
        if r['key'] not in cache:
            s, why = sample_player(proj, r, league, N, rng)
            cache[r['key']] = correlated(r, s); prov[r['key']] = why
        return cache[r['key']]
    # other teams: current starters
    totals, unpriced = {}, {}
    for owner, rows in state.by_owner.items():
        if owner == state.me: continue
        t = np.zeros(N); miss = []
        for r in rows:
            if r['slot'] in ('BN', 'IR') or r['designation'] in UNUSABLE: continue
            s = S(r)
            if s is not None: t += s
            else: miss.append(r['player'])
        totals[owner] = t; unpriced[owner] = miss
    opp = matchup(league, proj.week)
    vs_median = bool(getattr(state.cfg, 'vs_median', False))
    others = np.stack(list(totals.values()))     # (teams-1, N)

    def score(lu_rows, label):
        t = np.zeros(N); miss = []
        for r in lu_rows:
            s = S(r)
            if s is None: miss.append(r['player']); continue
            t += s
        out = dict(label=label, mean=float(t.mean()), sd=float(t.std()), miss=miss, players=[r['player'] for r in lu_rows])
        out['p_opp'] = float((t > totals[opp]).mean()) if opp in totals and totals[opp].mean() > 0 and not unpriced.get(opp) else None
        if vs_median and all(o.mean() > 0 for o in totals.values()):
            allt = np.vstack([others, t[None, :]])
            med = np.median(allt, axis=0)
            out['p_med'] = float((t > med).mean())
        else: out['p_med'] = None
        out['score'] = (out['p_opp'] or 0) + (out['p_med'] or 0)
        return out

    cur = [r for r in lineup['current'].values() if r]
    opt = [r for r in lineup['optimal'].values() if r]
    # a Q/D starter projected at 0.00 is a source assuming OUT (Cross 09-23). Replacing
    # him is a game-status contingency the card already names, not a win-probability
    # edge; such swaps are left out here so a 0 never masquerades as +14%.
    q_zero = {r['key'] for r in cur if r.get('designation') in ('Q', 'D') and not (r.get('pts') or 0)}
    options = [score(cur, 'current')]
    opt_keys = {r['key'] for r in opt}
    if not (q_zero - opt_keys): options.append(score(opt, 'mean-optimal'))
    # every legal one-for-one swap of a bench player into a starter's slot
    cfg = state.cfg
    bench = [r for r in lineup['rows'] if r['slot'] == 'BN' and r['designation'] not in UNUSABLE and r.get('pts') is not None
             and r['key'] not in actuals]
    for slot, s_row in lineup['current'].items():
        if not s_row or s_row['key'] in actuals or s_row['key'] in q_zero: continue
        for b in bench:
            if not (b['elig'] & cfg.accepts[slot]): continue
            rows = [b if (r is s_row) else r for r in cur]
            options.append(score(rows, f"{b['player']} for {s_row['player']} at {slot}"))
    base = options[0]
    for o in options: o['gain'] = o['score'] - base['score']
    best = max(options, key=lambda o: o['score'])
    notes = [f'same-game correlation modelled for QB/RB/WR/TE (game sd {SG:.2f}, team sd {ST:.2f}); DEF, K and IDP independent; treat a 2-3 point probability edge as noise']
    if q_zero: notes.append('not scored here: ' + ', '.join(r['player'] for r in cur if r['key'] in q_zero) + ' (Q/D, projected 0.00 — a game-status question, handled by the contingency flag, not a lineup edge)')
    if actuals: notes.append(f'{len(actuals)} finished players carry their actual score; other teams\' finished players still use projections in the median')
    if opp is None: notes.append(f'no opponent on file for week {proj.week} (data/matchups.json) — P(beat opponent) not computed')
    elif opp in totals and totals[opp].mean() <= 0: notes.append(f'{opp} has no priced players this week — P(beat opponent) not computed')
    elif unpriced.get(opp): notes.append(f'{opp} has {len(unpriced[opp])} starter(s) no source prices ({", ".join(unpriced[opp][:4])}{"…" if len(unpriced[opp]) > 4 else ""}) — P(beat opponent) not computed rather than overstated')
    if vs_median and sum(1 for t in totals.values() if t.mean() > 0) < len(totals): notes.append('some league rosters have no priced players this week — the median is not computed from a full field')
    assumed = sorted({k for k, v in prov.items() if v and ':l' not in v})
    return dict(opp=opp, vs_median=vs_median, current=base, best=best, options=sorted(options, key=lambda o: -o['score']),
                teams={o: float(t.mean()) for o, t in totals.items()}, notes=notes, n=N,
                assumed=len(assumed), priced=len([k for k, v in prov.items() if v and ':l' in v]),
                samples={r['key']: cache[r['key']] for r in cur if r['key'] in cache and cache[r['key']] is not None})

def fmt(res, league):
    c, b = res['current'], res['best']
    def pct(x): return f'{x:.0%}' if x is not None else 'n/a'
    L = [f"WIN PROBABILITY — {league} — vs {res['opp'] or '?'}" + (' and vs the league median' if res['vs_median'] else '') +
         f"  ({res['n']} samples; {res['priced']} players sampled from Kalshi ladders, {res['assumed']} from assumed spreads)"]
    L.append(f"  current lineup: {c['mean']:.1f} ± {c['sd']:.1f}   P(beat opp) {pct(c['p_opp'])}   P(beat median) {pct(c['p_med'])}")
    for o in res['options'][:6]:
        if o['label'] == 'current': continue
        L.append(f"  {o['label'][:44]:44} {o['mean']:6.1f}  opp {pct(o['p_opp'])}  med {pct(o['p_med'])}  Δ {o['gain']:+.3f}")
    if b['label'] != 'current' and b['gain'] >= 0.03:
        L.append(f"  -> {b['label']}: +{b['gain']:.1%} combined win probability over the current lineup")
    else:
        L.append('  -> current lineup is within noise of the best: no change')
    for n in res['notes']: L.append('  note: ' + n)
    return '\n'.join(L)
