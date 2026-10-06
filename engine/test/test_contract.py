#!/usr/bin/env python3
"""INPUT CONTRACT REGRESSION — every invariant C1-C17 replayed on the input that broke it.

Fixtures (test/fixtures/contract/, built by make_fixtures.py from the engine's own
data at the 10-04 baseline and the pump's git history) are minimal roots. Each case
runs contract.check(root, now, week) on a fixture, or on a copy of the clean 10-04
base with one real failure planted in it, and asserts the exact code fires with the
exact severity — and that the clean base does not fire it. Pure modules only: no
network, no /home/claude/bsb2, a fixed `now` per case, so the suite does not rot
as the calendar moves.

  python3 test/test_contract.py
"""
import csv, io, json, os, re, shutil, subprocess, sys, tempfile, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, ENGINE)
from lib import contract as CT, rules as RU, ts as T, clock as C, state as ST
from lib.names import key

FX = os.path.join(HERE, 'fixtures', 'contract')
ET = C.ET
bad = 0; total = 0
def case(label, ok, detail=''):
    global bad, total
    total += 1
    if not ok: bad += 1
    print(f'[{"OK " if ok else "FAIL"}] {label}' + (f'  — {detail}' if detail and not ok else ''))

def at(y, mo, d, h=0, mi=0): return dt.datetime(y, mo, d, h, mi, tzinfo=ET)
NOW = at(2026, 10, 4, 8, 30)            # the 10-04 base: Sunday morning, before the 9:30 London game

_tmp = []
def root(*layers, edit=None):
    """A temp root: base fixture + layers (fixture names) copied over it, then edit(data_dir)."""
    r = tempfile.mkdtemp(prefix='fxc_'); _tmp.append(r)
    for L in layers:
        src = os.path.join(FX, L)
        for dp, _, fs in os.walk(src):
            for f in fs:
                s = os.path.join(dp, f); t = os.path.join(r, os.path.relpath(s, src))
                os.makedirs(os.path.dirname(t), exist_ok=True); shutil.copy(s, t)
    if edit: edit(os.path.join(r, 'data'))
    return r

def run(r, now=NOW, week=4, only=None, repo=''):
    return CT.check(r, now=now, week=week, only=only, repo=repo)

def fired(res, code, sev):
    return [v for v in res.violations if v.code == code and v.severity == sev]

def rw_csv(path, fn):
    rows = list(csv.DictReader(open(path))); fields = list(rows[0].keys())
    rows = fn(rows)
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)

print('=' * 88); print('INPUT CONTRACT REGRESSION'); print('=' * 88)

# ---------------------------------------------------------------- the clean base
B = run(root('base'))
case('the clean 10-04 base passes (no REFUSE, no DEGRADE)', B.ok and not [v for v in B.violations if v.severity == CT.DEGRADE], B.codes_line())
case('manifest: every as-of comes from content, none is unknown on the base',
     all(m['as_of'] != 'unknown' for nm, m in B.manifest.items() if nm in ('kalshi', 'rosters_BSB', 'rosters_HH', 'sleeper_off', 'espn_games', 'transactions_BSB')),
     str({nm: (m['as_of'], m['as_of_src']) for nm, m in B.manifest.items()}))
case('manifest: Kalshi as-of is the pulled_at column (08:20:41Z), not a file time',
     B.manifest['kalshi']['as_of'].startswith('2026-10-04T04:20') and B.manifest['kalshi']['as_of_src'] == 'pulled_at column', str(B.manifest['kalshi']))

# ---------------------------------------------------------------- C1 one week
r1 = run(root('C1'), now=at(2026, 9, 29, 7, 30), week=4)
case('C1 REFUSE: Tue 09-29 7:30 am — pump pulled week 3 (2:49 am), engine data week 4', bool([v for v in fired(r1, 'C1', CT.REFUSE) if 'pump/loader week 3' in v.msg]), r1.codes_line())
case('C1 REFUSE: the 2:48 am roster read is outside week 4', bool([v for v in fired(r1, 'C1', CT.REFUSE) if 'outside week 4' in v.msg]))
case('C1: a run that refuses is not ok', not r1.ok)
r1b = run(root('base', edit=lambda d: rw_csv(os.path.join(d, 'sleeper_off_wk4.csv'), lambda rs: rs[:40])))
case('C1 REFUSE: sleeper_off_wk4 with 40 rows (< 100)', bool([v for v in fired(r1b, 'C1', CT.REFUSE) if '40 rows' in v.msg]), r1b.codes_line())
case('C1: the clean base never fires C1', not B.by_code('C1'))

# ---------------------------------------------------------------- C2 timestamps
def _naive(d):
    p = os.path.join(d, 'state', 'BSB', '2026-10-04T0748.json'); j = json.load(open(p)); j['pulled'] = '2026-10-04 08:21'; json.dump(j, open(p, 'w'))
r2 = run(root('base', edit=_naive))
case('C2 REFUSE: a naive snapshot pulled time (no zone, undeclared source)', bool([v for v in fired(r2, 'C2', CT.REFUSE) if 'naive' in v.msg]), r2.codes_line())
def _utc_as_et(d):
    # the pull ran at 08:20 UTC; written as 08:20 EASTERN it is four hours in the future at 08:30 ET... no: 4h later
    rw_csv(os.path.join(d, 'kalshi.csv'), lambda rs: [dict(r, pulled_at='2026-10-04T12:20:41-04:00') for r in rs])
r2b = run(root('base', edit=_utc_as_et))
case('C2 REFUSE: a stamp in the future (UTC wall time labelled ET)', bool([v for v in fired(r2b, 'C2', CT.REFUSE) if 'future' in v.msg]), r2b.codes_line())
def _garbage(d):
    rw_csv(os.path.join(d, 'espn_games.csv'), lambda rs: [dict(rs[0], kickoff='Sunday 1pm')] + rs[1:])
r2c = run(root('base', edit=_garbage))
case('C2 REFUSE: an unparseable kickoff', bool(fired(r2c, 'C2', CT.REFUSE)), r2c.codes_line())

# ---------------------------------------------------------------- ts.parse_ts
case('ts: Yahoo log "YYYY-MM-DD HH:MM" is ET', T.parse_ts('2026-09-30 04:12', 'yahoo_log') == at(2026, 9, 30, 4, 12))
case('ts: Yahoo page "Sep 28, 9:44 pm" is ET, year inferred', T.parse_ts('Sep 28, 9:44 pm', 'yahoo_page', now=NOW) == at(2026, 9, 28, 21, 44))
case('ts: a December page read in January is last year', T.parse_ts('Dec 31, 11:00 pm', 'yahoo_page', now=at(2027, 1, 1, 9)).year == 2026)
case('ts: ISO with offset and Z both land in ET', T.parse_ts('2026-10-04T13:30Z', 'espn') == at(2026, 10, 4, 9, 30) and T.parse_ts('2026-10-04T08:21:40+00:00', 'pump').hour == 4)
case('ts: archive stamp kalshi_2026-10-04T0822Z is UTC', T.parse_ts('2026-10-04T0822Z', 'archive') == at(2026, 10, 4, 4, 22))
case('ts: Yahoo game text "Sun 9:30 am" resolves inside the week', T.parse_ts('Sun 9:30 am vs Ind ', 'yahoo_game', week_start=C.week_start(4)) == at(2026, 10, 4, 9, 30))
try: T.parse_ts('2026-10-04 08:21', 'kalshi'); _ok = False
except T.TsError: _ok = True
case('ts: a naive string from an undeclared source is refused, not guessed', _ok)
case('ts: every returned datetime is tz-aware ET', T.parse_ts('2026-09-29T0810', 'snapshot').tzinfo is not None and T.parse_ts('2026-09-29T0810', 'snapshot').utcoffset() == dt.timedelta(hours=-4))

# ---------------------------------------------------------------- C3 freshness
r3 = run(root('base'), now=at(2026, 10, 4, 12, 0))
case('C3 DEGRADE: Kalshi 8h old at noon with starters inside the decide window', bool([v for v in fired(r3, 'C3', CT.DEGRADE) if 'Kalshi' in v.msg]), r3.codes_line())
case('C3: degrade_lineup is set and the reason names Kalshi', r3.degrade_lineup and 'Kalshi' in (r3.lineup_reason() or ''))
case('C3: a 1:00 pm game is PROVISIONAL, a game three days out is not (feeds only bind inside 36h)',
     bool(r3.lineup_reason(at(2026, 10, 4, 13))) and r3.lineup_reason(at(2026, 10, 7, 20)) is None)
case('C3: rosters 8h old do not block adds', not r3.degrade_add_drop)
r3b = run(root('base'), now=at(2026, 10, 5, 15, 0))
case('C3 DEGRADE: rosters 35h old block adds and drops (> 30h)', r3b.degrade_add_drop and bool([v for v in fired(r3b, 'C3', CT.DEGRADE) if 'adds and drops BLOCK' in v.msg]), r3b.codes_line())
case('C3: the clean base at 08:30 is fresh', not B.degrade_lineup and not B.degrade_add_drop)

# ---------------------------------------------------------------- C4 roster shape
r4 = run(root('base', 'C4_empty', edit=lambda d: [os.remove(os.path.join(d, 'state', 'HH', f)) for f in os.listdir(os.path.join(d, 'state', 'HH')) if f != '2026-09-29T0810.json']),
         now=at(2026, 9, 29, 8, 30), week=4, only=('C4',))
case("C4 REFUSE: the real '--empty--' row (Pound the Rock CB, 09-29)", bool([v for v in fired(r4, 'C4', CT.REFUSE) if '--empty--' in v.msg]), r4.codes_line())
r4b = run(root('base', 'C4_team_missing'), only=('C4',))
case('C4 REFUSE: a BSB roster CSV with one team removed (11 of 12)', bool([v for v in fired(r4b, 'C4', CT.REFUSE) if '11 rostered teams' in v.msg]), r4b.codes_line())
_raw = list(csv.DictReader(open(os.path.join(FX, 'C15', 'data', 'yahoo', 'HH_rosters.csv'))))
case("C4 (loader): the pump file with the '--empty--' row is not installed", any(v.code == 'C4' for v in CT.check_pump_file('rosters', os.path.join(FX, 'C15', 'data', 'yahoo', 'HH_rosters.csv'), league='HH', now=at(2026, 9, 29, 7))))
def _swap_id(d):
    rw_csv(os.path.join(d, 'yahoo', 'BSB_rosters.csv'), lambda rs: [dict(r, team_id='3') if r['owner'] == 'OVERKILL' else r for r in rs])
r4c = run(root('base', edit=_swap_id), only=('C4',))
case('C4 REFUSE: two owners under one team_id / my team not at id 7', bool(fired(r4c, 'C4', CT.REFUSE)), r4c.codes_line())
case('C4: the clean base never fires C4', not B.by_code('C4'))

# ---------------------------------------------------------------- C5 frozen pages
r5 = run(root('C5'), now=at(2026, 9, 29, 7, 30), week=4, only=('C5',))
case("C5 REFUSE: 09-29 frozen page — Coker on The STRIB Club's page AND Maker's Mark's, log missing STRIB's drop",
     bool([v for v in fired(r5, 'C5', CT.REFUSE) if 'jalen coker' in v.msg]), r5.codes_line())
def _full(d): shutil.copy(os.path.join(d, 'hh_transactions_full.csv'), os.path.join(d, 'hh_transactions.csv'))
r5b = run(root('C5', edit=_full), now=at(2026, 9, 29, 7, 30), week=4, only=('C5',))
case("C5: with STRIB's real 11:29 drop in the log, reconcile leaves him on Maker's Mark only — no C5", not r5b.by_code('C5'), r5b.codes_line())
_rows = json.load(open(os.path.join(FX, 'C5', 'data', 'state', 'HH', '2026-09-29T0810.json')))['rows']
_log = list(csv.DictReader(open(os.path.join(FX, 'C5', 'data', 'hh_transactions_full.csv'))))
_rec, _net = ST.reconcile('HH', [dict(r) for r in _rows], _log, now=at(2026, 9, 29, 7, 30))
case("C5: reconcile (now pinned) removes Coker from The STRIB Club", not any(r['player'] == 'Jalen Coker' and r['owner'] == 'The STRIB Club' for r in _rec), str(_net))

# ---------------------------------------------------------------- C6 defenses
_trex = json.load(open(os.path.join(FX, 'C6', 'data', 'state', 'HH', '2026-10-01T1853.json')))['rows']
_mn = next(r for r in _trex if r['player'] == 'Minnesota')
# keyed the way the engine keyed it on 10-01 (a person called 'minnesota')
case("C6: T-rex's 'Minnesota' keyed as the 10-01 engine keyed it ('minnesota') is a violation",
     bool(CT.def_key_violations([dict(_mn, nfl='MIN', tm='MIN', key='minnesota')], 'HH')))
r6 = run(root('C6'), now=at(2026, 10, 1, 15, 0), week=4, only=('C6',))
case("C6 REFUSE: 'Minnesota' DEF with no team code (a city-only render)", bool([v for v in fired(r6, 'C6', CT.REFUSE) if 'Minnesota' in v.msg]), r6.codes_line())
case('C6: the clean base keys every DEF as DST:<team>', not B.by_code('C6'))

# ---------------------------------------------------------------- C7 vocabulary
def _tag(d):
    p = os.path.join(d, 'state', 'BSB', '2026-10-04T0748.json'); j = json.load(open(p)); j['rows'][3]['designation'] = 'NFI-R'; json.dump(j, open(p, 'w'))
r7 = run(root('base', edit=_tag), only=('C7',))
case("C7 WARN: an unknown tag ('NFI-R') is named, not silently clear", bool([v for v in fired(r7, 'C7', CT.WARN) if 'NFI-R' in v.msg]), r7.codes_line())
case('C7: the vocabulary holds every tag seen this season', not RU.unknown_tags(['none', '', 'Q', 'D', 'O', 'IR', 'IR-R', 'NA', 'PUP-R', 'CEL', 'SUSP', 'PUP']))

# ---------------------------------------------------------------- C8 in-game ladders
_n8 = at(2026, 9, 27, 14, 20)
r8 = run(root('C8'), now=_n8, week=3, only=('C8',))
case('C8 REFUSE: Sunday 09-27 2:20 pm — in-week Kalshi games with no kickoff on the runner schedule (ESPN returned one row)',
     bool([v for v in fired(r8, 'C8', CT.REFUSE) if 'no known kickoff' in v.msg]), r8.codes_line())
def _full8(d): shutil.copy(os.path.join(d, 'espn_games_full.csv'), os.path.join(d, 'espn_games.csv'))
r8b = run(root('C8', edit=_full8), now=_n8, week=3, only=('C8',))
case('C8: with the full week-3 schedule the kicked games are the live guard\'s to drop — no C8', not r8b.by_code('C8'), r8b.codes_line())
def _wrong_kick(d):
    _full8(d)
    rw_csv(os.path.join(d, 'espn_games.csv'), lambda rs: [dict(r, kickoff='2026-09-27T20:25Z') if r['home'] == 'CLE' else r for r in rs])
    os.makedirs(os.path.join(d, 'yahoo'), exist_ok=True); shutil.copy(os.path.join(d, 'yahoo_live_rows.csv'), os.path.join(d, 'yahoo', 'HH_rosters.csv'))
r8c = run(root('C8', edit=_wrong_kick), now=_n8, week=3)
case("C8 REFUSE: Yahoo shows CAR@CLE in the 2nd quarter while the schedule says 4:25 — its in-game ladders would be pregame",
     bool([v for v in fired(r8c, 'C8', CT.REFUSE) if 'CARCLE' in v.msg]), r8c.codes_line())
class _P: pass
_p = _P(); _p.kick = {'CAR': at(2026, 9, 27, 13), 'CLE': at(2026, 9, 27, 13)}; _p.in_week_events = {'KXNFLRECYDS-26SEP27CARCLE'}; _p.kal_games = {('CAR', 'CLE'): {}}
case('C8 (post-Projections): a kicked game left in the pregame set or its game-line ladders is REFUSE', len(CT.check_projections(_p, now=_n8)) == 2)

# ---------------------------------------------------------------- C9 kickoff vs Yahoo
def _london(d):
    rw_csv(os.path.join(d, 'espn_games.csv'), lambda rs: [dict(r, kickoff='2026-10-04T17:00Z') if r['away'] == 'IND' else r for r in rs])
r9 = run(root('base', edit=_london), only=('C9',))
case("C9 DEGRADE: schedule says IND@WSH at 1:00, Yahoo says 'Sun 9:30 am' (London)", bool([v for v in fired(r9, 'C9', CT.DEGRADE) if 'Sun 9:30 am' in v.msg]), r9.codes_line())
case("C9: Yahoo's time is the override the engine reads", r9.kick_override.get('IND') == at(2026, 10, 4, 9, 30) and r9.kick_override.get('WAS') == at(2026, 10, 4, 9, 30), str(r9.kick_override))
case('C9: the clean base agrees with Yahoo to the minute', not B.by_code('C9'))

# ---------------------------------------------------------------- C10 props
r10 = run(root('base', 'C10'), only=('C10',))
_v10 = fired(r10, 'C10', CT.REFUSE)
case('C10 REFUSE: week-2 DraftKings props against week-4 games (10-04 runner)', bool(_v10) and _v10[0].drops == 'espn_props.csv', r10.codes_line())
case('C10: the props are refused as an INPUT — the run itself proceeds', r10.ok and 'espn_props.csv' in r10.dropped)

# ---------------------------------------------------------------- C11 Kalshi completeness
def _thin(d):
    rw_csv(os.path.join(d, 'kalshi.csv'), lambda rs: [r for r in rs if 'MIAMIN' not in r['event']])
r11 = run(root('base', edit=_thin), only=('C11',))
case("C11 DEGRADE: a pull missing one of three games' events (67% < 80%)", bool(fired(r11, 'C11', CT.DEGRADE)) and bool(r11.steam_gone_off), r11.codes_line())
def _series(d):
    rw_csv(os.path.join(d, 'kalshi.csv'), lambda rs: [r for r in rs if not ('NEBUF' in r['event'] and r['series'] in ('KXNFLREC', 'KXNFLRECYDS', 'KXNFLRSHYDS'))])
r11b = run(root('base', edit=_series), only=('C11',))
case('C11 DEGRADE: NE@BUF lost three series since the previous pull', bool([v for v in fired(r11b, 'C11', CT.DEGRADE) if 'NEBUF' in v.msg]), r11b.codes_line())
case('C11: the clean base is complete against its previous archive', not B.by_code('C11') and not B.steam_gone_off)

# ---------------------------------------------------------------- C12 transactions
def _old_log(d):
    p = os.path.join(d, 'pulls', 'ffdata_pull.md'); s = open(p).read()
    open(p, 'w').write(s.replace('BSB transactions:', 'BSB transactions NOT installed:'))
    json.dump({'files': {'bsb_transactions.csv': {'as_of': '2026-10-02T09:40:00+00:00', 'src': 'test: an older page'}}}, open(os.path.join(d, 'asof.json'), 'w'))
r12 = run(root('base', edit=_old_log), only=('C12',))
case('C12 DEGRADE: the transactions page is older than the rosters (moves since cannot correct a frozen page)',
     bool([v for v in fired(r12, 'C12', CT.DEGRADE) if 'OLDER than the rosters' in v.msg]), r12.codes_line())
case('C12: BSB adds and drops BLOCK (add_drop_reason), HH unaffected', bool(r12.add_drop_reason('BSB')) and not r12.add_drop_reason('HH'))
def _bad_row(d):
    with open(os.path.join(d, 'bsb_transactions.csv'), 'a') as fh: fh.write('Oct 3 8:39pm,FWU,Add,Someone,WR,NE,,Free Agent\n')
r12b = run(root('base', edit=_bad_row), only=('C12',))
case('C12 DEGRADE: a log row whose datetime does not parse', bool([v for v in fired(r12b, 'C12', CT.DEGRADE) if 'datetime' in v.msg]), r12b.codes_line())

# ---------------------------------------------------------------- C13 one waiver run
_log13 = os.path.join(FX, 'C13', 'data', 'bsb_transactions.csv')
case('C13: waiver_run_at(week 4) is the logged 4:12 am run (09-30), not the assumed 6:00', RU.waiver_run_at(4, _log13) == at(2026, 9, 30, 4, 12), str(RU.waiver_run_at(4, _log13)))
case('C13: a week with no Waiver adds logged falls back to Wednesday 06:00', RU.waiver_run_at(9, _log13) == C.bsb_waiver_deadline(9))
case('C13: claims are open at 4:00 am Wednesday and closed at 4:30 (the 4:57 pull is after the run)',
     RU.bsb_claims_open(at(2026, 9, 30, 4, 0), _log13) and not RU.bsb_claims_open(at(2026, 9, 30, 4, 30), _log13))
case('C13: last_waiver_run on Sunday 10-04 is the 09-30 4:12 run', RU.last_waiver_run(at(2026, 10, 4, 9), _log13) == at(2026, 9, 30, 4, 12))
# grep: one waiver run, no mtime as-of, one designation set
_src = {}
for dp, _, fs in os.walk(ENGINE):
    if '/.git' in dp or '/test' in dp[len(ENGINE):] or '__pycache__' in dp: continue
    for f in fs:
        if f.endswith('.py') and not f.startswith('test_'): _src[os.path.relpath(os.path.join(dp, f), ENGINE)] = open(os.path.join(dp, f)).read()
_wd = [f for f, s in _src.items() if 'bsb_waiver_deadline' in s and f not in ('lib/rules.py', 'lib/clock.py')]
case('C13 grep: no bsb_waiver_deadline caller outside rules.py (clock.py defines it)', not _wd, str(_wd))
_mt = [f for f, s in _src.items() if re.search(r'getmtime\s*\(', s) and f not in ('lib/market.py',)]
case('grep: no os.path.getmtime as-of in any engine module (market.py keys its fits CACHE on it — not an as-of)', not _mt, str(_mt))
_us = [f for f, s in _src.items() if f.startswith('lib/') and f != 'lib/rules.py' and re.search(r"(UNUSABLE|RISKY|TAGGED|LONG_TERM|OUT_TAGS)\s*=\s*\{", s)]
_inline = [f for f, s in _src.items() if f.startswith('lib/') and f != 'lib/rules.py' and "'IR','IR-R','O','NA'" in s.replace(' ', '')]
case('grep: no designation-set copy outside rules.py', not _us and not _inline, str(_us + _inline))
_sp = [f for f, s in _src.items() if f.startswith('lib/') and f != 'lib/ts.py' and re.search(r'\bstrptime\(|\.fromisoformat\(', s)]
case('grep: no ad-hoc timestamp parsing in lib/ outside ts.py', not _sp, str(_sp))
_ld = [f for f in ('ffdata_load.py', 'ff.py') if re.search(r'\bstrptime\(', _src.get(f, ''))]
case('grep: ffdata_load.py and ff.py parse no timestamp of their own', not _ld, str(_ld))

# ---------------------------------------------------------------- C14 matchup
def _mu(fn):
    def e(d):
        shutil.copy(os.path.join(FX, 'C14', 'data', 'yahoo', 'BSB_matchup_wk3.csv'), os.path.join(d, 'yahoo', 'BSB_matchup_wk3.csv'))
        rw_csv(os.path.join(d, 'yahoo', 'BSB_matchup_wk3.csv'), fn)
    return e
_n14 = at(2026, 9, 29, 6, 0)
r14 = run(root('base', edit=_mu(lambda rs: rs)), now=_n14, week=3, only=('C14',))
case('C14: the real BSB week-3 page (147.40 vs 114.65) reconciles — no C14', not r14.by_code('C14'), r14.codes_line())
r14b = run(root('base', edit=_mu(lambda rs: [dict(r, total='150.40') if r['side'] == 'me' else r for r in rs])), now=_n14, week=3, only=('C14',))
case('C14 REFUSE: side total != sum of its starter rows', bool([v for v in fired(r14b, 'C14', CT.REFUSE) if '150.40' in v.msg]), r14b.codes_line())
r14c = run(root('base', edit=_mu(lambda rs: [dict(r, owner='Rayland') if r['side'] == 'me' else r for r in rs])), now=_n14, week=3, only=('C14',))
case("C14 REFUSE: the 'me' side is not my team", bool([v for v in fired(r14c, 'C14', CT.REFUSE) if "'me' side" in v.msg]), r14c.codes_line())
def _opp(d):
    p = os.path.join(d, 'matchups.json'); j = json.load(open(p)); j['4']['BSB'] = 'Nobody FC'; json.dump(j, open(p, 'w'))
r14d = run(root('base', edit=_opp), only=('C14',))
case('C14 REFUSE: the opponent on file is not a roster owner', bool(fired(r14d, 'C14', CT.REFUSE)), r14d.codes_line())

# ---------------------------------------------------------------- C15 columns
def _pct(d):
    shutil.copy(os.path.join(FX, 'C15', 'data', 'yahoo', 'HH_rosters.csv'), os.path.join(d, 'yahoo', 'HH_rosters.csv'))
r15 = run(root('base', edit=_pct), only=('C15',))
# 10-05: a percentage in Yahoo's DISPLAY points columns degrades (the field is blanked, the
# roster row is kept) — Yahoo's in-game pages put one there on every Sunday row
case("C15 DEGRADE: the real '3%' in proj_pts (pump 28e1a7f) blanks the field, keeps the roster", bool([v for v in fired(r15, 'C15', CT.DEGRADE) if '3%' in v.msg and 'blanked' in v.msg]), r15.codes_line())
def _nocol(d):
    rows = list(csv.DictReader(open(os.path.join(d, 'kalshi.csv'))))
    with open(os.path.join(d, 'kalshi.csv'), 'w', newline='') as fh:
        f = [k for k in rows[0] if k != 'pulled_at']; w = csv.DictWriter(fh, fieldnames=f, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
r15b = run(root('base', edit=_nocol), only=('C15',))
case('C15 REFUSE: kalshi.csv without its pulled_at column', bool([v for v in fired(r15b, 'C15', CT.REFUSE) if 'pulled_at' in v.msg]), r15b.codes_line())
case('C15: the clean base has every column', not B.by_code('C15'))

# ---------------------------------------------------------------- C16 registry + ledger
def _corrupt(name):
    def e(d): open(os.path.join(d, name), 'w').write(open(os.path.join(FX, 'C16', 'data', name)).read()[:-40])
    return e
r16 = run(root('base', edit=_corrupt('roles.json')), only=('C16',))
case('C16 REFUSE: roles.json truncated mid-write never becomes {}', bool([v for v in fired(r16, 'C16', CT.REFUSE) if 'roles.json' in v.msg]), r16.codes_line())
def _ledger(d): shutil.copy(os.path.join(FX, 'C16', 'data', 'ledger.json'), os.path.join(d, 'ledger.json')); _corrupt('ledger.json')(d)
r16b = run(root('base', edit=_ledger), only=('C16',))
case('C16 REFUSE: ledger.json truncated never becomes []', bool([v for v in fired(r16b, 'C16', CT.REFUSE) if 'ledger.json' in v.msg]), r16b.codes_line())
case('C16 WARN: add_yes entries verified 09-14 are demoted on 10-04 (> 14 days)', bool([v for v in B.by_code('C16') if v.severity == CT.WARN and 'hutchinson' in v.msg]), B.codes_line())
_R = RU.load_roles(os.path.join(FX, 'C16', 'data', 'roles.json'), today=dt.date(2026, 9, 20))
case('C16: the same entries are still verified on 09-20 (6 days)', 'xavier hutchinson' in _R['add_yes'] and _R['add_yes']['xavier hutchinson']['as_of'] == '2026-09-14')
_R2 = RU.load_roles(os.path.join(FX, 'C16', 'data', 'roles.json'), today=dt.date(2026, 10, 4))
case('C16: on 10-04 they sit under _demoted_add_yes with their as-of', 'xavier hutchinson' in _R2['_demoted_add_yes'] and not [k for k in _R2['add_yes'] if not k.startswith('_')])
_d16 = tempfile.mkdtemp(); _tmp.append(_d16)
RU.save_roles(json.load(open(os.path.join(FX, 'C16', 'data', 'roles.json'))) | {'add_yes': {'new guy': dict(team='NE', src='beat 2026-10-03')}}, os.path.join(_d16, 'roles.json'), today=dt.date(2026, 10, 4))
case('C16: save_roles stamps as_of on a new add_yes entry, atomically (no temp file left)',
     json.load(open(os.path.join(_d16, 'roles.json')))['add_yes']['new guy']['as_of'] == '2026-10-04' and os.listdir(_d16) == ['roles.json'])
from lib import ledger as LG
_real = LG.PATH; LG.PATH = os.path.join(_d16, 'ledger.json')
open(LG.PATH, 'w').write('[{"id": "x", "league": "BSB"')
try: LG._load(); _raised = False
except ValueError: _raised = True
case('C16: ledger._load raises on a corrupt file instead of returning [] (which _save would write over)', _raised)
open(LG.PATH, 'w').write('[]'); LG.propose('BSB', 'hold', 'Probe', 'probe call')
case('C16: ledger._save is atomic (tmp + rename, nothing left behind)', sorted(os.listdir(_d16)) == ['ledger.json', 'roles.json'] and len(json.load(open(LG.PATH))) == 1)
LG.PATH = _real

# ---------------------------------------------------------------- C17 single writer
def _repo(newer):
    r = tempfile.mkdtemp(prefix='repo_'); _tmp.append(r)
    os.makedirs(os.path.join(r, 'engine', 'data'))
    L = json.load(open(os.path.join(FX, 'C16', 'data', 'ledger.json')))
    if newer: L.append(dict(id='zz', ts='2026-10-04T10:00-04:00', league='BSB', kind='hold', subject='X', call='x', status='proposed'))
    json.dump(L, open(os.path.join(r, 'engine', 'data', 'ledger.json'), 'w'))
    return r
_b17 = root('base', edit=lambda d: shutil.copy(os.path.join(FX, 'C16', 'data', 'ledger.json'), os.path.join(d, 'ledger.json')))
r17 = run(_b17, only=('C17',), repo=_repo(True))
case("C17 REFUSE: the pump repo's engine/data ledger is newer than the local one", bool(fired(r17, 'C17', CT.REFUSE)), r17.codes_line())
r17b = run(_b17, only=('C17',), repo=_repo(False))
case('C17: an equal repo ledger does not refuse', not r17b.by_code('C17'), r17b.codes_line())
r17c = CT.check(_b17, now=NOW, week=4, only=('C17',), repo=_repo(True), in_action=True)
case('C17: inside the Action (the repo IS the engine) the check is skipped', not r17c.by_code('C17'))

# ---------------------------------------------------------------- the engine reads the flags
from lib import gate as G
_res = r3b                                         # rosters 35h old -> add/drop degraded
CT.install(_res)
_ga = G.check('add', 'probe add', player='Probe', designation='none', sources=['sleeper', 'usage'], pos='WR', value=60.0, horizon='season',
              roster_keys=set(), pulled=C.today().isoformat(), league='BSB')
case('G8 reads the manifest: an add BLOCKs under degrade_add_drop although the caller passed today', any(g == 'G8-fresh' and s == 'BLOCK' for g, s, _ in _ga.checks), _ga.render())
CT.install(r3)
_gs = G.check('start', 'probe start', player='Probe', designation='none', sources=['kalshi', 'sleeper'], pos='WR', value=10.0, horizon='weekly',
              market_ready=True, pulled=C.today().isoformat(), league='BSB')
case('G8 reads the manifest: a start WARNs (provisional) under degrade_lineup', any(g == 'G8-fresh' and s == 'WARN' for g, s, _ in _gs.checks), _gs.render())
CT.install(None)
_g0 = G.check('start', 'probe start', player='Probe', designation='none', sources=['kalshi', 'sleeper'], pos='WR', value=10.0, horizon='weekly',
              market_ready=True, pulled=C.today().isoformat(), league='BSB')
case('G8 outside a run falls back to the caller\'s date (the gate regression is unchanged)', any(g == 'G8-fresh' and s == 'PASS' for g, s, _ in _g0.checks))
case('Result.codes_line is the card\'s one line', 'C3 DEGRADE' in r3.codes_line() and B.codes_line() == 'C16 WARN')

# ---------------------------------------------------------------- rules.locked
case('rules.locked: final / live / past kickoff / Yahoo game text / week-lock', all([
    RU.locked({'final': True}), RU.locked({'live': True}), RU.locked({'phase': 'locked'}),
    RU.locked({'kick': at(2026, 10, 4, 13)}, now=at(2026, 10, 4, 13, 1)), not RU.locked({'kick': at(2026, 10, 4, 13)}, now=at(2026, 10, 4, 12)),
    RU.locked({'game': 'Q3 5:12, 14-7 vs Atl'}), RU.locked({'game': 'Final W 31-24 vs Dal'}), not RU.locked({'game': 'Sun 1:00 pm vs Dal'}),
    RU.locked({'week_locked': True}), not RU.locked({})]))

for r in _tmp: shutil.rmtree(r, ignore_errors=True)
print('=' * 88)
print(f'{total - bad}/{total} behaved as required.' + ('  CONTRACT IS SOUND.' if bad == 0 else f'  {bad} FAILURES — do not ship.'))
sys.exit(1 if bad else 0)
