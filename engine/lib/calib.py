"""CALIBRATION — how far each source's number lands from the actual, by position.

Every run logs, for every rostered player in each league, the pregame number
each source gives him under the league's own scoring:

  engine   the blended line the card uses (Kalshi/props over Sleeper)
  sleeper  the Sleeper-only line (no market override)
  yahoo    Yahoo's own projection off the matchup page (when on file)

data/proj_log/{LG}_wk{W}.csv, one row per player. A row locks at his kickoff so
the number scored is the last PREGAME one, never a post-hoc one. When Yahoo's
actuals for the week land (final rows in data/actuals/, exact league scoring —
only the two rosters on the matchup page, which is the honest limit of the
sample), the report joins them and gives n, mean absolute error and bias per
source and position, cumulative over the season.

What it is for: the blend stays market-first by doctrine, but a source that is
measurably worse at a position (a fitted ladder at TE, say) should lose its
override there once the sample says so. Until three weeks are in, this is a
report, not a weight.

The report (rebuilt 10-04) compares PAIRED samples only — rows where every source
compared has a pregame number — with MAE, RMSE and bias per pair, league and
position, a game-clustered bootstrap CI on each MAE difference, the subset where the
market changed the number (a Kalshi field and |engine - sleeper| >= 1), Kalshi's
P(anytime TD) reliability, and P(win) reliability once four league-weeks are on
record. A row counts as pregame only if it was first seen AND last written before
kickoff; week 3 (logged after kickoff before the 10-04 fix) comes from the git
back-fill (calib_backfill.py -> {LG}_wk3.backfill.csv). HH week 2 is back-filled
from the engine's saved week-2 projections: engine numbers only, so it is never in a
paired comparison — it prints on its own 'engine-only' line. Week 2 cannot be
back-filled from git: the pump's first commit is 09-23.
"""
from . import paths as _paths
import csv, os, json
from collections import defaultdict
from . import score as SC, clock as C, actuals as AC, ts as T
from .names import key, team

D = _paths.data('proj_log', '')
FIELDS = ['key', 'player', 'owner', 'pos', 'tm', 'slot', 'engine', 'sleeper', 'yahoo', 'kalshi_fields', 'kick', 'locked', 'post', 'logged']

def _read(p):
    return {r['key']: r for r in csv.DictReader(open(p))} if os.path.exists(p) else {}

def log(state, proj, week):
    """Merge this run's pregame numbers into the week's log; rows past kickoff stay as they were."""
    os.makedirs(D, exist_ok=True)
    p = D + f'{state.league}_wk{week}.csv'
    old = _read(p)
    now = C.now(); out = {}
    for r in state.rows:
        if r['slot'] == 'IR': continue
        prev = old.get(r['key'])
        kick = proj.kickoff(r['tm'])
        if prev and prev.get('locked') == '1':
            out[r['key']] = prev; continue
        # the first run AFTER his kickoff must freeze the previous (pregame) row, not
        # recompute: by then the live guard has stripped his ladders and the row would
        # lock in a Sleeper-only number (10-04: all 120 BSB 1 pm rows were post-kick)
        if prev and kick and kick <= now:
            out[r['key']] = dict(prev, locked='1'); continue
        L = proj.line(r['key'], r['pos'], r['tm'])
        Ls = proj.line(r['key'], r['pos'], r['tm'], market=False)
        eng = SC.points(L, state.league) if not L.get('unknown') else None
        slp = SC.points(Ls, state.league) if not Ls.get('unknown') and 'sleeper' in Ls['sources'] else None
        yh = (proj.yahoo.get(r['key']) or {}).get(state.league)
        kf = ','.join(f for f in ('rec', 'rec_yd', 'rush_yd', 'pass_yd', 'pass_td', 'td') if f in (L.get('prov') or {}))
        locked = bool(kick and kick <= now)
        # first seen after his kickoff: not a pregame number, never scored
        post = '1' if (locked and not prev) else (prev.get('post', '0') if prev else '0')
        out[r['key']] = dict(key=r['key'], player=r['player'], owner=r['owner'], pos=r['pos'], tm=r['tm'], slot=r['slot'],
                             engine='' if eng is None else f'{eng:.2f}', sleeper='' if slp is None else f'{slp:.2f}',
                             yahoo='' if yh is None else f'{yh:.2f}', kalshi_fields=kf,
                             kick=C.iso(kick) if kick else '', locked='1' if locked else '0', post=post, logged=C.iso())
    for k, r in old.items():                      # players who left the league keep their row
        out.setdefault(k, r)
    with open(p, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader(); w.writerows(out.values())
    return p, len(out)

def _backfill_hh_wk2(root=None):
    """Engine-only rows for HH week 2 from the saved projection json (before the log existed).
    ENGINE-ONLY: it has no Sleeper or Yahoo number, so it is never part of a paired
    comparison; report() prints it on its own 'engine-only' line."""
    p = os.path.join(root or _paths.root(), 'data', 'hh_proj_wk2.json')
    if not os.path.exists(p): return {}
    j = json.load(open(p))
    return {k: dict(key=k, player=v.get('name', k), pos=v.get('pos', ''), engine=v.get('pts'), sleeper=None, yahoo=None) for k, v in j.items()}

SOURCES = ('engine', 'sleeper', 'yahoo')
PAIRS = (('engine', 'sleeper'), ('engine', 'yahoo'), ('sleeper', 'yahoo'))
BOOT = 2000

def _pregame(r):
    """A row is a pregame number only if it was first seen before kickoff AND last
    written before kickoff. Before 10-04 a row locked by the first run AFTER kickoff,
    recomputed with the ladders already stripped by the live guard: week 3 has 222 of
    227 BSB rows logged after their kickoff. Those rows are not scored."""
    if r.get('post') == '1': return False
    lgd, kk = T.try_ts(r.get('logged'), 'legacy') if r.get('logged') else None, T.try_ts(r.get('kick'), 'legacy') if r.get('kick') else None
    if lgd is not None and kk is not None and lgd >= kk: return False
    return True

def load_log(lg, w, root=None):
    """The week's pregame rows: the live log's pregame rows, else the git backfill's row
    for that player (data/proj_log/{LG}_wk{W}.backfill.csv, written by calib_backfill.py).
    -> {key: row with 'origin' in live|backfill}"""
    d = os.path.join(root, 'data', 'proj_log') + '/' if root else D
    out = {}
    bp = d + f'{lg}_wk{w}.backfill.csv'
    if os.path.exists(bp):
        for r in csv.DictReader(open(bp)): out[r['key']] = dict(r, origin='backfill')
    lp = d + f'{lg}_wk{w}.csv'
    if os.path.exists(lp):
        for r in csv.DictReader(open(lp)):
            if _pregame(r): out[r['key']] = dict(r, origin='live')
    return out

def _opp_map(w, root=None):
    """team -> opponent for week w (Sleeper's projection file carries 'opp') -> game clusters."""
    p = os.path.join(root or _paths.root(), 'data', f'sleeper_off_wk{w}.csv')
    m = {}
    if os.path.exists(p):
        for r in csv.DictReader(open(p)):
            if r.get('team') and r.get('opp'): m[team(r['team'])] = team(r['opp'])
    return m

def samples(week, root=None, now=None):
    """Every scored player-week: one dict per (league, week, player) with each source's
    pregame number, the actual (Yahoo exact where printed, else his Sleeper stat line
    scored by lib/score.actual), the game it belongs to, and whether the market changed
    the number. Weeks whose games are not all final are skipped."""
    from . import outcomes as OUT
    A = OUT.Actuals(root, now)
    out, eng_only = [], []
    for w in range(1, week + 1):
        if not OUT.week_complete(w, root, now):
            continue
        om = _opp_map(w, root)
        for lg in ('BSB', 'HH'):
            plog = load_log(lg, w, root)
            if not plog and lg == 'HH' and w == 2:
                for k, r in _backfill_hh_wk2(root).items():
                    a, src = A.pts(lg, w, k, r.get('pos'))
                    if a is None or r.get('engine') in (None, ''): continue
                    eng_only.append(dict(league=lg, week=w, key=k, pos=_fam(r.get('pos')), engine=float(r['engine']), actual=a, asrc=src))
                continue
            for k, r in plog.items():
                a, src = A.pts(lg, w, k, r.get('pos'))
                if a is None: continue
                vals = {s_: (float(r[s_]) if r.get(s_) not in (None, '') else None) for s_ in SOURCES}
                tm = team(r.get('tm') or '')
                g = f'{w}:' + '-'.join(sorted([tm, om.get(tm, '?')]))
                mkt = bool(r.get('kalshi_fields')) and vals['engine'] is not None and vals['sleeper'] is not None and abs(vals['engine'] - vals['sleeper']) >= 1.0
                out.append(dict(league=lg, week=w, key=k, player=r.get('player'), pos=_fam(r.get('pos')), game=g, actual=a, asrc=src,
                                market=mkt, origin=r.get('origin'), **vals))
    return out, eng_only

def _stats(errs):
    n = len(errs)
    if not n: return None
    return dict(n=n, mae=sum(abs(e) for e in errs) / n, rmse=(sum(e * e for e in errs) / n) ** 0.5, bias=sum(errs) / n)

def _boot_diff(S, a, b, reps=BOOT, seed=11):
    """Bootstrap by GAME: resample games with replacement, MAE(a) - MAE(b) on the paired
    rows. -> (diff, lo95, hi95, n_games)"""
    import random
    by = defaultdict(list)
    for x in S: by[x['game']].append((abs(x[a] - x['actual']), abs(x[b] - x['actual'])))
    games = list(by)
    if len(games) < 2: return None
    rng = random.Random(seed)
    def diff(gs):
        ea = eb = n = 0.0
        for g in gs:
            for u, v in by[g]: ea += u; eb += v; n += 1
        return (ea - eb) / n if n else 0.0
    d0 = diff(games)
    ds = sorted(diff([rng.choice(games) for _ in games]) for _ in range(reps))
    return dict(diff=d0, lo=ds[int(0.025 * reps)], hi=ds[int(0.975 * reps) - 1], games=len(games))

def report(week, root=None, now=None):
    """PAIRED calibration. Every comparison uses only the rows where ALL the sources it
    compares exist (a source is never credited for the players it happens to cover).
    -> dict(rows (per league x pos x source, on the three-way paired set — the card's
    table), pairs (each source pair: n, MAE/RMSE/bias each side, game-bootstrap CI of the
    MAE difference), market (the subset where Kalshi changed the engine number by >= 1),
    by_pos, engine_only (HH wk2 back-fill, never paired), td (P(anytime TD) reliability),
    pwin (P(win) reliability, >= 4 weeks), weeks, n_total, note)"""
    S, E = samples(week, root, now)
    rows = []
    tri = [x for x in S if all(x[s_] is not None for s_ in SOURCES)]
    for lg in ('BSB', 'HH'):
        for pos in sorted({x['pos'] for x in tri if x['league'] == lg}) + ['ALL']:
            sub = [x for x in tri if x['league'] == lg and (pos == 'ALL' or x['pos'] == pos)]
            for s_ in SOURCES:
                st = _stats([x[s_] - x['actual'] for x in sub])
                if st: rows.append(dict(league=lg, pos=pos, source=s_, **st))
    pairs = []
    for a, b in PAIRS:
        P_ = [x for x in S if x[a] is not None and x[b] is not None]
        for lg in ('BSB', 'HH', 'ALL'):
            sub = [x for x in P_ if lg == 'ALL' or x['league'] == lg]
            if not sub: continue
            sa, sb = _stats([x[a] - x['actual'] for x in sub]), _stats([x[b] - x['actual'] for x in sub])
            pairs.append(dict(a=a, b=b, league=lg, n=len(sub), sa=sa, sb=sb, ci=_boot_diff(sub, a, b)))
    by_pos = []
    P_es = [x for x in S if x['engine'] is not None and x['sleeper'] is not None]
    for pos in sorted({x['pos'] for x in P_es}):
        sub = [x for x in P_es if x['pos'] == pos]
        by_pos.append(dict(pos=pos, n=len(sub), engine=_stats([x['engine'] - x['actual'] for x in sub]),
                           sleeper=_stats([x['sleeper'] - x['actual'] for x in sub]), ci=_boot_diff(sub, 'engine', 'sleeper')))
    M = [x for x in P_es if x['market']]
    market = dict(n=len(M), engine=_stats([x['engine'] - x['actual'] for x in M]), sleeper=_stats([x['sleeper'] - x['actual'] for x in M]),
                  ci=_boot_diff(M, 'engine', 'sleeper'),
                  yahoo_paired=(lambda Y: dict(n=len(Y), engine=_stats([x['engine'] - x['actual'] for x in Y]), yahoo=_stats([x['yahoo'] - x['actual'] for x in Y]),
                                               ci=_boot_diff(Y, 'engine', 'yahoo')))([x for x in M if x['yahoo'] is not None]))
    eo = dict(n=len(E), engine=_stats([x['engine'] - x['actual'] for x in E]), weeks=sorted({(x['league'], x['week']) for x in E}))
    weeks = sorted({(x['league'], x['week']) for x in S})
    try: td = td_reliability(week, root, now)
    except Exception as e: td = dict(error=repr(e))
    try: pw = pwin_reliability(root, now=now)
    except Exception as e: pw = dict(error=repr(e))
    asrc = defaultdict(int)
    for x in S: asrc[x['asrc']] += 1
    note = ('Paired only: each comparison uses the rows where every source compared has a pregame number. '
            'Pregame = first seen AND last written before kickoff (rows the pre-10-04 log locked after kickoff are excluded; '
            'week 3 comes from the git back-fill where it exists). Actuals: Yahoo exact where printed, else the Sleeper stat line '
            'scored in league rules (BSB exact; HH within ~1 pt offense, ~3 DEF — see the fidelity table); IDP only where Yahoo printed it. '
            'CIs bootstrap whole games. Under three weeks, a report, not a weight.')
    return dict(rows=rows, pairs=pairs, by_pos=by_pos, market=market, engine_only=eo, td=td, pwin=pw, weeks=weeks,
                n_total=len(tri), n_samples=len(S), actual_src=dict(asrc), note=note,
                origins=dict(sorted(_count((x['league'], x['week'], x['origin']) for x in S).items())))

def _count(it):
    d = defaultdict(int)
    for x in it: d[x] += 1
    return {f'{k[0]} wk{k[1]} {k[2]}': v for k, v in d.items()}

# ------------------------------------------------------------------ P(anytime TD) reliability
TD_BINS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 1.01)

def _archive_dir(root=None):
    from . import outcomes as OUT
    for d in (os.path.join(root or _paths.root(), 'data', 'kalshi_archive'), os.path.join(OUT.FFDATA, 'data', 'archive')):
        if os.path.isdir(d) and os.listdir(d): return d
    return None

def td_prices(week, root=None):
    """Kalshi 'Name: 1+ touchdowns' (KXNFLTD) price at the LAST archived pull before each
    game's kickoff. Price = mid of bid/ask when both quote, else last trade.
    -> {(key, team_code_pair): dict(p, pull, event)}"""
    from . import clock as _C
    import datetime as _dt
    d = _archive_dir(root)
    if not d: return {}
    w0, w1 = _C.week_start(week), _C.week_start(week + 1)
    pulls = []
    for f in sorted(os.listdir(d)):
        if not f.startswith('kalshi_'): continue
        t = T.try_ts(f[7:-4], 'pump')
        if t is None or t < w0 - _dt.timedelta(days=2) or t >= w1: continue
        pulls.append((t, os.path.join(d, f)))
    best = {}
    for t, f in pulls:
        for r in csv.DictReader(open(f)):
            if r.get('series') != 'KXNFLTD' or ':' not in r.get('title', ''): continue
            nm, rest = r['title'].split(':', 1)
            if not rest.strip().startswith('1+'): continue
            try: ev_d = T.kalshi_event_date(r['event'])
            except Exception: continue
            if not (w0 <= ev_d + _dt.timedelta(hours=12) < w1 + _dt.timedelta(hours=12)): continue
            close_ok = True
            k = (key(nm.strip()), r['event'])
            try:
                b, a_, l_ = float(r['yes_bid'] or 0), float(r['yes_ask'] or 0), float(r['last_price'] or 0)
            except ValueError: continue
            p = (b + a_) / 2 if b > 0 and 0 < a_ < 1 and a_ - b <= 0.10 else l_
            best.setdefault(k, []).append((t, p))
    return best

def td_reliability(week, root=None, now=None):
    """Calibration of Kalshi's P(anytime TD): price at the last pull before kickoff vs
    whether he scored a rushing or receiving TD (Sleeper stat line). Bins of 10 points.
    -> dict(rows=[{lo, hi, n, p_mean, hit}], n, brier, weeks)"""
    from . import outcomes as OUT
    import datetime as _dt
    out_rows = defaultdict(list); weeks = []
    for w in range(1, week + 1):
        if not OUT.week_complete(w, root, now): continue
        st = OUT.sleeper_stats(w, root)
        if not st: continue
        prices = td_prices(w, root)
        if not prices: continue
        kick = {}
        for lg in ('BSB', 'HH'):
            p = os.path.join(root or _paths.root(), 'data', 'proj_log', f'{lg}_wk{w}.csv')
            if os.path.exists(p):
                for r in csv.DictReader(open(p)):
                    if r.get('kick'): kick[team(r['tm'])] = T.try_ts(r['kick'], 'legacy')
        used = 0
        for (k, ev), pts in prices.items():
            s = st.get(k)
            if s is None: continue
            tm = team(s[0]['team']); kk = kick.get(tm)
            if kk is None: continue
            pre = [p for t, p in pts if t < kk]
            if not pre: continue
            p = pre[-1]
            scored = (float(s[0].get('rush_td') or 0) + float(s[0].get('rec_td') or 0)) > 0
            out_rows[min(i for i in range(len(TD_BINS) - 1) if TD_BINS[i] <= p < TD_BINS[i + 1])].append((p, scored))
            used += 1
        if used: weeks.append(w)
    rows, allp = [], []
    for i in sorted(out_rows):
        L = out_rows[i]; allp += L
        rows.append(dict(lo=TD_BINS[i], hi=min(TD_BINS[i + 1], 1.0), n=len(L), p_mean=sum(p for p, _ in L) / len(L), hit=sum(1 for _, h in L if h) / len(L)))
    brier = sum((p - (1 if h else 0)) ** 2 for p, h in allp) / len(allp) if allp else None
    return dict(rows=rows, n=len(allp), brier=brier, weeks=weeks,
                note='players with no stat row (inactive) are not scored — a priced player who sat is a voided market on Kalshi too')

def pwin_reliability(root=None, min_weeks=4, now=None):
    """P(beat opponent) at lock (data/outcomes/pwin.jsonl) vs the result. Printed once
    at least `min_weeks` league-weeks are on record; before that, the count."""
    from . import outcomes as OUT
    rows = []
    for r in OUT.read('pwin', root):
        y = OUT.yahoo_actuals(r['league'], r['nfl_week'], root)
        from .leagues import ALL
        me = ALL[r['league']].name
        mine = sum(x['pts'] for x in y.values() if x['owner'] == me and x['slot'] not in ('BN', 'IR'))
        opp = sum(x['pts'] for x in y.values() if x['owner'] == r.get('opp') and x['slot'] not in ('BN', 'IR'))
        if not OUT.week_complete(r['nfl_week'], root, now) or not y or r.get('p_opp') is None: continue
        rows.append(dict(league=r['league'], week=r['nfl_week'], p=r['p_opp'], won=mine > opp))
    if len(rows) < min_weeks:
        return dict(n=len(rows), ready=False, note=f'{len(rows)} league-week(s) with P(win) at lock and a final — reliability prints at {min_weeks}')
    bins = defaultdict(list)
    for x in rows: bins[min(int(x['p'] * 5), 4)].append(x)
    return dict(n=len(rows), ready=True, brier=sum((x['p'] - x['won']) ** 2 for x in rows) / len(rows),
                rows=[dict(lo=i / 5, hi=(i + 1) / 5, n=len(L), p_mean=sum(x['p'] for x in L) / len(L), won=sum(x['won'] for x in L) / len(L)) for i, L in sorted(bins.items())])

def _fam(pos):
    p = (pos or '').split(',')[0].strip().upper()
    return {'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB'}.get(p, p)

def fmt(rep):
    L = ['CALIBRATION — paired pregame numbers vs actuals (league scoring)']
    if not rep or not rep.get('n_samples'):
        L.append('  no completed week with pregame numbers yet'); return '\n'.join(L)
    L.append('  weeks: ' + ', '.join(f'{lg} wk{w}' for lg, w in rep['weeks']) + f" · {rep['n_samples']} scored player-weeks · actuals {rep['actual_src']}")
    L.append('  origin of the pregame rows: ' + ', '.join(f'{k} {v}' for k, v in rep.get('origins', {}).items()))
    L.append(f"  {'pair':16} {'lg':4} {'n':>4}  {'MAE a':>6} {'MAE b':>6}  {'RMSE a':>6} {'RMSE b':>6}  {'bias a':>6} {'bias b':>6}   MAE a-b [95% CI by game]")
    for p in rep['pairs']:
        ci = p['ci']
        L.append(f"  {p['a'] + ' v ' + p['b']:16} {p['league']:4} {p['n']:4d}  {p['sa']['mae']:6.2f} {p['sb']['mae']:6.2f}  {p['sa']['rmse']:6.2f} {p['sb']['rmse']:6.2f}  {p['sa']['bias']:+6.2f} {p['sb']['bias']:+6.2f}   "
                 + (f"{ci['diff']:+.2f} [{ci['lo']:+.2f}, {ci['hi']:+.2f}] ({ci['games']} games)" if ci else 'n/a'))
    L.append('  engine v sleeper by position:')
    for b in rep['by_pos']:
        ci = b['ci']
        L.append(f"    {b['pos']:4} n={b['n']:4d}  MAE {b['engine']['mae']:5.2f} v {b['sleeper']['mae']:5.2f}  bias {b['engine']['bias']:+5.2f} v {b['sleeper']['bias']:+5.2f}  "
                 + (f"diff {ci['diff']:+.2f} [{ci['lo']:+.2f}, {ci['hi']:+.2f}]" if ci else ''))
    m = rep['market']
    if m['n']:
        ci = m['ci']
        L.append(f"  where the market changed the number (Kalshi field, |engine - sleeper| >= 1): n={m['n']}  MAE engine {m['engine']['mae']:.2f} v sleeper {m['sleeper']['mae']:.2f}"
                 + (f"  diff {ci['diff']:+.2f} [{ci['lo']:+.2f}, {ci['hi']:+.2f}] ({ci['games']} games)" if ci else ''))
        y = m.get('yahoo_paired') or {}
        if y.get('n'):
            ci = y['ci']
            L.append(f"    same subset with a Yahoo number: n={y['n']}  MAE engine {y['engine']['mae']:.2f} v yahoo {y['yahoo']['mae']:.2f}" + (f"  diff {ci['diff']:+.2f} [{ci['lo']:+.2f}, {ci['hi']:+.2f}]" if ci else ''))
    else:
        L.append('  where the market changed the number: no paired pregame rows yet')
    eo = rep['engine_only']
    if eo['n']: L.append(f"  engine-only (HH wk2 back-fill, not paired, not compared): n={eo['n']} MAE {eo['engine']['mae']:.2f} bias {eo['engine']['bias']:+.2f}")
    td = rep.get('td') or {}
    if td.get('n'):
        L.append(f"  Kalshi P(anytime TD) reliability (weeks {td['weeks']}, n={td['n']}, Brier {td['brier']:.3f}):")
        for r in td['rows']: L.append(f"    {r['lo']:.0%}-{r['hi']:.0%}: n={r['n']:4d}  priced {r['p_mean']:.1%}  scored {r['hit']:.1%}")
    pw = rep.get('pwin') or {}
    L.append('  P(win) reliability: ' + (pw.get('note') or (f"n={pw['n']} Brier {pw['brier']:.3f} " + '; '.join(f"{r['lo']:.0%}-{r['hi']:.0%}: n={r['n']} said {r['p_mean']:.0%} won {r['won']:.0%}" for r in pw['rows']))))
    return '\n'.join(L)
