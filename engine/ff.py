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
  python3 ff.py outcomes   resolve and score every decision whose week is complete (idempotent)
  python3 ff.py bid <player> <amount>                 record your BSB bid (losing bids never reach the pump)
  python3 ff.py edge       the Tuesday EDGE REPORT: lineup edge, calls by kind, adds, calibration, rivals

Everything a command prints is also written to data/run/<stamp>.json so the card
and the next run read the same facts this run did.
"""
import sys, os, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # code from this checkout; data from lib/paths (FF_ROOT)
from lib import clock as C, state as S, ledger as L, lineup as LU, wire as W, gate as G
from lib import score as SC, windows as WN
from lib.project import Projections
from lib.names import key, team
from lib import paths as PATHS

D = PATHS.data('')
LEAGUES = ('BSB', 'HH')
# FF_FAST=1 (scenario harness, 10-04): build() skips the blocks that cost seconds and
# decide nothing on the Decide list — win probability (R['win'] = None: no P(win) on the
# Outlook tiles, no win-probability swap calls), calibration log/report, rivals (the
# Tier-A bid falls back to the FAB-ladder bands), the playoff simulation, the outcome
# ledger's update pass and the edge report. Never set in the pump or a live run.
FAST = os.environ.get('FF_FAST') == '1'
UNUSABLE = S.UNUSABLE

def hr(t=''): print('\n' + '=' * 96 + (f'\n{t}\n' + '=' * 96 if t else ''))

# ----------------------------------------------------------------- check
def cmd_check(quiet=False):
    r = subprocess.run([sys.executable, os.path.join(PATHS.code(), 'test_gate.py')], capture_output=True, text=True)
    ok = r.returncode == 0
    last = [l for l in r.stdout.splitlines() if 'behaved as required' in l]
    if not quiet:
        hr('CHECK'); print('  ' + (last[-1] if last else r.stdout[-300:]))
        if not ok: print(r.stdout)
    r2 = subprocess.run([sys.executable, os.path.join(PATHS.code(), 'test', 'test_system.py')], capture_output=True, text=True)
    ok2 = r2.returncode == 0
    last2 = [l for l in r2.stdout.splitlines() if 'behaved' in l or 'FAIL' in l]
    if not quiet:
        for l in last2[-6:]: print('  ' + l)
        if not ok2: print(r2.stdout[-2000:])
    # the scenario suite (harness, 10-04): frozen fixtures + mutations, each run in its
    # own temp FF_ROOT with FF_FAST=1 (~30 s on 2 cores). FF_SKIP_SCENARIOS=1 skips it.
    ok3, last3 = True, []
    if os.environ.get('FF_SKIP_SCENARIOS') != '1' and os.path.exists(os.path.join(PATHS.code(), 'scenarios', 'run.py')):
        r3 = subprocess.run([sys.executable, os.path.join(PATHS.code(), 'scenarios', 'run.py')], capture_output=True, text=True)
        ok3 = r3.returncode == 0
        last3 = [l for l in r3.stdout.splitlines() if l.startswith(('[FAIL]', '[XFAIL]', '[XPASS]', '        first mismatch')) or 'scenarios behaved' in l or 'SKIPPED' in l]
        if not ok3 and not last3: last3 = (r3.stdout + r3.stderr).splitlines()[-8:]
        if not quiet:
            for l in last3[-12:]: print('  ' + l)
    elif not (ok and ok2 and ok3):
        # quiet mode (ff.py run): still name what failed, so a refused run in the
        # pump's log says why (09-27: the Action refused with no detail on file)
        for l in [x for x in r.stdout.splitlines() + r2.stdout.splitlines() if x.startswith('[FAIL]') or 'Traceback' in x or 'Error' in x][:12]: print('  ' + l)
        for l in last + last2[-1:] + [x for x in last3 if not x.startswith('[XFAIL]') and 'known failure' not in x][-6:]: print('  ' + l)
    return ok and ok2 and ok3

# ----------------------------------------------------------------- status
def cmd_status(run=None):
    hr(f'STATUS  {C.stamp()}  ·  NFL week {C.nfl_week()}')
    from lib import rules as RU
    wd = RU.waiver_run_at()
    h = (wd - C.now()).total_seconds() / 3600
    if 0 < h < 30: print(f'  BSB waivers process {C.stamp(wd)} — {h:.1f}h from now')
    P = Projections(C.data_week())
    # ---- market freshness: the question "are we tracking Vegas?" must have a
    # numeric answer every time, not a feeling.
    print('\n  MARKETS ON DISK  (as-of from file content — lib/contract.manifest — never mtime)')
    from lib import contract as CT, ts as TS
    MF = CT.manifest(os.path.dirname(D.rstrip('/')))
    for fn, what, nm in (('kalshi.csv', 'Kalshi ladders', 'kalshi'), ('espn_games.csv', 'Vegas game lines', 'espn_games'),
                         ('espn_props.csv', 'DraftKings props', 'espn_props'), ('lines_wk10_18.csv', 'look-ahead lines', None),
                         (f'sleeper_off_wk{C.data_week()}.csv', 'Sleeper offense', 'sleeper_off'), (f'sleeper_idp_wk{C.data_week()}.csv', 'Sleeper IDP', 'sleeper_idp')):
        pth = D + fn
        if not os.path.exists(pth): print(f'     {what:18s} MISSING'); continue
        _t = (MF.get(nm) or {}).get('as_of') if nm else None
        _tt = TS.try_ts(_t, 'pump') if _t and _t != 'unknown' else None
        if _tt is None: print(f'     {what:18s} as-of unknown' + (' (posted look-ahead lines, static)' if nm is None else '')); continue
        age = (C.now() - _tt).total_seconds() / 3600
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

# ----------------------------------------------------------------- input contract
def contract_gate(week, now=None):
    """The input contract (lib/contract.py) runs before anything is decided.
    REFUSE: nothing is built — the codes are printed, data/out_contract.txt says why,
    and contract.Refused is raised (the pump keeps the previous card). DEGRADE: the
    result is installed as contract.RESULT, where gate G8 reads the real input ages
    and the add/drop block, and build() marks lineup calls provisional. WARN: printed
    here and listed on the card's Inputs panel."""
    from lib import contract as CT
    res = CT.install(CT.check(os.path.dirname(D.rstrip('/')), now or C.now(), week))
    try: open(D + 'out_contract.txt', 'w').write(res.text())
    except OSError: pass
    if res.violations: print(res.summary())
    if res.refused: raise CT.Refused(res)
    return res

def _contract_projections(P, CR):
    """C8 once Projections exists: no ladder of a game already kicked off is left in the pregame set."""
    from lib import contract as CT
    vs = CT.check_projections(P)
    if vs:
        CR.violations.extend(vs)
        try: open(D + 'out_contract.txt', 'w').write(CR.text())
        except OSError: pass
        print(CR.summary()); raise CT.Refused(CR)

def _contract_lineup(lu, CR):
    """degrade_lineup: a lineup change on degraded inputs is PROVISIONAL, with the reason.
    Replacing a starter Yahoo tags OUT stays firm (RUNBOOK 09-29: an OUT starter is a hole)."""
    from lib import rules as RU
    for c in lu['changes']:
        why = CR.lineup_reason(c.get('kick'))
        if not why or c['provisional']: continue
        if c.get('sit') and c['sit'].get('designation') in RU.UNUSABLE: continue
        c['provisional'] = True
        c['reason'] = (c['reason'] + '; ' if c.get('reason') else '') + f'inputs degraded ({why})'

def _contract_steam(steam, CR):
    """C11: a Kalshi pull that is incomplete against the previous one cannot say a
    player's markets were WITHDRAWN — the 'gone' list is not used."""
    if CR.steam_gone_off and steam.get('gone'):
        steam['gone_suppressed'] = steam['gone']; steam['gone'] = []
        steam['contract'] = f'withdrawn markets not inferred: {CR.steam_gone_off}'

# ----------------------------------------------------------------- week
def build(week=None):
    """Assemble the whole run for both leagues. Returns the run dict."""
    week = week or C.data_week()
    if not FAST: outcomes_update()               # outcome ledger: resolve/score what is due (idempotent; never raises)
    CR = contract_gate(week)                     # inputs are checked before anything is decided
    P = Projections(week); WNd = WN.Windows()
    _contract_projections(P, CR)
    sea = json.load(open(D + 'season_blend.json')) if os.path.exists(D + 'season_blend.json') else {}
    sea_blend = sea
    run = dict(stamp=C.stamp(), iso=C.iso(), week=week, leagues={})
    run['contract'] = CR
    from lib import actuals as AC
    for lg in LEAGUES:
        st = S.load(lg); L.reconcile(st)
        act = AC.load(lg, week)
        lu = LU.solve(st, P, actuals=act)
        _contract_lineup(lu, CR)
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
                          provisional=c['provisional'], state=st, week=week,
                          resolves_at=C.iso(o['kick']) if o['kick'] else None)
            R['calls'].append(dict(kind='start', change=c, gate=g, ledger=e))
        # ---- wire: weekly upgrades (DEF/K etc) and roster construction
        for u in w.upgrade_board(lu)[:3]:
            g = w.gate_add(u['add'], horizon='weekly' if u['fam'] in ('DEF', 'K') else 'season')
            e = L.propose(lg, 'add', u['add']['name'], f'add {u["add"]["name"]} ({u["fam"]}) over {u["over"]["player"]}',
                          detail=f'{u["gain"]:+.2f}/wk', evidence=u['add']['line']['sources'],
                          verdict=g.verdict, state=st)
            R['calls'].append(dict(kind='upgrade', item=u, gate=g, ledger=e))
        # THIS week's DEF/K off the wire when it costs nothing: an open spot or a
        # spare DEF/K that is not a hold (Vikings +12.2 over the Chiefs, HH 10-01).
        # Decided here, once, so the breakout scan does not hand the same open spot
        # to a long-term add in the same breath.
        R['week_upgrade'] = None
        open_ = len(st.cfg.slots) + st.cfg.bench - sum(1 for r in st.mine if r['slot'] != 'IR')
        for c in R['calls']:
            if c['kind'] != 'upgrade' or c['ledger']['status'] != 'proposed': continue
            u = c['item']; over = u['over']
            if u['fam'] not in ('DEF', 'K') or u['gain'] < 4.0 or c['gate'].verdict == 'BLOCK': continue
            if over.get('final') or over.get('live') or over.get('phase') == 'locked': continue
            spare = [r for r in st.mine if W._fam(r['pos']) == u['fam'] and r['slot'] == 'BN' and r['key'] not in w.hold and r['key'] != over['key']]
            if open_ <= 0 and not spare: continue
            R['week_upgrade'] = dict(call=c, open=open_ > 0, drop=None if open_ > 0 else spare[0])
            break
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
        R['stream_holes'] = []          # next week's DEF/K slot with EVERY one of mine on bye (10-02: Butker, HH week 5)
        for fam, thresh in (('DEF', 2.0), ('K', 3.0)):
            b = (R['stream'] or {}).get(fam)
            if b and b['best_fa'] and b['best_mine'] is None and b.get('byes'):
                R['stream_holes'].append((fam, b)); continue
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
        _open_now = len(st.cfg.slots) + st.cfg.bench - sum(1 for r in st.mine if r['slot'] != 'IR')
        _reserved = (1 if (R.get('week_upgrade') or {}).get('open') else 0) + min(len(R.get('stream_holes', [])), max(0, _open_now - (1 if (R.get('week_upgrade') or {}).get('open') else 0)))
        R['breakout'] = BK.scan(st, P, season=sea_blend, lineup=lu, reserve_open=_reserved)
        # a bye HOLE next week is not an edge to weigh, it is an empty slot: the best
        # free DEF/K goes in, and the drop is the open spot, the spare at that family,
        # or the breakout scan's cheapest clean drop (never a hold or a handcuff)
        for fam, b in R.get('stream_holes', []):
            swap_after = None
            fa = b['best_fa']; cand = next((c for c in w.by_fam[fam] if c['key'] == fa['key']), None)
            if not cand: continue
            open_ = len(st.cfg.slots) + st.cfg.bench - sum(1 for r in st.mine if r['slot'] != 'IR')
            spare = [r for r in st.mine if W._fam(r['pos']) == fam and r['slot'] == 'BN' and r['key'] not in w.hold]
            drop = None; gd = None
            if open_ <= 0:
                if spare: drop = spare[0]; gd = w.gate_drop(drop, horizon='weekly')
                else:
                    # the breakout scan's cheapest clean drop, with the gate it already passed
                    dc = next((d for d in (R['breakout'] or {}).get('drops', []) if d['tier'] >= 1 and not str(d['row']['key']).startswith('__')), None)
                    if dc is not None: drop = dc['row']; gd = dc.get('gate')
                    # no clean drop on the bench: the move is the bye player HIMSELF, once
                    # his game this week is over (a K/DEF is a one-for-one swap)
                    else:
                        byer = next((r for r in st.mine if r['player'] in b['byes']), None)
                        if byer is None: continue
                        # Yahoo locks a started player for the WEEK (Caleb, 09-28: 'I can't move
                        # Burns to IR yet because I started him this week'): the swap is Tuesday
                        drop = byer; gd = None
                        swap_after = C.week_start(week + 1)
            ga = G.check('add', f'add {fa["name"]} ({fam}, week {week+1} bye cover)', player=fa['name'],
                         designation='none', sources=['vegas', 'sleeper'], pos=fam, value=cand['week'] or 0,
                         horizon='weekly', market_ready=True, roster_keys=st.roster_keys,
                         pool_keys=set(w.pool), pool_meta=w.meta, pulled=C.today().isoformat(), league=lg, state=st)
            if gd and gd.verdict == 'BLOCK': continue
            e = L.propose(lg, 'add', fa['name'], f'bye cover: {fa["name"]} for week {week+1}' + (f', drop {drop["player"]}' if drop else ''),
                          detail=f'{fam}: {", ".join(b["byes"])} on bye week {week+1}; {fa["tm"]} {fa["val"]:.1f} is the best free {fam} on posted lines',
                          evidence=['vegas'], verdict=ga.verdict if not gd else ('BLOCK' if 'BLOCK' in (ga.verdict, gd.verdict) else 'WARN' if 'WARN' in (ga.verdict, gd.verdict) else 'PASS'),
                          state=st, week=week)
            bb = dict(b, best_mine=dict(name=' / '.join(b['byes']) + ' (bye)', val=0.0), edge=fa['val'])
            R['stream_calls'].append(dict(fam=fam, board=bb, add=cand, drop=drop, gate_add=ga, gate_drop=gd, ledger=e, hole=True,
                                          swap_after=locals().get('swap_after'), alternates=[x['name'] for x in b['rows'] if not x['mine'] and x['val'] is not None][1:3]))
            # the drop is spent: a breakout add that wanted the same player waits
            if drop:
                for x in (R['breakout'] or {}).get('rows', []):
                    if x['move'].get('drop') == drop['player']:
                        x['move'] = dict(x['move'], verb='WAIT', when='no clean drop left', drop=None,
                                         why=f"{drop['player']} is the spot, and it goes to next week's bye cover ({fa['name']}) first; re-check after the game")
                R['breakout']['summary'] = R['breakout']['summary']
        # ---- win probability: the lineup that wins two results, not the highest mean
        from lib import winprob as WP
        R['win'] = None if FAST else WP.evaluate(st, P, lu, lg, actuals=act)
        run['leagues'][lg] = R
    from lib import fab as F, steam as STM
    run['fab'] = F.model()
    run['windows'] = WNd
    run['proj'] = P
    # what the market learned between pulls: line movement since the week's first
    # pull, and rostered players whose markets were withdrawn (inactives)
    run['steam'] = STM.scan(P, {lg: R['state'] for lg, R in run['leagues'].items()}, week)
    _contract_steam(run['steam'], CR)
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
        if FAST: break
        try: CB.log(R['state'], P, week)
        except Exception as e: R['flags'].append(f'calibration log failed: {e!r}')
    try: run['calib'] = None if FAST else CB.report(week)
    except Exception as e: run['calib'] = None
    # rivals: how the other managers behave, from the logs (09-26)
    from lib import rivals as RV
    for lg, R in run['leagues'].items():
        if FAST: R['rivals'] = None; continue
        try: R['rivals'] = RV.profiles(R['state'], P)
        except Exception as e: R['rivals'] = None; R['flags'].append(f'rivals model failed: {e!r}')
    # playoff leverage: every roster's strength, the rest of the season simulated (09-26)
    from lib import playoff as PO
    for lg, R in run['leagues'].items():
        if FAST: R['playoff'] = None; continue
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
    shadow_plan(run)
    outcomes_record(run)
    write_plan_json(run)
    return run

# ----------------------------------------------------------------- outcome ledger + edge report (10-04)
def outcomes_update():
    """Start of build(): bring the outcome ledger up to date — import the ledger's
    historical calls once, resolve every decision whose deadline passed, score every
    horizon whose week is complete. Idempotent; a failure is printed, never raised."""
    try:
        from lib import outcomes as OUT
        OUT.import_ledger()
        return OUT.update()
    except Exception as e:
        print(f'  outcome ledger update failed (run continues): {e!r}')
        return None

def outcomes_record(run):
    """End of build(): every decision point this run produced -> data/outcomes/decisions.jsonl,
    then the edge report for the card. Additive; never fails the run."""
    try:
        from lib import outcomes as OUT
        run['outcomes'] = OUT.record(run)
    except Exception as e:
        import traceback
        run['outcomes'] = f'record failed: {e!r}'
        print(f'  outcome ledger record failed (run continues): {e!r}\n' + traceback.format_exc()[-600:])
    if FAST: run['edge'] = None; return
    try:
        from lib import edge as EDGE
        run['edge'] = EDGE.report(run=run)
    except Exception as e:
        run['edge'] = None
        print(f'  edge report failed (card renders without it): {e!r}')

def cmd_outcomes():
    from lib import outcomes as OUT
    hr(f'OUTCOME LEDGER  {C.stamp()}')
    print(f'  ledger import: {OUT.import_ledger()}')
    for k, v in OUT.update().items(): print(f'  {k}: {v}')
    print(f'  stores: {OUT.summary()}')

def cmd_bid(player, amount):
    from lib import outcomes as OUT
    r = OUT.bid(player, amount)
    print(f"  recorded: your BSB bid ${r['my_bid']} on {r['player']} for the week-{r['run_week']} run ({r['run_at']})"
          + (f" — the engine recommended ${r['recommended_bid']}" if r.get('recommended_bid') is not None else ''))

def cmd_edge():
    from lib import outcomes as OUT, edge as EDGE
    try:
        OUT.import_ledger(); OUT.update()
    except Exception as e:
        print(f'  outcome ledger update failed: {e!r}')
    rep = EDGE.report()
    print(EDGE.text(rep))

# ----------------------------------------------------------------- normalized plan (harness, 10-04)
def _gcodes(*gs):
    """Gate codes of every non-PASS check: ['G1:BLOCK', 'G13-injury:WARN', ...]."""
    out = []
    for g in gs:
        if g is None: continue
        if isinstance(g, dict):           # planner gate dicts
            for c in g.get('checks', []) or []:
                if c.get('status') in ('WARN', 'BLOCK'): out.append(f"{c.get('gate')}:{c.get('status')}")
            continue
        for gate, st_, _m in getattr(g, 'checks', []):
            if st_ in ('WARN', 'BLOCK'): out.append(f'{gate}:{st_}')
    return out

def _verdict(*gs):
    vs = [g.verdict for g in gs if g is not None and hasattr(g, 'verdict')]
    return 'BLOCK' if 'BLOCK' in vs else 'WARN' if 'WARN' in vs else 'PASS' if vs else None

def _nm(r):
    if r is None: return None
    if isinstance(r, str): return r
    return r.get('player') or r.get('name')

def _decide_labels(html):
    """The Decide tiles as a manager reads them: one plain-text label per tile."""
    import re as _re, html as _h
    if not html or '<h2>Decide</h2>' not in html: return []
    i = html.index('<h2>Decide</h2>'); j = html.find('<h2>Outlook</h2>', i)
    sec = html[i:j if j > 0 else len(html)]
    parts = _re.split(r'<div class="dcard(?=[ "])', sec)[1:]
    out = []
    for p in parts:
        t = _h.unescape(_re.sub(r'\s+', ' ', _re.sub(r'<[^>]+>', ' ', '<div class="dcard' + p))).strip()
        out.append(t[:240])
    return out

def plan_json(run, html=None):
    """data/plan.json — ONE normalized plan per run, for diffing (scenario harness):
    per league the engine's lineup (slot -> player), every action from the CURRENT paths
    (lineup calls, weekly upgrades, bench swaps, streams / bye covers, this week's DEF/K,
    breakout rows, IR flags, next-man-up alerts) with kind/add/drop/slot/start/sit/when/
    bid/verdict/gate codes/status, the blocked calls with their codes, the shadow
    planner's moves and rejections (plan_{LG}.json), and the Decide tile labels."""
    import re as _re
    from lib import plan as PL
    out = dict(week=run['week'], now=run['iso'], fast=FAST, leagues={})
    CR = run.get('contract')
    out['contract'] = dict(codes=sorted({v.code for v in getattr(CR, 'violations', [])}),
                           refused=sorted({v.code for v in getattr(CR, 'refused', [])})) if CR is not None else None
    for lg, R in run['leagues'].items():
        st, lu = R['state'], R['lineup']
        A = []
        def act(kind, **kw):
            d = dict(kind=kind, add=None, drop=None, slot=None, start=None, sit=None, when=None, bid=None,
                     verdict=None, gates=[], status=None, provisional=False, subject=None)
            d.update(kw); d['subject'] = d['subject'] or d['add'] or d['start'] or d['drop']; A.append(d)
        for c in R.get('calls', []):
            e = c.get('ledger') or {}
            if c['kind'] == 'start':
                ch = c['change']
                act('start', slot=ch['slot'], start=_nm(ch['start']), sit=_nm(ch['sit']), verdict=c['gate'].verdict,
                    gates=_gcodes(c['gate']), status=e.get('status'), provisional=bool(ch['provisional']),
                    when=ch.get('phase'), gain=round(ch['gain'], 2), reason=ch.get('reason') or '')
            elif c['kind'] == 'upgrade':
                u = c['item']
                act('upgrade', add=u['add']['name'], sit=_nm(u['over']), verdict=c['gate'].verdict, gates=_gcodes(c['gate']),
                    status=e.get('status'), fam=u['fam'], gain=round(u['gain'], 2))
            elif c['kind'] == 'swap':
                b = c['item']
                act('swap', add=b['add']['name'], drop=_nm(b['drop']), verdict=_verdict(c['gate_add'], c['gate_drop']),
                    gates=_gcodes(c['gate_add'], c['gate_drop']), status=e.get('status'))
        wu = R.get('week_upgrade')
        if wu:
            u = wu['call']['item']
            act('week_upgrade', add=u['add']['name'], drop=_nm(wu.get('drop')), sit=_nm(u['over']), fam=u['fam'],
                verdict=wu['call']['gate'].verdict, gates=_gcodes(wu['call']['gate']), status=wu['call']['ledger'].get('status'),
                when='now', open=bool(wu.get('open')))
        for c in R.get('stream_calls', []):
            act('bye_cover' if c.get('hole') else 'stream', add=c['add']['name'], drop=_nm(c.get('drop')), fam=c['fam'],
                when=('Tuesday ' + C.iso(c['swap_after'])) if c.get('swap_after') else 'now',
                verdict=_verdict(c.get('gate_add'), c.get('gate_drop')), gates=_gcodes(c.get('gate_add'), c.get('gate_drop')),
                status=(c.get('ledger') or {}).get('status'))
        for fam, b in R.get('stream_holes', []):
            pass                                   # holes become bye_cover calls above (or are skipped on a BLOCKed drop)
        for x in (R.get('breakout') or {}).get('rows', []):
            m = x['move']
            if x.get('tier') not in ('A', 'B') and m['verb'] not in ('ADD', 'ADD-DEAD', 'BLOCKED'): continue
            bid = _re.search(r'bid \$(\d+)', m.get('when') or '')
            g = x.get('gate')
            act('breakout', add=x['name'], drop=m.get('drop'), verb=m['verb'], tier=x.get('tier'), when=m.get('when'),
                bid=int(bid.group(1)) if bid else None, verdict=(g.verdict if g is not None else None), gates=_gcodes(g),
                why=(m.get('why') or '')[:200])
        for f_ in R.get('flags', []):
            if 'IR MOVE' in f_:
                act('ir', drop=None, subject=f_.split(' at ')[0], text=f_[:200])
        for a in (R.get('nextup') or {}).get('alerts', []):
            act('nextup', add=(a['fa'] or {}).get('name') if a.get('fa') else None, drop=a.get('drop'),
                sit=_nm(a['row']), subject=(a['fa'] or {}).get('name') if a.get('fa') else _nm(a['row']))
        blocked = [dict(kind=a['kind'], subject=a['subject'], add=a['add'], drop=a['drop'],
                        gates=[g for g in a['gates'] if g.endswith(':BLOCK')]) for a in A
                   if a.get('verdict') == 'BLOCK' or a.get('verb') == 'BLOCKED']
        p = (run.get('plans') or {}).get(lg)
        if isinstance(p, PL.Plan):
            pj = json.loads(p.to_json())
            planner = dict(moves=[dict(kind=m['kind'], add=m.get('add_name'), drop=m.get('drop_name'),
                                       ir=m.get('ir_name'), slot=m.get('slot'), start=m.get('start'), sit=m.get('sit'),
                                       when=m.get('when'), provisional=m.get('provisional'), J=m.get('J'),
                                       txns=[PL._txn_txt(t) for t in m.get('txns', [])],
                                       gates=_gcodes(*(m.get('gates') or {}).values()))
                                  for m in pj.get('moves', [])],
                           rejected=[dict(name=r.get('name'), reason=(r.get('reason') or '')[:240]) for r in pj.get('rejected', [])],
                           lineup_after=(pj.get('lineup_after') or {}).get('slots'))
        else:
            planner = dict(error=str(p)[:400] if p is not None else 'planner did not run')
        out['leagues'][lg] = dict(
            me=st.me, pulled=st.pulled, others_pulled=getattr(st, 'others_pulled', None),
            lineup={s: _nm(r) for s, r in lu['optimal'].items()},
            current={s: _nm(r) for s, r in lu['current'].items()},
            actions=A, blocked=blocked, flags=list(R.get('flags', [])), planner=planner)
    out['decide'] = _decide_labels(html) if html is not None else None
    return out

def write_plan_json(run, html=None):
    """End of build(): data/plan.json (normalized plan). The Decide labels need the
    rendered card: build() renders it once here and cmd_card reuses run['card_html']."""
    try:
        if html is None:
            from lib import card as CARD
            try: html = CARD.render(run); run['card_html'] = html
            except Exception as e: html = None; run['card_render_error'] = repr(e)
        pj = plan_json(run, html)
        open(D + 'plan.json', 'w').write(json.dumps(pj, indent=1, sort_keys=True, default=str))
        run['plan_json'] = pj
    except Exception as e:
        import traceback
        print(f'  plan.json failed (run continues): {e!r}\n' + traceback.format_exc()[-800:])

def cmd_plan_json():
    """ff.py plan-json: build (no check), write data/plan.json, print it."""
    run = build()
    print(json.dumps(run.get('plan_json'), indent=1, sort_keys=True, default=str))

# ----------------------------------------------------------------- planner (shadow mode)
def _card_calls(run, lg):
    """The live card's Decide calls for one league, normalised to
    (kind, add, drop, text) — what the planner is compared against."""
    from lib.names import key as _k
    R = run['leagues'][lg]; out = []
    for c in R.get('calls', []):
        if c['ledger']['status'] != 'proposed': continue
        if c['kind'] == 'start':
            ch = c['change']
            if ch['provisional']: continue
            out.append(('lineup', _k(ch['start']['player']), _k(ch['sit']['player']) if ch['sit'] else None,
                        f"lineup: {ch['slot']} start {ch['start']['player']} over {ch['sit']['player'] if ch['sit'] else 'empty'} ({ch['gain']:+.2f})"))
        elif c['kind'] == 'swap':
            b = c['item']
            out.append(('swap', b['add']['key'], b['drop']['key'], f"swap: drop {b['drop']['player']} -> add {b['add']['name']} ({b['gain']:+.1f} {b['basis']})"))
    for c in R.get('stream_calls', []):
        if c['ledger']['status'] != 'proposed': continue
        out.append(('stream', c['add']['key'], c['drop']['key'] if c['drop'] else None,
                    f"{'bye cover' if c.get('hole') else 'stream'}: add {c['add']['name']} ({c['fam']})" + (f", drop {c['drop']['player']}" if c['drop'] else '') + (' (Tuesday)' if c.get('swap_after') else '')))
    wu = R.get('week_upgrade')
    if wu:
        u = wu['call']['item']
        out.append(('week_upgrade', u['add']['key'], wu['drop']['key'] if wu.get('drop') else None,
                    f"this week's {u['fam']}: add {u['add']['name']} " + (f"drop {wu['drop']['player']}" if wu.get('drop') else 'into the open spot') + f", start over {u['over']['player']}"))
    for x in (R.get('breakout') or {}).get('rows', []):
        m = x['move']
        if m['verb'] not in ('ADD', 'ADD-DEAD'): continue
        d = m.get('drop'); dk = None
        if d and not str(d).startswith(('an open', 'the spot')): dk = _k(d)
        out.append(('breakout', x['key'], dk, f"breakout {x['tier']}: add {x['name']} " + (f"into {d}" if d and dk is None else f"drop {d}" if d else '')))
    for f_ in R.get('flags', []):
        if 'IR MOVE' in f_:
            nm = f_.split(' at ')[0]
            out.append(('ir', None, _k(nm), f"IR move: {nm}"))
    for a in (R.get('nextup') or {}).get('alerts', []):
        if a.get('fa'):
            out.append(('nextup', a['fa']['key'], _k(a['drop']) if a.get('drop') else None,
                        f"next man up: add {a['fa']['name']} for {a['row']['player']}" + (f", drop {a['drop']}" if a.get('drop') else '')))
    return out

def plan_diff(run):
    """Plan moves vs the live card's Decide calls, both leagues -> text."""
    from lib import plan as PL
    L = [f"PLAN DIFF — week {run['week']} — {run['stamp']}  (shadow mode: the card still shows the live calls; FF_PLANNER=1 renders the plan)",
         f"objective: J = {PL.W_NOW}*dS_W + {PL.W_NEXT}*dS_W1 + {PL.W_REST}*dS_rest(mean of weeks W+2..17) + {PL.W_BOOM}*d_bench_boom"
         f" - acq ({PL.K_ACQ}) - {PL.K_FAB}*bid - {PL.K_CHURN}*txns; ship at J >= {PL.SHIP_J}"]
    for lg in LEAGUES:
        R = run['leagues'][lg]; p = (run.get('plans') or {}).get(lg)
        L.append(''); L.append(f'== {lg} ' + '=' * 80)
        if p is None or isinstance(p, Exception) or isinstance(p, str):
            L.append(f'  planner FAILED: {p!r}'); continue
        card = _card_calls(run, lg)
        pm = []
        for m in p.moves:
            if m['kind'] == 'add': pm.append((m['add_key'], next((t['key'] for t in m['txns'] if t['op'] == 'drop'), None), m))
            elif m['kind'] == 'ir': pm.append((None, m['txns'][0]['key'], m))
            else: pm.append((m['txns'][0]['key'], next((t['key'] for t in m['txns'] if t['op'] == 'bench'), None), m))
        rej = {r['key']: r for r in p.rejected}
        used = set()
        L.append('  card Decide calls vs the plan:')
        if not card: L.append('    (the card has no Decide call in this league)')
        for kind, a, d, txt in card:
            hit = next((i for i, (pa, pd, m) in enumerate(pm) if i not in used and ((a is not None and pa == a) or (a is None and m['kind'] == 'ir' and pd == d))), None)
            if hit is not None:
                used.add(hit); m = pm[hit][2]
                same_drop = (pm[hit][1] == d)
                L.append(f"    BOTH      {txt}")
                L.append(f"              plan: {' ; '.join(PL._txn_txt(t) for t in m['txns'])}  [{m['when']}]" + ('' if same_drop else '  <- different spot'))
                if m.get('value_terms') and m['kind'] == 'add': L.append('              ' + PL.fmt_terms(m['value_terms']))
            else:
                r = rej.get(a)
                L.append(f"    CARD ONLY {txt}")
                L.append('              planner: ' + (r['reason'] if r else 'not a planner candidate (no producer raised him)' if a else 'no matching planner move'))
        for i, (pa, pd, m) in enumerate(pm):
            if i in used: continue
            L.append(f"    PLAN ONLY {'PROVISIONAL ' if m['provisional'] else ''}[{m['kind']}] {' ; '.join(PL._txn_txt(t) for t in m['txns'])}  [{m['when']}]")
            if m.get('value_terms') and m['kind'] == 'add': L.append('              ' + PL.fmt_terms(m['value_terms']))
            for r_ in m['reasons'][:4]: L.append(f'              - {r_}')
        L.append(f"  budgets: {json.dumps(p.budgets, default=str)}")
        L.append(f"  final lineup week {p.week}: {p.lineup_after['total']:.1f} pts (optimal before moves {p.lineup_after['optimal_before_moves']:.1f})"
                 + (f" · P(beat opp) {p.winprob['p_opp']:.0%}" if isinstance(p.winprob, dict) and p.winprob.get('p_opp') is not None else '')
                 + (f" · P(beat median) {p.winprob['p_med']:.0%}" if isinstance(p.winprob, dict) and p.winprob.get('p_med') is not None else ''))
        L.append(f'  considered and rejected ({len(p.rejected)}):')
        for r in sorted(p.rejected, key=lambda r: (-(r['J'] if r['J'] is not None else -1e9), r['key']))[:25]:
            L.append(f"    - {r['name']}: {r['reason'][:230]}")
        if p.excluded:
            L.append('  not a clean drop: ' + '; '.join(f"{e['player']} ({e['reason'][:70]})" for e in p.excluded))
        unv = [e['rule'] for e in p.mechanics if not e['verified']]
        if unv: L.append('  UNVERIFIED mechanics: ' + ' | '.join(unv))
    return '\n'.join(L) + '\n'

def shadow_plan(run):
    """Shadow mode (additive): the unified planner runs on the assembled run for both
    leagues and writes data/plan_{LG}.json and data/plan_diff.txt. It never changes
    run['leagues'] and never writes the ledger; a planner failure is recorded, not raised."""
    from lib import plan as PL
    run['plans'] = {}
    for lg in LEAGUES:
        try:
            p = PL.plan(run, lg)
            run['plans'][lg] = p
            open(D + f'plan_{lg}.json', 'w').write(p.to_json())
        except Exception as e:
            import traceback
            run['plans'][lg] = f'{e!r}\n' + traceback.format_exc()
    try:
        txt = plan_diff(run)
    except Exception as e:
        import traceback
        txt = f'plan_diff failed: {e!r}\n' + traceback.format_exc()
    try:
        from lib import sanity as SAN
        sim = SAN.check_plan(run)
        txt += '\nplan simulation (sanity check 11): ' + ('clean — legal at every step, each spot once, budgets held' if not sim else '; '.join(sim)) + '\n'
    except Exception as e:
        txt += f'\nplan simulation failed to run: {e!r}\n'
    run['plan_diff'] = txt
    try: open(D + 'plan_diff.txt', 'w').write(txt)
    except OSError: pass
    return run['plans']

def print_plan(run):
    hr('PLANNER (shadow) — plan vs the live card')
    print(run.get('plan_diff') or '  planner did not run')

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
    html = run.get('card_html') or CARD.render(run)
    p = os.path.join(PATHS.root(), 'lineup-card.html')
    # the sanity read: the card is checked as a manager would read it; a trip
    # refuses the card (the last one stands) and prints why (09-29, Burns)
    from lib import sanity as SAN
    bad = SAN.check(run, html)
    if bad:
        print('\n  CARD REFUSED — sanity read failed:')
        for b_ in bad: print(f'    [FAIL] {b_}')
        open(D + 'out_sanity.txt', 'w').write('\n'.join(bad) + '\n')
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
    if cmd == 'outcomes':
        cmd_outcomes(); sys.exit(0)
    if cmd == 'bid':
        cmd_bid(sys.argv[2], sys.argv[3]); sys.exit(0)
    if cmd == 'edge':
        cmd_edge(); sys.exit(0)
    if cmd == 'plan-json':
        cmd_plan_json(); sys.exit(0)
    if cmd == 'scenarios':
        sys.path.insert(0, os.path.join(PATHS.code(), 'scenarios'))
        import run as _SR
        sys.exit(_SR.main(sys.argv[2:]))
    if not cmd_check(quiet=True):
        print('CHECK FAILED — refusing to run. `python3 ff.py check` for detail.'); sys.exit(1)
    from lib import contract as CT
    try:
        run = build()
    except CT.Refused as e:
        print('INPUT CONTRACT REFUSED — nothing decided; the previous card stands.')
        for v in e.result.refused: print(f'  [{v.code}] {v.msg}')
        print(f'  detail: {D}out_contract.txt'); sys.exit(1)
    if cmd in ('week', 'run'):   print_week(run)
    if cmd in ('wire', 'run'):   print_wire(run)
    if cmd in ('season', 'run'): print_season(run)
    if cmd in ('breakout', 'run'): print_breakout(run)
    if cmd in ('win', 'run'): print_win(run)
    if cmd in ('plan', 'run'): print_plan(run)
    if cmd in ('card', 'run'):   cmd_card(run)
