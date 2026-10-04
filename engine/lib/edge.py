"""THE EDGE REPORT — Tuesday's answer to 'is any of this working?'

  (a) LINEUP   points left on the bench (actual starters vs the hindsight-optimal lineup);
               the engine's lineup vs a 'Yahoo autopilot' lineup (best lineup by Yahoo's
               own projection at lock), both scored on what happened — THE number that
               says whether the projection layer has an edge; and Caleb's overrides
               (actual vs engine). Cumulative, with a bootstrap CI over league-weeks.
  (b) CALLS    by kind from the outcome ledger: n, followed, hit rate, predicted vs
               realized slope, points gained, the cost of calls not followed.
  (c) ADDS     started points of Caleb's adds over the man dropped; breakout precision by
               tier (A / B one week / B two weeks / C / W) measured as the flagged free
               agents' next-week PPR — reconstructed from the usage pulls, Kalshi archive,
               trending history and snapshots on disk; and which of each league's top-10
               pickups by points since the add the scan flagged before the adder moved.
  (d) CALIBRATION from lib/calib.report (paired, game-bootstrap CIs, P(TD) reliability).
  (e) RIVALS   FAB left, activity, DEF streaming.

report() computes; text() prints; html() returns the collapsed card section (the card's
own classes: wire / hd / note / wtab). Every block says what it could not compute.
"""
import os, csv, json, glob, random, statistics, datetime as dt, subprocess, tempfile
from collections import defaultdict
from . import clock as C, ts as T, outcomes as OUT, lineup as LU, usage as U
from .names import key, team
from .leagues import ALL

def _esc(x):
    import html
    return html.escape(str(x) if x is not None else '')

def _boot_mean(xs, reps=4000, seed=5):
    if len(xs) < 2: return None
    rng = random.Random(seed)
    ms = sorted(sum(rng.choice(xs) for _ in xs) / len(xs) for _ in range(reps))
    return (ms[int(0.025 * reps)], ms[int(0.975 * reps) - 1])

# ------------------------------------------------------------------ (a) lineup
def _weeks_done(root=None, now=None):
    return [w for w in range(1, OUT.LAST_WEEK + 1) if OUT.week_complete(w, root, now)]

def _pregame_values(lg, w, root=None):
    """{source: {key: pts}} for the week, from calib.load_log (live pregame rows, else the
    git back-fill); week 2 HH also has the engine-only projection json."""
    from . import calib as CB
    out = {s: {} for s in ('engine', 'sleeper', 'yahoo')}
    for k, r in CB.load_log(lg, w, root).items():
        for s in out:
            if r.get(s) not in (None, ''): out[s][k] = float(r[s])
    if not out['engine'] and lg == 'HH' and w == 2:
        for k, r in CB._backfill_hh_wk2().items():
            if r.get('engine') is not None: out['engine'][k] = float(r['engine'])
        out['_engine_src'] = 'HH wk2 engine-only projection json'
    return out

def lineup_week(lg, w, root=None):
    """One league-week. -> dict or None (no matchup page on file)."""
    from .state import _elig
    me = ALL[lg].name; cfg = ALL[lg]
    y = OUT.yahoo_actuals(lg, w, root)
    mine = {k: r for k, r in y.items() if r['owner'] == me and r['slot'] != 'IR'}
    if not mine: return None
    posx = OUT.pos_index(lg, root)
    rows = [dict(key=k, elig=_elig(posx.get(k) or ('DEF' if k.startswith('DST:') else ''), lg)) for k in mine]
    noelig = [mine[k]['player'] for k in mine if not posx.get(k) and not k.startswith('DST:')]
    act = {k: r['pts'] for k, r in mine.items()}
    actual = sum(r['pts'] for r in mine.values() if r['slot'] not in ('BN', 'IR'))
    opt, _ = LU.optimal_points(rows, cfg, act)
    res = dict(league=lg, week=w, actual=round(actual, 2), optimal=round(opt, 2), bench_left=round(opt - actual, 2),
               roster=len(mine), noelig=noelig)
    pv = _pregame_values(lg, w, root)
    # the engine's lineup: frozen lineup_slot decisions when the ledger has the whole week
    dec = [d for d in OUT.latest('decisions', root=root).values() if d['league'] == lg and d['nfl_week'] == w and d['kind'] == 'lineup_slot'
           and (d.get('provenance') or {}).get('engine') != 'ledger']
    if dec and len({d['subject'] for d in dec}) >= len(cfg.slots) - 1:
        keys = [d['recommended'] for d in dec if d.get('recommended')]
        res['engine_src'] = 'decision ledger (recommended occupant per slot at lock)'
        res['engine_on_actual'] = round(sum(act.get(k, 0.0) for k in keys), 2)
        res['engine_missing'] = [k for k in keys if k not in act]
    for src in ('engine', 'yahoo', 'sleeper'):
        if src == 'engine' and 'engine_on_actual' in res: continue
        vals = pv.get(src) or {}
        cov = [k for k in mine if k in vals]
        if len(cov) < max(len(cfg.slots), int(0.6 * len(mine))):
            res[f'{src}_on_actual'] = None; res[f'{src}_cov'] = f'{len(cov)}/{len(mine)}'; continue
        tot, asg = LU.optimal_points(rows, cfg, {k: vals.get(k) for k in mine})
        keys = [k for k in asg.values() if k]
        res[f'{src}_on_actual'] = round(sum(act[k] for k in keys), 2)
        res[f'{src}_cov'] = f'{len(cov)}/{len(mine)}'
        res[f'{src}_lineup'] = sorted(mine[k]['player'] for k in keys)
        if src == 'engine': res['engine_src'] = pv.get('_engine_src') or 'projection log (pregame rows; week 3 from the git back-fill)'
    if res.get('engine_on_actual') is not None and res.get('yahoo_on_actual') is not None:
        res['engine_vs_yahoo'] = round(res['engine_on_actual'] - res['yahoo_on_actual'], 2)
        e, yv = set(res.get('engine_lineup') or []), set(res.get('yahoo_lineup') or [])
        res['diff_players'] = dict(engine_only=sorted(e - yv), yahoo_only=sorted(yv - e))
    if res.get('engine_on_actual') is not None:
        res['overrides'] = round(actual - res['engine_on_actual'], 2)
        # the HH week-2 json predates the log: whether it is the number at lock is not on
        # record, so it is shown but never pooled into the cumulative override figure
        if 'json' in (res.get('engine_src') or ''): res['overrides_unpooled'] = True
    return res

def lineup_section(root=None, now=None):
    weeks = _weeks_done(root, now)
    rows = [r for w in weeks for lg in ALL for r in [lineup_week(lg, w, root)] if r]
    def cum(field):
        xs = [r[field] for r in rows if r.get(field) is not None and not (field == 'overrides' and r.get('overrides_unpooled'))]
        return dict(n=len(xs), total=round(sum(xs), 2), mean=round(sum(xs) / len(xs), 2) if xs else None, ci=_boot_mean(xs))
    return dict(rows=rows, weeks=weeks, bench_left=cum('bench_left'), engine_vs_yahoo=cum('engine_vs_yahoo'), overrides=cum('overrides'))

# ------------------------------------------------------------------ (b) calls by kind
def calls_section(root=None):
    D = OUT.latest('decisions', root=root); RS = OUT.latest('resolutions', key_field='decision_id', root=root)
    O = OUT.latest('outcomes', root=root)
    by = defaultdict(lambda: dict(n=0, open=0, surfaced=0, followed=0, overridden=0, ignored=0, moot=0, scored=0, hits=0,
                                  gained=0.0, cost=0.0, pairs=[], unavailable=0))
    now = C.now()
    for d in D.values():
        b = by[d['kind']]; b['n'] += 1
        if d.get('ever_surfaced') or d.get('surfaced_on_decide'): b['surfaced'] += 1
        r = RS.get(d['id'])
        if not r: b['open'] += 1; continue
        b[r['status']] += 1
        o = O.get(f"{d['id']}|1")
        if not o: continue
        if not o.get('available'): b['unavailable'] += 1; continue
        if d['kind'] == 'lineup_slot':
            v = o.get('call_value')
            if v is None or not o.get('proposed_change'): continue
        else:
            if r.get('recommended') != 'add': continue
            v = o.get('delta_add')
            if v is None: continue
        b['scored'] += 1
        if v > 0: b['hits'] += 1
        if r['status'] == 'followed': b['gained'] += v
        elif r['status'] == 'ignored' or (r['status'] == 'overridden' and d['kind'] != 'lineup_slot'): b['cost'] += v
        if d.get('margin') is not None and d.get('margin_unit') == 'pts_week': b['pairs'].append((d['margin'], v))
    out = []
    for kind in OUT.KINDS:
        b = by.get(kind)
        if not b: continue
        slope = None
        if len(b['pairs']) >= 3:
            xs, ys = zip(*b['pairs']); mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            vx = sum((x - mx) ** 2 for x in xs)
            slope = round(sum((x - mx) * (y - my) for x, y in b['pairs']) / vx, 2) if vx > 0 else None
        row = {k: v for k, v in b.items() if k != 'pairs'}
        row.update(kind=kind, hit_rate=(b['hits'] / b['scored']) if b['scored'] else None, slope=slope, n_slope=len(b['pairs']),
                   gained=round(b['gained'], 2), cost=round(b['cost'], 2))
        out.append(row)
    return dict(rows=out, n_decisions=len(D), n_resolved=len(RS), n_outcomes=len(O))

# ------------------------------------------------------------------ (c) adds + breakout precision
def _git(*a):
    try: return subprocess.run(['git', '-C', OUT.FFDATA] + list(a), capture_output=True, text=True, timeout=30).stdout
    except Exception: return ''

def _shallow():
    return _git('rev-parse', '--is-shallow-repository').strip() == 'true'

def _pump_commits():
    """The pump's commit history, or None when the checkout is shallow (actions/checkout
    defaults to fetch-depth 1): a replay as-of a past moment needs the history, and
    HEAD's files standing in for it would be a wrong as-of, not a replay."""
    if _shallow(): return None
    out = []
    for line in _git('log', '--format=%H %s %cI').splitlines():
        p = line.split()
        if len(p) < 3: continue
        t = T.try_ts(p[2], 'pump') if p[1] == 'pull' else None
        t = t or T.try_ts(p[-1], 'pump')
        if t: out.append((t, p[0]))
    return sorted(out)

def _pump_file_at(path, t, commits):
    """The pump's version of `path` at the last commit at or before t (else the first after)."""
    before = [h for ct, h in commits if ct <= t]
    after = [h for ct, h in commits if ct > t]
    for h in list(reversed(before)) + after[:3]:
        body = _git('show', f'{h}:{path}')
        if body: return body, h
    return None, None

def _fit_week_ladders(path, week, series=('KXNFLRECYDS', 'KXNFLRSHYDS', 'KXNFLPASSYDS')):
    """Kalshi yardage ladders of week `week` from one archived pull -> {(key, series): fit}."""
    from . import market as M
    w0, w1 = C.week_start(week), C.week_start(week + 1)
    rows = []
    with open(path) as fh:
        rd = csv.DictReader(fh); flds = rd.fieldnames
        for r in rd:
            if r.get('series') not in series: continue
            try: d = T.kalshi_event_date(r['event'])
            except Exception: continue
            if w0 <= d + dt.timedelta(hours=12) < w1 + dt.timedelta(hours=12): rows.append(r)
    if not rows: return {}
    fd, tmp = tempfile.mkstemp(suffix='.csv')
    with os.fdopen(fd, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=flds); w.writeheader(); w.writerows(rows)
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return M._load_kalshi(tmp)
    finally:
        os.unlink(tmp)

def _usage_landed(uw):
    """When week uw's full stat line first reached the engine: the first pump commit at or
    after the week's rollover (Tue 07:00 ET of uw+1) that wrote stats_wk{uw}_WR.csv.
    -> (datetime, how)"""
    roll = C.week_start(uw + 1)
    best = None
    for line in _git('log', '--format=%s %cI', '--', f'data/sleeper/stats_wk{uw}_WR.csv').splitlines():
        p = line.split()
        t = T.try_ts(p[1], 'pump') if len(p) >= 2 and p[0] == 'pull' else T.try_ts(p[-1], 'pump') if p else None
        if t is not None and t >= roll and (best is None or t < best): best = t
    if best: return best, 'pump commit'
    t = U.pulled_at(uw)
    if t is not None and t >= roll: return t, 'loader as-of'
    return roll + dt.timedelta(days=1, hours=5), 'nominal (Wed noon after the week — the pull time is not on file)'

def _archive_pull_at(t):
    d = None
    for c in (os.path.join(OUT.ROOT, 'data', 'kalshi_archive'), os.path.join(OUT.FFDATA, 'data', 'archive')):
        if os.path.isdir(c): d = c; break
    if not d: return None
    best = None
    for f in sorted(os.listdir(d)):
        if not f.startswith('kalshi_'): continue
        ft = T.try_ts(f[7:-4], 'pump')
        if ft is not None and ft <= t: best = os.path.join(d, f)
    return best

def retro_scan(lg, uw, root=None, now=None, commits=None):
    """Reconstruct the breakout scan on usage week `uw` as of the moment that pull landed:
    the league's rosters then (snapshot + transactions log), next week's Kalshi ladder vs
    Sleeper's projection then (archive + pump git), the trending list then. Tier rules are
    lib/breakout's own (_usage_tier, MARKET_FLOOR, the 1.15 / 0.85 ratios, the BSB QB rule);
    the registry's add_yes is NOT applied (its history is not on file).
    -> dict(rows=[...], at, notes)"""
    from . import breakout as BK, state as ST
    use = U.load(uw)
    if not use: return dict(rows=[], at=None, notes=[f'no week-{uw} usage on disk'])
    prev = U.load(uw - 1) if uw > 1 else {}
    notes = []
    at, how = _usage_landed(uw)
    notes.append(f'usage week {uw} landed {C.stamp(at)} ({how}) — the scan is replayed as of then')
    sb = OUT.snapshot_before(lg, at + dt.timedelta(minutes=1), root=root)
    if not sb: return dict(rows=[], at=at, notes=notes + ['no league snapshot before the pull'])
    raw = [dict(r) for r in OUT._snap_rows(sb[1])]
    log = [r for r in csv.DictReader(open(os.path.join(root or OUT.ROOT, 'data', 'bsb_transactions.csv' if lg == 'BSB' else 'hh_transactions.csv')))
           if (T.try_ts(r.get('datetime'), 'yahoo_log') or at) <= at]
    rows_now, _ = ST.reconcile(lg, raw, log_rows=log, now=at)
    rostered = {key(r['player']) for r in rows_now} | {'DST:' + team(r.get('nfl') or '') for r in rows_now if (r.get('pos') or '').upper() == 'DEF'}
    commits = commits if commits is not None else _pump_commits()
    # next week's Sleeper projection and the ladder that existed at the pull
    sl = {}
    body, h = _pump_file_at(f'data/sleeper/sleeper_off_wk{uw + 1}.csv', at, commits)
    if body:
        for r in csv.DictReader(body.splitlines()): sl[key(r['player'])] = r
    else:
        p = os.path.join(root or OUT.ROOT, 'data', f'sleeper_off_wk{uw + 1}.csv')
        if not os.path.exists(p): p = os.path.join(root or OUT.ROOT, 'data', f'sleeper_wk{uw + 1}.csv')
        if os.path.exists(p):
            for r in csv.DictReader(open(p)): sl[key(r['player'])] = r
            notes.append(f'Sleeper week-{uw + 1} projection: the engine copy on disk (not as-of the pull)')
    ap = _archive_pull_at(at)
    kal = {}
    if ap is None:
        first = sorted(glob.glob(os.path.join(OUT.ROOT, 'data', 'kalshi_archive', 'kalshi_*.csv')) or glob.glob(os.path.join(OUT.FFDATA, 'data', 'archive', 'kalshi_*.csv')))
        for f in first:
            ft = T.try_ts(os.path.basename(f)[7:-4], 'pump')
            if ft and at < ft <= at + dt.timedelta(days=2):
                ap = f; notes.append(f'no Kalshi pull before {C.stamp(at)}; the first archived pull ({C.stamp(ft)}) stands in'); break
    if ap:
        kal = _fit_week_ladders(ap, uw + 1)
        if not kal:
            # the pull before the usage landed may not carry next week's games yet: the first pull after does
            later = sorted(glob.glob(os.path.join(os.path.dirname(ap), 'kalshi_*.csv')))
            for f in later:
                ft = T.try_ts(os.path.basename(f)[7:-4], 'pump')
                if ft and ft > at:
                    kal = _fit_week_ladders(f, uw + 1)
                    if kal: notes.append(f'week-{uw + 1} ladders first priced at {C.stamp(ft)} (after the pull)'); break
    else:
        notes.append(f'no Kalshi archive at {C.stamp(at)} — market tier undetermined (A/B split unknown; starter usage counted as B)')
    trend = {}
    tb, _ = _pump_file_at('data/sleeper/trending.csv', at, commits)
    if tb:
        for r in csv.DictReader(tb.splitlines()):
            if r.get('kind') != 'add': continue
            nm = f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
            trend[key(nm)] = int(float(r.get('count') or 0))
    else:
        notes.append('no trending history at the pull — CROWD empty (tier C undercounted)')
    fields = {'WR': ('rec_yd', 'KXNFLRECYDS'), 'TE': ('rec_yd', 'KXNFLRECYDS'), 'RB': ('rush_yd', 'KXNFLRSHYDS'), 'QB': ('pass_yd', 'KXNFLPASSYDS')}
    out = []
    for k, r in use.items():
        if k in rostered: continue
        lvl, rule = BK._usage_tier(r)
        if not lvl: continue
        fld, ser = fields[r['pos']]
        f = kal.get((k, ser))
        try: sv = float((sl.get(k) or {}).get(fld) or 0)
        except ValueError: sv = 0.0
        floor = BK.MARKET_FLOOR[fld]
        ahead = market_no = False; mtxt = 'no ladder'
        if f and f.get('sse', 1) < 0.05:
            if sv <= 0: ahead = f['mean'] >= floor; mtxt = f"Kalshi {f['mean']:.0f}, no Sleeper line"
            else:
                ratio = f['mean'] / sv; ahead = ratio >= 1.15 and f['mean'] >= floor; market_no = ratio < 0.85
                mtxt = f"Kalshi {f['mean']:.0f} vs Sleeper {sv:.0f}"
        if lg == 'BSB' and r['pos'] == 'QB' and not (f and f['mean'] >= 240): continue
        crowd = trend.get(k, 0)
        if lvl == 'start' and ahead: tier = 'A'
        elif lvl == 'start' and not market_no: tier = 'B'
        elif lvl == 'start': tier = 'W'
        elif crowd: tier = 'C'
        else: tier = 'W'
        held = ''
        if lvl == 'start' and prev.get(k) and BK._usage_tier(prev[k])[0] == 'start': held = f'wk{uw - 1}'
        out.append(dict(league=lg, usage_week=uw, key=k, name=r['name'], pos=r['pos'], tm=r['tm'], tier=tier, held=held,
                        lvl=lvl, market=mtxt, crowd=crowd, flagged_at=C.iso(at)))
    return dict(rows=out, at=at, notes=notes, snapshot=os.path.basename(sb[1]), ladders=len(kal), pull=os.path.basename(ap) if ap else None)

def _next_week(rows, w, root=None, now=None):
    """Attach next-week PPR (Sleeper pts_ppr) to retro rows. A player with no stat row in a
    complete week did not play: 0. In an incomplete week only teams whose game is on the
    stats pull count (partial)."""
    complete = OUT.week_complete(w, root, now)
    st = OUT.sleeper_stats(w, root)
    teams = {team(r['team']) for r, p in st.values()}
    for x in rows:
        s = st.get(x['key'])
        if s is not None:
            try: x['next_ppr'] = float(s[0].get('pts_ppr') or 0)
            except ValueError: x['next_ppr'] = 0.0
        elif complete or x['tm'] in teams: x['next_ppr'] = 0.0
        else: x['next_ppr'] = None
    return complete

def _cached_scan(lg, uw, root, now, commits, persist):
    """A replayed scan is a fact about the past: computed once per (league, usage week) and
    kept in data/outcomes/retro_scan.jsonl (rows + a meta row); later runs only re-attach
    next-week points."""
    have = [r for r in OUT.read('retro_scan', root) if r['league'] == lg and r['usage_week'] == uw]
    meta = next((r for r in have if r.get('meta')), None)
    if meta is not None:
        return dict(rows=[dict(r) for r in have if not r.get('meta')], at=T.try_ts(meta['at'], 'legacy'), notes=meta['notes'],
                    snapshot=meta.get('snapshot'), ladders=meta.get('ladders'), pull=meta.get('pull'))
    if commits is None:
        return dict(rows=[], at=None, notes=[f'not replayed: the pump checkout is shallow and no cached scan is on file '
                                             f'(ship data/outcomes/retro_scan.jsonl with the engine, or set fetch-depth: 0 in pull.yml)'])
    sc = retro_scan(lg, uw, root, now, commits)
    if persist and sc.get('at') is not None and sc['rows']:
        rows = [dict(r, id=f"{lg}|{uw}|{r['key']}") for r in sc['rows']]
        rows.append(dict(id=f'{lg}|{uw}|__meta', meta=True, league=lg, usage_week=uw, at=C.iso(sc['at']), notes=sc['notes'],
                         snapshot=sc.get('snapshot'), ladders=sc.get('ladders'), pull=sc.get('pull')))
        try: OUT.upsert('retro_scan', rows, root=root)
        except Exception: pass
    return sc

GROUPS = (('A', lambda x: x['tier'] == 'A'), ('B one week', lambda x: x['tier'] == 'B' and not x['held']),
          ('B two weeks', lambda x: x['tier'] == 'B' and bool(x['held'])), ('C', lambda x: x['tier'] == 'C'), ('W', lambda x: x['tier'] == 'W'))

def breakout_precision(root=None, now=None, weeks=(1, 2, 3), persist=True):
    """The precision table: next-week PPR of the free agents the scan would have flagged,
    by tier, for usage week U -> outcome week U+1."""
    commits = _pump_commits()
    table, notes, flags = [], [], []
    for uw in weeks:
        complete = None
        for lg in ALL:
            sc = _cached_scan(lg, uw, root, now, commits, persist)
            rows = sc['rows']
            if not rows:
                notes.append(f'{lg} wk{uw}: ' + '; '.join(sc['notes'])); continue
            complete = _next_week(rows, uw + 1, root, now)
            notes += [f'{lg} wk{uw}: {n}' for n in sc['notes']]
            notes.append(f"{lg} wk{uw}: rosters from {sc['snapshot']} + log to {C.stamp(sc['at'])}; ladders {sc['ladders']} from {sc['pull']}")
            for g, f in GROUPS:
                xs = [x['next_ppr'] for x in rows if f(x) and x['next_ppr'] is not None]
                pend = sum(1 for x in rows if f(x) and x['next_ppr'] is None)
                table.append(dict(league=lg, uw=uw, ow=uw + 1, group=g, n=len(xs), pending=pend,
                                  mean=(sum(xs) / len(xs)) if xs else None, median=statistics.median(xs) if xs else None,
                                  ge10=(sum(1 for v in xs if v >= 10) / len(xs)) if xs else None, complete=complete,
                                  names=[f"{x['name']} {x['next_ppr']:.1f}" for x in sorted((x for x in rows if f(x) and x['next_ppr'] is not None), key=lambda x: -x['next_ppr'])][:6]))
            flags += [dict(id=f"{lg}|{uw}|{x['key']}", league=lg, usage_week=uw, key=x['key'], name=x['name'], tier=x['tier'] + ('2' if x['held'] else ''),
                           flagged_at=x['flagged_at'], next_ppr=x['next_ppr']) for x in rows if x['tier'] in ('A', 'B')]
    if persist and flags:
        try: OUT.upsert('retro_flags', flags)
        except Exception as e: notes.append(f'retro flags not persisted: {e!r}')
    # pooled across leagues and weeks, complete weeks only
    pooled = []
    for g, _ in GROUPS:
        sub = [r for r in table if r['group'] == g and r['complete'] and r['n']]
        n = sum(r['n'] for r in sub)
        if n: pooled.append(dict(group=g, n=n, mean=sum(r['mean'] * r['n'] for r in sub) / n))
    return dict(table=table, pooled=pooled, notes=notes)

def adds_section(root=None, now=None, precision=None):
    """Caleb's own adds: started points (weeks he was in a starting slot) and the value
    over the man dropped (hindsight V with vs without). And each league's top-10 pickups
    by points since the add, with whether the scan (or a ledger call) flagged him first."""
    done = _weeks_done(root, now)
    A = OUT.Actuals(root)
    mine, top = [], {}
    flags = {}
    for r in OUT.read('retro_flags', root):
        t = T.try_ts(r['flagged_at'], 'legacy'); kk = (r['league'], r['key'])
        if t and (kk not in flags or t < flags[kk][0]): flags[kk] = (t, r['tier'], f"usage wk{r['usage_week']}")
    for d in OUT.latest('decisions', root=root).values():
        if d['kind'] in ('breakout_tier', 'add_drop', 'claim', 'nextup', 'stream'):
            t = T.try_ts(d['created'], 'legacy'); kk = (d['league'], d['subject'])
            if t and (kk not in flags or t < flags[kk][0]): flags[kk] = (t, (d.get('extra') or {}).get('tier') or d['kind'], 'ledger ' + d['kind'])
    for lg in ALL:
        me = ALL[lg].name; posx = OUT.pos_index(lg, root)
        log = OUT._log(lg, root)
        adds = [r for r in log if r['action'] == 'Add']
        for r in adds:
            w0 = C.nfl_week(r['t'])
            ws = [w for w in done if w >= w0]
            pts, why = 0.0, []
            for w in ws:
                v, s = A.pts(lg, w, r['key'], posx.get(r['key']) or r.get('pos'))
                if v is None: why.append(w); continue
                pts += v
            row = dict(league=lg, team=r['team'], player=r['player'], key=r['key'], pos=r.get('pos'), at=r['t'], weeks=ws, pts=round(pts, 2),
                       unavailable=why, note=r.get('note'), bid=r.get('bid'))
            f = flags.get((lg, r['key']))
            row['flag'] = (f'{f[1]} {C.stamp(f[0])} ({f[2]})' if f else None)
            row['flag_first'] = bool(f and f[0] < r['t'])
            top.setdefault(lg, []).append(row)
            if r['team'] == me:
                drop = next((x for x in log if x['team'] == me and x['action'] == 'Drop' and abs((x['t'] - r['t']).total_seconds()) < 120), None)
                started = 0.0; vd = 0.0; vok = True
                for w in ws:
                    y = OUT.yahoo_actuals(lg, w, root).get(r['key'])
                    if y and y['owner'] == me and y['slot'] not in ('BN', 'IR'): started += y['pts']
                    R0, _ = OUT.roster_week(lg, w, root)
                    if R0 is None: vok = False; continue
                    dk = drop['key'] if drop else None
                    v1, m1 = OUT.V(lg, (R0 | {r['key']}) - ({dk} if dk else set()), w, A, posx)
                    v0, m0 = OUT.V(lg, (R0 - {r['key']}) | ({dk} if dk else set()), w, A, posx)
                    if any(m[0] in (r['key'], dk) for m in m1 + m0): vok = False; continue
                    vd += v1 - v0
                mine.append(dict(row, drop=drop['player'] if drop else None, started=round(started, 2),
                                 over_drop=round(vd, 2) if vok and ws else None))
    tops = {lg: sorted([r for r in rows if r['weeks']], key=lambda r: -r['pts'])[:10] for lg, rows in top.items()}
    return dict(mine=sorted(mine, key=lambda r: r['at']), top=tops, weeks=done, precision=precision)

# ------------------------------------------------------------------ (e) rivals
def rivals_section(root=None, now=None):
    from . import fab as F
    now = now or C.now()
    out = {}
    fab = None
    try: fab = F.model()
    except Exception: pass
    for lg in ALL:
        me = ALL[lg].name
        P = defaultdict(lambda: dict(adds=0, last7=0, claims=0, def_adds=0, k_adds=0, bids=[]))
        for r in OUT._log(lg, root):
            if r['action'] != 'Add': continue
            p = P[r['team']]; p['adds'] += 1
            if (now - r['t']).days < 7: p['last7'] += 1
            if (r.get('note') or '').lower() == 'waiver':
                p['claims'] += 1
                if (r.get('bid') or '').strip().isdigit(): p['bids'].append(int(r['bid']))
            if (r.get('pos') or '').upper() == 'DEF': p['def_adds'] += 1
            if (r.get('pos') or '').upper() == 'K': p['k_adds'] += 1
        rows = []
        for o, p in sorted(P.items(), key=lambda kv: -kv[1]['adds']):
            spent = (fab or {}).get('spent', {}).get(o) if lg == 'BSB' and fab else None
            rows.append(dict(owner=o, me=o == me, adds=p['adds'], last7=p['last7'], claims=p['claims'], def_adds=p['def_adds'], k_adds=p['k_adds'],
                             fab_left=(F.BUDGET - spent) if spent is not None else (F.BUDGET if lg == 'BSB' and fab else None),
                             max_bid=max(p['bids']) if p['bids'] else None))
        out[lg] = rows
    return out

# ------------------------------------------------------------------ the report
def report(run=None, root=None, now=None, precision_weeks=(1, 2, 3)):
    now = now or C.now()
    rep = dict(made=C.stamp(now), sections={})
    S = rep['sections']
    for name, fn in (('lineup', lambda: lineup_section(root, now)), ('calls', lambda: calls_section(root)),
                     ('precision', lambda: breakout_precision(root, now, precision_weeks))):
        try: S[name] = fn()
        except Exception as e:
            import traceback
            S[name] = dict(error=f'{e!r}', trace=traceback.format_exc()[-800:])
    try: S['adds'] = adds_section(root, now)
    except Exception as e: S['adds'] = dict(error=repr(e))
    try:
        from . import calib as CB
        cal = (run or {}).get('calib')
        if not cal or 'pairs' not in cal: cal = CB.report(max(_weeks_done(root, now) or [1]), root)
        S['calib'] = cal
        S['fidelity'] = OUT.fidelity(_weeks_done(root, now), root)
    except Exception as e: S['calib'] = dict(error=repr(e))
    try: S['rivals'] = rivals_section(root, now)
    except Exception as e: S['rivals'] = dict(error=repr(e))
    try: S['ledger'] = OUT.summary(root)
    except Exception as e: S['ledger'] = dict(error=repr(e))
    S['blind'] = blind(S, now, root)
    return rep

def blind(S, now, root=None):
    """What the report cannot see yet, and when that changes."""
    L = []
    cs = S.get('calls') or {}
    live = [r for r in OUT.latest('decisions', root=root).values() if (r.get('provenance') or {}).get('engine') != 'ledger']
    wk = C.nfl_week(now)
    L.append(f"Calls by kind: {len(live)} decision points recorded live so far (the store starts with this build); the rest are the ledger's "
             f"historical start/add calls, imported. This week's lineup slots resolve at each kickoff and score once week {wk} is final "
             f"(after the {C.stamp(C.week_start(wk + 1))} rollover and the pump's Tuesday stats pull); adds, breakouts and streams score at N=1 then, "
             f"N=3 three weeks later, rest-of-season after week 17. Breakout rows (Tier A/B) are recorded only from this build on.")
    L.append("Yahoo autopilot vs engine needs Yahoo's pregame projection per player: week 3 has it from the pump's roster pages (git back-fill); "
             "week 2 has none (pre-pump) — that week shows bench points only. Week-3 engine numbers are today's code on that week's inputs.")
    L.append('HH IDP: no Sleeper IDP stat file in the pump, so any IDP outcome that needs a player Yahoo did not print (a free-agent IDP add, '
             "a rival's IDP pickup, IDP calibration outside the two matchup rosters) is unavailable until an IDP stats pull is added to the pump "
             "(sleeper_pull.py: position[]=DL,LB,DB).")
    try: n_pw = len(OUT.read('pwin', root))
    except Exception: n_pw = 0
    L.append(f'P(win) reliability: {n_pw} league-week(s) with P(beat opponent) frozen at the first kickoff so far (a week whose first starter '
             'already played before this build is not back-filled — HH week 4 locked Thursday); it prints at 4 with finals — at the earliest '
             'after week 6 is final.')
    L.append('Breakout precision: usage week 3 -> week 4 is partial until week 4 is final; usage week 1 has no market and no trending history '
             '(A/B undetermined, C undercounted); the registry\'s add_yes (beat reporting) cannot be replayed, so retro Tier A is market-only.')
    L.append('Claims: a losing bid is invisible to the pump — `ff.py bid <player> <amount>` before Tuesday night or the claims table '
             'only knows the winners.')
    return L

# ------------------------------------------------------------------ text
def _f(v, d=1, sign=False):
    if v is None: return 'n/a'
    return (f'{v:+.{d}f}' if sign else f'{v:.{d}f}')

def _pct(v): return 'n/a' if v is None else f'{v:.0%}'

def _ci(ci): return 'n/a' if not ci else f"{ci['diff']:+.2f} [{ci['lo']:+.2f}, {ci['hi']:+.2f}]"

def text(rep):
    S = rep['sections']; L = [f"EDGE REPORT — {rep['made']}"]
    # (a)
    a = S.get('lineup') or {}
    L.append('\n(a) LINEUP — scored on what happened (Yahoo matchup-page points, exact)')
    if a.get('error'): L.append('  failed: ' + a['error'])
    else:
        L.append(f"  {'lg':4}{'wk':>3} {'actual':>7} {'optimal':>8} {'bench left':>10} {'engine':>7} {'yahoo AP':>8} {'sleeper AP':>10} {'eng-yah':>8} {'act-eng':>8}  engine source")
        for r in a['rows']:
            L.append(f"  {r['league']:4}{r['week']:3d} {r['actual']:7.1f} {r['optimal']:8.1f} {r['bench_left']:10.1f} {_f(r.get('engine_on_actual')):>7} {_f(r.get('yahoo_on_actual')):>8} "
                     f"{_f(r.get('sleeper_on_actual')):>10} {_f(r.get('engine_vs_yahoo'), sign=True):>8} {_f(r.get('overrides'), sign=True) + ('*' if r.get('overrides_unpooled') else ''):>8}  {r.get('engine_src') or 'none (no pregame engine numbers)'}"
                     + (f" · coverage e{r.get('engine_cov')} y{r.get('yahoo_cov')}" if r.get('engine_cov') or r.get('yahoo_cov') else ''))
            dp = r.get('diff_players')
            if dp and (dp['engine_only'] or dp['yahoo_only']):
                L.append(f"        engine started {', '.join(dp['engine_only'])} where Yahoo's autopilot started {', '.join(dp['yahoo_only'])}")
        if any(r.get('overrides_unpooled') for r in a['rows']):
            L.append('  * HH week 2: the engine numbers are the saved week-2 projection json (whether they were the numbers at lock is not on record) — shown, not pooled')
        for nm, lab in (('bench_left', 'points left on the bench'), ('engine_vs_yahoo', 'ENGINE vs YAHOO AUTOPILOT'), ('overrides', 'actual vs engine (overrides)')):
            c = a.get(nm) or {}
            ci = c.get('ci')
            L.append(f"  cumulative {lab}: {_f(c.get('total'), sign=nm != 'bench_left')} over {c.get('n', 0)} league-week(s)"
                     + (f", mean {_f(c.get('mean'), 2, sign=nm != 'bench_left')} [95% bootstrap {ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else '')
                     + (' — fewer than 4 league-weeks: the CI is not meaningful yet' if c.get('n', 0) < 4 else ''))
    # (b)
    b = S.get('calls') or {}
    L.append('\n(b) CALLS BY KIND — the outcome ledger')
    if b.get('error'): L.append('  failed: ' + b['error'])
    else:
        L.append(f"  {b['n_decisions']} decision points · {b['n_resolved']} resolved · {b['n_outcomes']} outcome rows")
        L.append(f"  {'kind':14} {'n':>4} {'open':>4} {'surf':>4} {'foll':>4} {'over':>4} {'ign':>4} {'moot':>4} {'scored':>6} {'hit':>5} {'slope':>6} {'gained':>7} {'cost':>7}")
        for r in b['rows']:
            L.append(f"  {r['kind']:14} {r['n']:4d} {r['open']:4d} {r['surfaced']:4d} {r['followed']:4d} {r['overridden']:4d} {r['ignored']:4d} {r['moot']:4d} {r['scored']:6d} "
                     f"{_pct(r['hit_rate']):>5} {_f(r['slope'], 2):>6} {r['gained']:+7.1f} {r['cost']:+7.1f}")
        L.append('  hit = the call\'s realized value > 0 (lineup: recommended minus the occupant it would replace; add: V(with add) - V(with drop), N=1); '
                 'gained = over followed calls; cost = value of calls ignored (adds: also declined/overridden — a missed add counts; a lineup override is not attributable to one call); slope = realized on predicted, weekly-point calls, n>=3.')
    # (c)
    c = S.get('adds') or {}
    pr = S.get('precision') or {}
    L.append('\n(c) ADDS')
    if c.get('error'): L.append('  failed: ' + c['error'])
    else:
        L.append(f"  Caleb's adds (complete weeks {c['weeks']}): started points, and value over the man dropped (hindsight-optimal lineup with vs without)")
        for r in c['mine']:
            L.append(f"    {r['league']:3} {r['at']:%m-%d} {r['player'][:22]:22} for {str(r['drop'] or '-')[:20]:20} wks {r['weeks'] or '-'}  pts {r['pts']:5.1f}  started {r['started']:5.1f}  over drop {_f(r['over_drop'], sign=True)}"
                     + (f"  (IDP wk {r['unavailable']} unavailable)" if r['unavailable'] else ''))
    L.append('  BREAKOUT PRECISION — next-week PPR of the free agents each tier would have flagged (retro scan on the usage pulls on disk)')
    if pr.get('error'): L.append('  failed: ' + pr['error'])
    else:
        L.append(f"  {'lg':4}{'usage→':>7} {'tier':12} {'n':>3} {'mean':>6} {'median':>6} {'≥10':>5}  top")
        for r in pr['table']:
            if not r['n'] and not r['pending']: continue
            L.append(f"  {r['league']:4} wk{r['uw']}→{r['ow']} {r['group']:12} {r['n']:3d} {_f(r['mean']):>6} {_f(r['median']):>6} {_pct(r['ge10']):>5}  "
                     + ('; '.join(r['names'][:4])) + ('' if r['complete'] else f"  [PARTIAL: week {r['ow']} not final; {r['pending']} pending]"))
        if pr.get('pooled'):
            L.append('  pooled, complete weeks: ' + ' · '.join(f"{p['group']} {p['mean']:.1f} (n={p['n']})" for p in pr['pooled']))
        for n in pr.get('notes', [])[:20]: L.append('  note: ' + n)
    if not c.get('error'):
        for lg, rows in (c.get('top') or {}).items():
            L.append(f"  {lg} top-10 pickups by points since the add (complete weeks), and whether we flagged him first:")
            for r in rows:
                L.append(f"    {r['pts']:6.1f}  {r['player'][:22]:22} {r['team'][:22]:22} {r['at']:%m-%d %H:%M}  "
                         + (('FLAGGED FIRST — ' if r['flag_first'] else 'flagged after — ') + r['flag'] if r['flag'] else 'not flagged'))
    # (d)
    L.append('\n(d) CALIBRATION')
    cal = S.get('calib') or {}
    if cal.get('error'): L.append('  failed: ' + cal['error'])
    else:
        from . import calib as CB
        L.append('\n'.join('  ' + x for x in CB.fmt(cal).splitlines()))
        fd = S.get('fidelity') or []
        if fd:
            L.append('  actuals fidelity — Sleeper stat line scored in league rules vs Yahoo\'s exact number: ' +
                     '; '.join(f"{r['league']} {r['pos']} n={r['n']} MAE {r['mae']:.2f}" for r in fd))
    # (e)
    L.append('\n(e) RIVALS')
    rv = S.get('rivals') or {}
    if rv.get('error'): L.append('  failed: ' + rv['error'])
    else:
        for lg, rows in rv.items():
            L.append(f"  {lg}: " + ' · '.join(f"{r['owner'][:16]}{' (me)' if r['me'] else ''} adds {r['adds']}/{r['last7']} wk" + (f" FAB ${r['fab_left']}" if r['fab_left'] is not None else '') + (f" DEF {r['def_adds']}" if r['def_adds'] else '') for r in rows))
    L.append('\nSTILL BLIND')
    for b_ in S.get('blind', []): L.append('  - ' + b_)
    return '\n'.join(L)

# ------------------------------------------------------------------ html (the card's collapsed section)
def html(rep):
    """-> list of HTML strings for card._assemble's sec(): the card's own classes only."""
    S = rep['sections']; H = []
    a = S.get('lineup') or {}
    H.append('<div class="wire" style="margin:0"><div class="hd"><h3>Lineup edge — scored on what happened</h3><div class="note">'
             'Bench left = the hindsight-optimal lineup minus the starters you played. Engine vs Yahoo autopilot = the engine\'s lineup at lock minus '
             'the best lineup by Yahoo\'s own projection, both on actual points: the number that says whether the projection layer has an edge. '
             'Act − eng = your overrides.</div></div>')
    if a.get('rows'):
        H.append('<table class="wtab"><thead><tr><th>League</th><th>Wk</th><th>Actual</th><th>Bench left</th><th>Engine</th><th>Yahoo AP</th><th>Eng − Yah</th><th>Act − eng</th></tr></thead><tbody>')
        for r in a['rows']:
            H.append(f"<tr><td>{r['league']}</td><td>{r['week']}</td><td>{r['actual']:.1f}</td><td>{r['bench_left']:.1f}</td><td>{_f(r.get('engine_on_actual'))}</td>"
                     f"<td>{_f(r.get('yahoo_on_actual'))}</td><td>{_f(r.get('engine_vs_yahoo'), sign=True)}</td><td>{_f(r.get('overrides'), sign=True)}</td></tr>")
        ev = a.get('engine_vs_yahoo') or {}
        H.append(f"<tr style=font-weight:700><td colspan=6>Cumulative engine − Yahoo autopilot ({ev.get('n', 0)} league-weeks)</td><td>{_f(ev.get('total'), sign=True)}</td><td>{_f((a.get('overrides') or {}).get('total'), sign=True)}</td></tr>")
        H.append('</tbody></table>')
    H.append('</div>')
    pr = S.get('precision') or {}
    if pr.get('table'):
        H.append('<div class="wire" style="margin:0"><div class="hd"><h3>Breakout precision — next-week PPR by tier</h3><div class="note">'
                 'The scan replayed on each usage pull with the rosters, Kalshi ladders and trending list of that moment; the outcome is the flagged free agents\' PPR the next week (0 if he did not play).</div></div>')
        H.append('<table class="wtab"><thead><tr><th>League</th><th>Usage → week</th><th>Tier</th><th>n</th><th>Mean</th><th>≥10</th><th>Top</th></tr></thead><tbody>')
        for r in pr['table']:
            if not r['n']: continue
            H.append(f"<tr><td>{r['league']}</td><td>{r['uw']} → {r['ow']}{'' if r['complete'] else ' (partial)'}</td><td>{_esc(r['group'])}</td><td>{r['n']}</td><td>{_f(r['mean'])}</td>"
                     f"<td>{(format(r['ge10'], '.0%') if r['ge10'] is not None else 'n/a')}</td><td>{_esc('; '.join(r['names'][:3]))}</td></tr>")
        H.append('</tbody></table></div>')
    b = S.get('calls') or {}
    if b.get('rows'):
        H.append('<div class="wire" style="margin:0"><div class="hd"><h3>Calls by kind — the outcome ledger</h3><div class="note">'
                 f"{b['n_decisions']} decision points, {b['n_resolved']} resolved, {b['n_outcomes']} scored. Gained = followed calls; cost = calls not followed (a missed add counts).</div></div>")
        H.append('<table class="wtab"><thead><tr><th>Kind</th><th>n</th><th>Followed</th><th>Ignored / overridden</th><th>Hit</th><th>Gained</th><th>Cost</th></tr></thead><tbody>')
        for r in b['rows']:
            H.append(f"<tr><td>{_esc(r['kind'])}</td><td>{r['n']}</td><td>{r['followed']}</td><td>{r['ignored']} / {r['overridden']}</td>"
                     f"<td>{(format(r['hit_rate'], '.0%') if r['hit_rate'] is not None else 'n/a')}</td><td>{r['gained']:+.1f}</td><td>{r['cost']:+.1f}</td></tr>")
        H.append('</tbody></table></div>')
    cal = S.get('calib') or {}
    if cal.get('pairs'):
        H.append('<div class="wire" style="margin:0"><div class="hd"><h3>Projection error, paired</h3><div class="note">' + _esc(cal.get('note', '')) + '</div></div>')
        H.append('<table class="wtab"><thead><tr><th>Pair</th><th>League</th><th>n</th><th>MAE</th><th>RMSE</th><th>Bias</th><th>MAE diff [95% CI]</th></tr></thead><tbody>')
        for p in cal['pairs']:
            ci = p.get('ci')
            H.append(f"<tr><td>{p['a']} v {p['b']}</td><td>{p['league']}</td><td>{p['n']}</td><td>{p['sa']['mae']:.2f} v {p['sb']['mae']:.2f}</td><td>{p['sa']['rmse']:.2f} v {p['sb']['rmse']:.2f}</td>"
                     f"<td>{p['sa']['bias']:+.2f} v {p['sb']['bias']:+.2f}</td><td>{_ci(ci)}</td></tr>")
        H.append('</tbody></table></div>')
    rv = S.get('rivals') or {}
    if rv and not rv.get('error'):
        H.append('<div class="wire" style="margin:0"><div class="hd"><h3>Rivals — activity, FAB, DEF streaming</h3></div>')
        H.append('<table class="wtab"><thead><tr><th>League</th><th>Manager</th><th>Adds</th><th>Last 7d</th><th>FAB left</th><th>DEF adds</th></tr></thead><tbody>')
        for lg, rows in rv.items():
            for r in rows:
                H.append(f"<tr><td>{lg}</td><td>{_esc(r['owner'])}{' (you)' if r['me'] else ''}</td><td>{r['adds']}</td><td>{r['last7']}</td><td>{'' if r['fab_left'] is None else '$' + str(r['fab_left'])}</td><td>{r['def_adds']}</td></tr>")
        H.append('</tbody></table></div>')
    bl = S.get('blind') or []
    if bl:
        H.append('<div class="wire" style="margin:0"><div class="hd"><h3>Still blind</h3><div class="note">' + '<br>'.join(_esc(x) for x in bl) + '</div></div></div>')
    return H
