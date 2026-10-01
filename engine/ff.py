#!/usr/bin/env python3
"""ff — the one entry point for both fantasy leagues.

  python3 ff.py status     "are we good?" — live state, staleness, open items, next locks
  python3 ff.py check      run every regression; nothing else runs if this fails
  python3 ff.py week       lineup diff vs live slots, both leagues, gated
  python3 ff.py wire       free agency, both leagues, gated, usage-first
  python3 ff.py season     schedule windows, byes, December environment
  python3 ff.py card       regenerate the card FROM the run output (never hand-written)
  python3 ff.py run        check + week + wire + season + card   <- the weekly routine
  python3 ff.py decline <league> <kind> <player>     record a Caleb "no" so it is never re-raised

Everything a command prints is also written to data/run/<stamp>.json so the card
and the next run read the same facts this run did.
"""
import sys, os, json, subprocess
sys.path.insert(0, '/home/claude/bsb2')
from lib import clock as C, state as S, ledger as L, lineup as LU, wire as W, gate as G
from lib import score as SC, windows as WN
from lib.project import Projections
from lib.names import key, team

D = '/home/claude/bsb2/data/'
LEAGUES = ('BSB', 'HH')
UNUSABLE = S.UNUSABLE

def hr(t=''): print('\n' + '=' * 96 + (f'\n{t}\n' + '=' * 96 if t else ''))

# ----------------------------------------------------------------- check
def cmd_check(quiet=False):
    r = subprocess.run([sys.executable, '/home/claude/bsb2/test_gate.py'], capture_output=True, text=True)
    ok = r.returncode == 0
    last = [l for l in r.stdout.splitlines() if 'behaved as required' in l]
    if not quiet:
        hr('CHECK'); print('  ' + (last[-1] if last else r.stdout[-300:]))
        if not ok: print(r.stdout)
    r2 = subprocess.run([sys.executable, '/home/claude/bsb2/test/test_system.py'], capture_output=True, text=True)
    ok2 = r2.returncode == 0
    last2 = [l for l in r2.stdout.splitlines() if 'behaved' in l or 'FAIL' in l]
    if not quiet:
        for l in last2[-6:]: print('  ' + l)
        if not ok2: print(r2.stdout[-2000:])
    elif not (ok and ok2):
        # quiet mode (ff.py run): still name what failed, so a refused run in the
        # pump's log says why (09-27: the Action refused with no detail on file)
        for l in [x for x in r.stdout.splitlines() + r2.stdout.splitlines() if x.startswith('[FAIL]') or 'Traceback' in x or 'Error' in x][:12]: print('  ' + l)
        for l in last + last2[-1:]: print('  ' + l)
    return ok and ok2

# ----------------------------------------------------------------- status
def cmd_status(run=None):
    hr(f'STATUS  {C.stamp()}  ·  NFL week {C.nfl_week()}')
    wd = C.bsb_waiver_deadline()
    h = (wd - C.now()).total_seconds() / 3600
    if 0 < h < 30: print(f'  BSB waivers process {C.stamp(wd)} — {h:.1f}h from now')
    P = Projections(C.data_week())
    # ---- market freshness: the question "are we tracking Vegas?" must have a
    # numeric answer every time, not a feeling.
    print('\n  MARKETS ON DISK')
    for fn, what in (('kalshi.csv', 'Kalshi ladders'), ('espn_games.csv', 'Vegas game lines'),
                     ('espn_props.csv', 'DraftKings props'), ('lines_wk10_18.csv', 'look-ahead lines'),
                     (f'sleeper_off_wk{C.data_week()}.csv', 'Sleeper offense'), (f'sleeper_idp_wk{C.data_week()}.csv', 'Sleeper IDP')):
        pth = D + fn
        if not os.path.exists(pth): print(f'     {what:18s} MISSING'); continue
        age = (C.now().timestamp() - os.path.getmtime(pth)) / 3600
        extra = ''
        if fn == 'kalshi.csv':
            extra = f' · {len(P.kal)} fitted ladders · {len(P.ready)}/32 teams market-ready'
            if not any(s_ == 'KXNFLREC' for (_, s_) in P.kal if _ not in ()) : pass
        print(f'     {what:18s} {age:5.1f}h old{extra}')
    for lg in LEAGUES:
        st = S.load(lg); rec = L.reconcile(st)
        print(f'\n  {st.describe()}')
        for e, new in rec: print(f'     ledger: {e["kind"]} {e["subject"]} -> {new}')
        st_l, why_l = st.stale_for('lineup'); st_a, why_a = st.stale_for('add_drop')
        print(f'     lineup calls: {"STALE — " + why_l if st_l else "ok"}   add/drop calls: {"STALE — " + why_a if st_a else "ok"}')
        # locks
        nxt = sorted({(P.kickoff(r['tm']), r['player']) for r in st.starters() if P.kickoff(r['tm'])},
                     key=lambda x: x[0])
        if nxt:
            k0 = nxt[0][0]; who = [n for k, n in nxt if k == k0]
            print(f'     next lock: {C.stamp(k0)} ({C.lineup_phase(k0)}) — {", ".join(who)}')
        opn = L.open_items(lg)
        if opn:
            print(f'     open on the ledger ({len(opn)}):')
            for e in opn: print(f'        {e["kind"]:5s} {e["subject"]:24s} {e["call"][:60]}')
        else: print('     nothing open on the ledger')
        missing = [r['player'] for r in st.starters() if P.line(r['key'], r['pos'], r['tm'])['unknown']
                   and r['designation'] not in UNUSABLE]
        if missing: print(f'     STARTERS NO SOURCE COVERS: {", ".join(missing)}  (unknown, not zero)')

# ----------------------------------------------------------------- week
def build(week=None):
    """Assemble the whole run for both leagues. Returns the run dict."""
    week = week or C.data_week()
    P = Projections(week); WNd = WN.Windows()
    sea = json.load(open(D + 'season_blend.json')) if os.path.exists(D + 'season_blend.json') else {}
    sea_blend = sea
    run = dict(stamp=C.stamp(), iso=C.iso(), week=week, leagues={})
    from lib import actuals as AC
    for lg in LEAGUES:
        st = S.load(lg); L.reconcile(st)
        act = AC.load(lg, week)
        lu = LU.solve(st, P, actuals=act)
        w = W.Wire(st, P, season=sea if lg == 'BSB' else None)
        R = dict(state=st, lineup=lu, wire=w, calls=[], flags=[], actuals=act, actuals_at=AC.pulled_at(lg, week))
        # ---- lineup calls
        for c in lu['changes']:
            o, s = c['start'], c['sit']
            g = G.check('start', f'{c["slot"]}: {o["player"]}', player=o['player'],
                        designation=o['designation'], sources=o['line']['sources'],
                        pos=o['line']['fam'], value=o['pts'], horizon='weekly',
                        market_ready=o['ready'], pulled=C.today().isoformat(), league=lg, state=st,
                        note=f'start {o["player"]} at {c["slot"]}')
            e = L.propose(lg, 'start', o['player'], f'start {o["player"]} at {c["slot"]}',
                          detail=f'over {s["player"] if s else "empty"} {c["gain"]:+.2f}',
                          evidence=o['line']['sources'], verdict=g.verdict,
                          provisional=c['provisional'], state=st,
                          resolves_at=C.iso(o['kick']) if o['kick'] else None)
            R['calls'].append(dict(kind='start', change=c, gate=g, ledger=e))
        # ---- wire: weekly upgrades (DEF/K etc) and roster construction
        for u in w.upgrade_board(lu)[:3]:
            g = w.gate_add(u['add'], horizon='weekly' if u['fam'] in ('DEF', 'K') else 'season')
            e = L.propose(lg, 'add', u['add']['name'], f'add {u["add"]["name"]} ({u["fam"]}) over {u["over"]["player"]}',
                          detail=f'{u["gain"]:+.2f}/wk', evidence=u['add']['line']['sources'],
                          verdict=g.verdict, state=st)
            R['calls'].append(dict(kind='upgrade', item=u, gate=g, ledger=e))
        for b in w.bench_board(lu)[:4]:
            ga = w.gate_add(b['add']); gd = w.gate_drop(b['drop'])
            e = L.propose(lg, 'add', b['add']['name'], f'drop {b["drop"]["player"]} -> add {b["add"]["name"]}',
                          detail=f'{b["gain"]:+.1f} {b["basis"]}' + (' · replaces a dead spot' if b['dead'] else ''),
                          evidence=b['add']['line']['sources'] + (['usage'] if b['add']['verified'] else []),
                          verdict=('BLOCK' if 'BLOCK' in (ga.verdict, gd.verdict) else
                                   'WARN' if 'WARN' in (ga.verdict, gd.verdict) else 'PASS'),
                          state=st)
            R['calls'].append(dict(kind='swap', item=b, gate_add=ga, gate_drop=gd, ledger=e))
        # ---- structural flags
        fams = {}
        for r in st.mine:
            if r['slot'] != 'IR': fams.setdefault(W._fam(r['pos']), []).append(r['player'])
        for f in ('DEF', 'K'):
            if len(fams.get(f, [])) > 1:
                # BSB (uncapped adds): a second DEF/K is a spot spent on a streamable
                # commodity. HH (7 adds/week): streaming is rationed, so a second
                # DEF that is elite on the SEASON and strong in the PLAYOFF window is
                # an asset, not a flag. 2026-09-16: the Texans -- #1 season DEF,
                # 4th-best playoff schedule -- were flagged as a wasted spot and
                # nearly dropped for a kicker stream. Caleb caught it.
                if st.cfg.acq_cap is not None and f == 'DEF':
                    keep = []
                    for r in st.mine:
                        if W._fam(r['pos']) != 'DEF' or r['key'] in w.hold: continue
                        sea = sea_all = None
                        sea = (sea_defs := sorted([(v['pts'], k) for k, v in sea_blend.items() if v['pos'] == 'DEF'], reverse=True))
                        rank = next((i + 1 for i, (p_, k) in enumerate(sea) if k == r['key']), None)
                        prk, pn = WNd.rank(r['tm'], WN.PLAY, idp=True)
                        if rank and rank <= 3 and prk and prk <= 8:
                            keep.append(f'{r["player"]} (#{rank} season, #{prk} playoff schedule)')
                    held = [r['player'] for r in st.mine if W._fam(r['pos']) == 'DEF' and r['key'] in w.hold]
                    if keep or held:
                        R['flags'].append(f'{len(fams[f])} DEFs rostered — second one is a HOLD in a capped league: ' + '; '.join(keep + [f'{h} (registry hold)' for h in held]))
                        continue
                pair = sorted([r for r in st.mine if W._fam(r['pos']) == f and r['slot'] != 'IR'],
                              key=lambda r: sea_blend.get(r['key'], {}).get('pts') or 0)
                if len(pair) >= 2 and f == 'DEF':
                    lo, hi = pair[0], pair[-1]
                    lo_s, hi_s = (sea_blend.get(lo['key'], {}).get('pts') or 0), (sea_blend.get(hi['key'], {}).get('pts') or 0)
                    R['flags'].append(f'{len(fams[f])} DEFs rostered ({", ".join(fams[f])}) for one DEF slot — the spare is {lo["player"]} ({lo_s:.0f} season vs {hi["player"]} {hi_s:.0f})'
                                      + (f'; {hi["player"]} is on the bench this week only on the matchup ({hi["pts"]:.1f} vs {lo["pts"]:.1f}), not on quality' if hi['slot'] == 'BN' and hi.get('pts') is not None and lo.get('pts') is not None else ''))
                else:
                    R['flags'].append(f'{len(fams[f])} {f}s rostered ({", ".join(fams[f])}) for one {f} slot')
        # a questionable STARTER needs a named contingency before his game locks
        # (Oluokun Q in the D slot, 09-18). Name the best eligible bench player.
        for r in lu['rows']:
            if r['slot'] in ('BN', 'IR') or r['designation'] != 'Q': continue
            if r.get('kick') and r['kick'] <= C.now(): continue          # his game is played; the Q question is over
            cands = [b for b in lu['rows'] if b['slot'] == 'BN' and b['designation'] not in UNUSABLE
                     and b['designation'] != 'Q' and (b['elig'] & st.cfg.accepts[r['slot']]) and b.get('pts') is not None]
            best = max(cands, key=lambda b: b['pts']) if cands else None
            when = C.stamp(r['kick']) if r.get('kick') else 'kickoff'
            R['flags'].append(f'{r["player"]} is Q at {r["slot"]} — ' +
                              (f'if he is out, {best["player"]} ({best["pts"]:.1f}) takes the slot; decide before {when}' if best
                               else f'no healthy bench player can fill {r["slot"]}; decide before {when}'))
        # registry says IR, not drop (a season-ending injury in a league with IR slots)
        ir_free = st.cfg.ir_slots - len(st.ir())
        for r in st.mine:
            d = w.drop_ok.get(r['key'])
            if not d or not d.get('ir') or r['slot'] == 'IR': continue
            fill = None
            if r['slot'] not in ('BN', 'IR'):
                cands = [b for b in lu['rows'] if b['slot'] == 'BN' and b['designation'] not in UNUSABLE and b['designation'] != 'Q'
                         and (b['elig'] & st.cfg.accepts[r['slot']]) and b.get('pts') is not None]
                fill = max(cands, key=lambda b: b['pts']) if cands else None
            R['flags'].append(f'{r["player"]} at {r["slot"]}: IR MOVE — {d["why"][:90]} — ' +
                              (f'{ir_free} IR slot(s) free: move him to IR as soon as Yahoo tags him O or IR (tag now: {r["designation"]}); that frees a roster spot without losing him' if ir_free > 0
                               else 'no IR slot free — he is a drop only when the spot is needed') +
                              (f'; {fill["player"]} ({fill["pts"]:.1f}) takes {r["slot"]}' if fill else ''))
        dead = [r for r in st.mine if r['designation'] in UNUSABLE and r['slot'] != 'IR' and not (w.drop_ok.get(r['key']) or {}).get('ir')]
        for r in dead:
            h = w.hold.get(r['key'])
            d = w.drop_ok.get(r['key'])
            R['flags'].append(f'{r["player"]} [{r["designation"]}] holds a roster spot'
                              + (f' — HOLD: {h["call"][:80]}' if h
                                 else f' — verified: {d["why"][:80]}' if d
                                 else ' — why and for how long is NOT on record; not a drop until it is'))
        # ---- December / byes
        R['dec'] = []
        for r in st.mine:
            if r['slot'] == 'IR': continue
            idp = W._fam(r['pos']) in ('DL', 'LB', 'DB')
            e = WNd.env(r['tm'], idp=idp); rk, n = WNd.rank(r['tm'], idp=idp)
            if e is not None: R['dec'].append((r, e, rk, n, idp))
        R['byes'] = {w_: [r['player'] for r in st.starters() if r['tm'] in WNd.byes(w_)]
                     for w_ in WNd.weeks if w_ >= week}
        # ---- playoff DEF/K stash window.
        # Caleb, 2026-09-16: "teams will start holding multiple defenses later in
        # the season as they prepare for the playoffs." So the December streaming
        # edge is not something to collect in December -- by then the wire is
        # picked over. The edge is in getting there FIRST: acquire the best
        # week-15-17 DEF (and K) before the hoarding starts, roughly weeks 10-12,
        # and from then on a second DEF with a playoff schedule is a HOLD in BOTH
        # leagues, capped or not.
        R['stash'] = None
        if 8 <= week <= 13:
            po = []
            for fam, idp in (('DEF', True), ('K', False)):
                rows = []
                for c in w.by_fam.get(fam, []):
                    e = WNd.env(c['tm'], WN.PLAY, idp=idp)
                    if e is None: continue
                    rk, n = WNd.rank(c['tm'], WN.PLAY, idp=idp)
                    rows.append(dict(name=c['name'], tm=c['tm'], env=e, rank=rk, key=c['key']))
                rows.sort(key=lambda x: x['rank'])
                mine = [(r['player'], WNd.rank(r['tm'], WN.PLAY, idp=idp)[0]) for r in st.mine if W._fam(r['pos']) == fam]
                po.append(dict(fam=fam, wire=rows[:5], mine=mine))
            R['stash'] = po
        R['stream'] = w.stream_board(week + 1, WNd)
        R['stream_calls'] = []
        for fam, thresh in (('DEF', 2.0), ('K', 3.0)):
            b = (R['stream'] or {}).get(fam)
            if not b or b['edge'] is None or b['edge'] < thresh or not b['best_fa']: continue
            fa = b['best_fa']; cand = next(c for c in w.by_fam[fam] if c['key'] == fa['key'])
            # what it costs: a second DEF/K is the natural drop; else name the spot
            # the spare is the one worth LESS on the season, starter or not (Vikings
            # 09-29: the 49ers were in the slot and the card proposed dropping the
            # Vikings, the better defense, for a week-5 stream)
            pair = [r for r in st.mine if W._fam(r['pos']) == fam and r['slot'] != 'IR' and r['key'] not in w.hold]
            pair.sort(key=lambda r: ((sea_blend.get(r['key']) or {}).get('pts') or 0, r.get('pts') or 0))
            drop = pair[0] if len(pair) >= 2 else None
            ga = G.check('add', f'add {fa["name"]} ({fam}, week {week+1} stream)', player=fa['name'],
                         designation='none', sources=['vegas', 'sleeper'], pos=fam, value=cand['week'] or 0,
                         horizon='weekly', market_ready=True, roster_keys=st.roster_keys,
                         pool_keys=set(w.pool), pool_meta=w.meta, pulled=C.today().isoformat(),
                         league=lg, state=st)
            gd = w.gate_drop(drop, horizon='weekly') if drop else None
            # A stream is only a stream when it costs a spare DEF/K or an open
            # spot. If it would cost a real bench player it is a roster decision
            # judged on upside, and a one-week kicker edge does not win that.
            bench_full = len(st.bench()) >= st.cfg.bench
            if drop is None and bench_full:
                R['stream'][fam]['note'] = (f'{fa["name"]} is the best week-{week+1} {fam} on the wire, but the bench is '
                                            f'full and no spare {fam} to drop — taking him costs a real bench player, '
                                            f'which a one-week {fam} edge does not justify.')
                continue
            e = L.propose(lg, 'add', fa['name'], f'stream {fa["name"]} for week {week+1}' + (f', drop {drop["player"]}' if drop else ''),
                          detail=f'{fam}: {fa["tm"]} {fa["val"]:.1f} vs yours {b["best_mine"]["name"]} {b["best_mine"]["val"]:.1f} — edge {b["edge"]:.1f} implied pts',
                          evidence=['vegas'], verdict=ga.verdict if not gd else ('BLOCK' if 'BLOCK' in (ga.verdict, gd.verdict) else 'WARN' if 'WARN' in (ga.verdict, gd.verdict) else 'PASS'),
                          state=st, week=week)
            R['stream_calls'].append(dict(fam=fam, board=b, add=cand, drop=drop, gate_add=ga, gate_drop=gd, ledger=e))
        # ---- breakout scan: last completed week's usage vs next week's price
        from lib import breakout as BK
        R['breakout'] = BK.scan(st, P, season=sea_blend, lineup=lu)
        # ---- win probability: the lineup that wins two results, not the highest mean
        from lib import winprob as WP
        R['win'] = WP.evaluate(st, P, lu, lg, actuals=act)
        run['leagues'][lg] = R
    from lib import fab as F, steam as STM
    run['fab'] = F.model()
    run['windows'] = WNd
    run['proj'] = P
    # what the market learned between pulls: line movement since the week's first
    # pull, and rostered players whose markets were withdrawn (inactives)
    run['steam'] = STM.scan(P, {lg: R['state'] for lg, R in run['leagues'].items()}, week)
    for lg, R in run['leagues'].items():
        me = R['state'].me
        for m in run['steam']['moves']:
            for lg2, slot in m['mine']:
                if lg2 == lg and slot not in ('BN', 'IR') and m['pct'] <= -STM.THRESH:
                    R['flags'].append(f"{m['key'].title()} at {slot}: market cut his {m['stat']} {m['pct']:+.0%} since {run['steam']['baseline'].astimezone(C.ET):%a %-I:%M %p} ({m['before']:.0f} -> {m['after']:.0f}) — the projection may not have caught up")
        for g in run['steam']['gone']:
            for lg2, slot in g['mine']:
                if lg2 == lg and slot not in ('BN', 'IR'):
                    R['flags'].append(f"{g['player']} at {slot}: Kalshi WITHDREW his markets since the previous pull — treat as OUT until Yahoo says otherwise; move him before lock")
    # calibration: log every source's pregame number, report error vs actuals (09-26)
    from lib import calib as CB
    for lg, R in run['leagues'].items():
        try: CB.log(R['state'], P, week)
        except Exception as e: R['flags'].append(f'calibration log failed: {e!r}')
    try: run['calib'] = CB.report(week)
    except Exception as e: run['calib'] = None
    # rivals: how the other managers behave, from the logs (09-26)
    from lib import rivals as RV
    for lg, R in run['leagues'].items():
        try: R['rivals'] = RV.profiles(R['state'], P)
        except Exception as e: R['rivals'] = None; R['flags'].append(f'rivals model failed: {e!r}')
    # playoff leverage: every roster's strength, the rest of the season simulated (09-26)
    from lib import playoff as PO
    for lg, R in run['leagues'].items():
        try:
            # once this week's matchup is final the records already carry it: the
            # simulation starts NEXT week and there is no 'this game' to lever (09-29)
            acts = R.get('actuals') or {}
            over = bool(acts) and all(a['final'] for a in acts.values()) and all(a['final'] for k, a in acts.items() if a['owner'] == R['state'].me) \
                   and sum(1 for a in acts.values() if a['owner'] == R['state'].me) >= len(R['state'].starters()) - 1
            R['playoff'] = PO.evaluate(R['state'], P, week + 1 if over else week, opp=None if over else WP.matchup(lg, week), season=sea_blend if lg == 'BSB' else None, windows=WNd)
            if over: R['playoff']['over'] = True
        except Exception as e:
            R['playoff'] = None; R['flags'].append(f'playoff simulation failed: {e!r}')
    # next man up: who inherits each starter's role, and whether he is on the wire —
    # the Sunday-morning pickup nobody else is positioned for (09-26)
    from lib import nextup as NU, breakout as BK, usage as U
    for lg, R in run['leagues'].items():
        st, lu, w = R['state'], R['lineup'], R['wire']
        drops = [d for d in R['breakout'].get('drops', [])]
        R['nextup'] = NU.scan(st, P, w, lu, run['steam'], week, opp=WP.matchup(lg, week), drops=drops, waived=BK._on_waivers(lg))
        for a in R['nextup']['alerts']:
            r = a['row']
            if a['fa']:
                R['flags'].append(f"{r['player']} at {r['slot']} is {r['status']} — NEXT MAN UP {a['fa']['name']} is a free agent ({(a['fa']['pts'] or 0):.1f} this week); {NU.mechanics(lg, r['kick'])}" + (f"; the clean drop is {a['drop']}" if a['drop'] else '; no clean drop — it would cost a real player'))
    return run

def print_breakout(run):
    from lib import breakout as BK
    print('\n' + '=' * 88); print('BREAKOUTS — role before price'); print('=' * 88)
    for lg, R in run['leagues'].items():
        print(BK.fmt(R['breakout'], lg, top=12)); print()

def print_win(run):
    from lib import winprob as WP, fab as F, steam as STM
    print('\n' + '=' * 88); print('WIN PROBABILITY and FAB'); print('=' * 88)
    for lg, R in run['leagues'].items():
        print(WP.fmt(R['win'], lg)); print()
    print(F.fmt(run['fab']))
    print(); print(STM.fmt(run['steam']))
    from lib import nextup as NU, playoff as PO
    for lg, R in run['leagues'].items():
        if R.get('nextup'): print(); print(NU.fmt(R['nextup'], lg))
    for lg, R in run['leagues'].items():
        if R.get('playoff'): print(); print(PO.fmt(R['playoff'], lg))
    from lib import rivals as RV, calib as CB
    for lg, R in run['leagues'].items():
        if R.get('rivals'): print(); print(RV.fmt(R['rivals']))
    if run.get('calib'): print(); print(CB.fmt(run['calib']))

def print_week(run):
    for lg, R in run['leagues'].items():
        lu, st = R['lineup'], R['state']
        hr(f'{lg} · {st.me} · WEEK {run["week"]} LINEUP   current {lu["total_cur"]:.2f} → optimal {lu["total_opt"]:.2f}')
        print(f'  state {st.pulled[:16]} ({st.age_h:.0f}h)   {len(lu["changes"])} real change(s), {len(lu["perms"])} permutation(s) ignored')
        for u in lu['unknown']: print(f'  ??? {u["player"]} — no source covers him this week (unknown, not zero)')
        for c in R['calls']:
            if c['kind'] != 'start': continue
            ch, g, e = c['change'], c['gate'], c['ledger']
            tag = 'ALREADY SET' if e['status'] == 'already_set' else ('PROVISIONAL' if ch['provisional'] else g.verdict)
            print(f'\n  {ch["slot"]:8s} {ch["start"]["player"]} ({ch["start"]["pts"]:.2f}) over '
                  f'{ch["sit"]["player"] if ch["sit"] else "empty"} {ch["gain"]:+.2f}   [{tag}]  '
                  f'{C.stamp(ch["kick"]) if ch["kick"] else ""} · {ch["phase"]}')
            if ch['provisional']:
                why = []
                if ch['gain'] < LU.NOISE: why.append(f'inside the {LU.NOISE}-pt noise band')
                if not ch['start']['ready'] or (ch['sit'] and not ch['sit'].get('ready', True)): why.append('no player market posted yet for ' + ('both games' if not ch['start']['ready'] and ch['sit'] and not ch['sit'].get('ready', True) else (ch['start']['player'] if not ch['start']['ready'] else ch['sit']['player']) + "'s game"))
                if ch.get('reason'): why.append(ch['reason'])
                print(f'           not a move: {"; ".join(why)}. Re-check when the market posts.')
            print(g.render('     '))
        if not any(c['kind'] == 'start' for c in R['calls']):
            print('\n  LINEUP IS OPTIMAL — nobody on the bench outscores a starter.')

def print_wire(run):
    for lg, R in run['leagues'].items():
        w, st = R['wire'], R['state']
        hr(f'{lg} · WIRE   pool {len(w.pool)} · phantoms removed {len(w.phantoms)} · near-misses kept {len(w.near)}')
        for a, b, _, why in w.phantoms: print(f'  PHANTOM removed: {a} == {b} ({why})')
        for f in R['flags']: print(f'  ** {f}')
        print('\n  best available (✓ = week-1 usage verified; sorted usage-first):')
        fams = ['QB','RB','WR','TE','K','DEF'] if lg == 'BSB' else ['QB','RB','WR','TE','DL','LB','DB','K','DEF']
        for fam in fams:
            b = w.best(fam, 3)
            if not b: continue
            print(f'    {fam:3s} ' + ' | '.join(
                f'{c["name"][:18]} {c["tm"]}' + (f' {c["week"]:.1f}' if c['week'] is not None else ' ???')
                + (f'/{c["season"]:.0f}' if c['season'] else '') + (' ✓' if c['verified'] else '') for c in b))
        ups = [c for c in R['calls'] if c['kind'] == 'upgrade']
        sws = [c for c in R['calls'] if c['kind'] == 'swap']
        if ups:
            print('\n  WEEKLY UPGRADES (vs a current starter):')
            for c in ups:
                u = c['item']; print(f'\n    {u["fam"]} ADD {u["add"]["name"]} {u["add"]["week"]:.2f} over {u["over"]["player"]} {u["over"]["pts"]:.2f}  {u["gain"]:+.2f}')
                print(c['gate'].render('       '))
        if sws:
            print('\n  ROSTER CONSTRUCTION (bench spots vs the wire, usage-gated):')
            for c in sws:
                b = c['item']
                print(f'\n    DROP {b["drop"]["player"]} → ADD {b["add"]["name"]}   {b["gain"]:+.1f} ({b["basis"]}{", dead spot" if b["dead"] else ""})   ledger {c["ledger"]["status"]}')
                print(c['gate_add'].render('       ')); print(c['gate_drop'].render('       '))
        if not ups and not sws: print('\n  nothing on the wire clears the gate. Hold.')
        sb = R.get('stream')
        if sb:
            print(f'\n  WEEK {run["week"]+1} STREAMING — DEF by opponent implied total (low = good), K by own total (high = good)')
            for fam in ('DEF', 'K'):
                b = sb.get(fam)
                if not b: continue
                print(f'    {fam}:  ' + ' · '.join(f'{x["name"][:16]}{" *" if x["mine"] else ""} {x["val"]:.1f}' for x in b['rows'][:6] if x['val'] is not None))
                if b['byes']: print(f'         on bye: {", ".join(b["byes"])}')
                if b['best_mine'] and b['best_fa'] and b['edge'] is not None:
                    tag = 'FA is better by' if b['edge'] > 0 else 'yours is better by'
                    print(f'         best of yours {b["best_mine"]["name"]} {b["best_mine"]["val"]:.1f}  vs  best free {b["best_fa"]["name"]} {b["best_fa"]["val"]:.1f}  → {tag} {abs(b["edge"]):.1f}')

def print_season(run):
    WNd = run['windows']
    for lg, R in run['leagues'].items():
        hr(f'{lg} · SEASON   December environment (wk 15-17), IDP judged on OPPONENT')
        for r, e, rk, n, idp in sorted(R['dec'], key=lambda x: x[2]):
            print(f'  {r["player"][:22]:22s} {r["tm"]:4s} {"opp" if idp else "own"} {e:6.2f}  rank {rk:2d}/{n}'
                  + ('  << asset' if rk <= 8 else '  << thin' if rk >= n - 7 else ''))
        if R.get('stash'):
            print('\n  PLAYOFF STASH WINDOW (weeks 8-13) — best week-15-17 DEF/K still on the wire; take before the hoarding starts:')
            for p_ in R['stash']:
                print(f'    {p_["fam"]}: ' + ' · '.join(f'{x["name"][:16]} #{x["rank"]}' for x in p_['wire']) + f'   yours: ' + ', '.join(f'{n} #{r}' for n, r in p_['mine']))
        print('\n  byes ahead (your starters out):')
        for w_, who in R['byes'].items():
            if who: print(f'    wk {w_:2d}: {", ".join(who)}')

# ----------------------------------------------------------------- card
def cmd_card(run, publish=False):
    from lib import card as CARD
    html = CARD.render(run)
    p = '/home/claude/bsb2/lineup-card.html'
    # the sanity read: the card is checked as a manager would read it; a trip
    # refuses the card (the last one stands) and prints why (09-29, Burns)
    from lib import sanity as SAN
    bad = SAN.check(run, html)
    if bad:
        print('\n  CARD REFUSED — sanity read failed:')
        for b_ in bad: print(f'    [FAIL] {b_}')
        open('/home/claude/bsb2/data/out_sanity.txt', 'w').write('\n'.join(bad) + '\n')
        return None
    open(p, 'w').write(html)
    print(f'\n  card written: {p} ({len(html)} bytes) — sanity read clean')
    return p

def cmd_decline(lg, kind, player):
    L.decline(lg, kind, player); print(f'  recorded: Caleb declined {kind} {player} in {lg}')

# ----------------------------------------------------------------- main
if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if cmd == 'check':
        sys.exit(0 if cmd_check() else 1)
    if cmd == 'decline':
        cmd_decline(*sys.argv[2:5]); sys.exit(0)
    if cmd == 'status':
        cmd_status(); sys.exit(0)
    if not cmd_check(quiet=True):
        print('CHECK FAILED — refusing to run. `python3 ff.py check` for detail.'); sys.exit(1)
    run = build()
    if cmd in ('week', 'run'):   print_week(run)
    if cmd in ('wire', 'run'):   print_wire(run)
    if cmd in ('season', 'run'): print_season(run)
    if cmd in ('breakout', 'run'): print_breakout(run)
    if cmd in ('win', 'run'): print_win(run)
    if cmd in ('card', 'run'):   cmd_card(run)
