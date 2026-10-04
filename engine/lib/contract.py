"""THE INPUT CONTRACT — inputs are checked before anything is decided.

The engine used to decide on whatever was on disk. Every one of these happened:
Yahoo team pages frozen per player after kickoff while the transactions log moved
on; a defense printed by city ('Minnesota') keyed as a person and offered as a
free agent; UTC read as ET; four notions of "week" (calendar, data, pump, loader);
in-game Kalshi ladders read as projections; week-2 DraftKings props applied in week
4 because a checkout reset every mtime; a missing team page that turned a whole
roster into free agents; a freshness gate that could not fail (every caller passed
today's date); seven copies of the UNUSABLE set; two notions of the BSB waiver
run; file mtime used as "as of"; roles.json / ledger.json parse errors swallowed
into {} / [].

`manifest(root)` says what every input is and how old it is, read from CONTENT
(pulled_at columns, the pump's pulled.txt, archive stamps, the loader's
data/asof.json and data/pulls/ffdata_pull.md) — never from a file's mtime. Where a
file truly carries no stamp the as-of is 'unknown', and the contract degrades.

`check(root, now, week)` returns a Result whose violations each carry a code, a
severity and the evidence:
  REFUSE   the run does not happen (ff.build raises Refused; data/out_contract.txt
           says why). A REFUSE with `drops` refuses ONE input instead: the run
           proceeds without it (C10: props from another week are dropped).
  DEGRADE  the run happens with flags the engine reads: degrade_lineup (lineup
           calls are PROVISIONAL), degrade_add_drop / add_drop_reason(lg) (G8
           BLOCKs adds and drops), steam_gone_off (no 'markets withdrawn' calls),
           kick_override (Yahoo's kickoff wins when the schedule disagrees).
  WARN     printed, and listed on the card's Inputs panel.

Invariants (each names the failure it exists for):
  C1  one week per run: pump/loader week == data week; sleeper_off_wk{W} >= 100 rows;
      rosters / actuals / matchups for W pulled inside [week_start(W), week_start(W+1)+36h)  REFUSE
  C2  every timestamp parses through ts.parse_ts; naive only from declared sources;
      no input stamped in the future (UTC written as ET)                                   REFUSE
  C3  per-purpose freshness: Kalshi <= 6h and Sleeper <= 24h for lineup calls on games
      in the decide/alert window; rosters <= 18h lineup / <= 30h add-drop                  DEGRADE
  C4  roster shape: owners == league size; each team_id once; my team present; rows per
      team within [slots+bench-2, slots+bench+IR]; no '--empty--'                          REFUSE
  C5  after reconcile, each player key on at most one roster; no team over max              REFUSE
  C6  every DEF row: nfl is one of the 32 codes and key == DST:<nfl>; no rostered key is a
      bare city or nickname                                                                REFUSE
  C7  designation vocabulary (rules.VOCAB)                                                  WARN
  C8  no in-game Kalshi ladder can reach pregame projections: every in-week game has a
      known kickoff; Yahoo/ESPN 'in progress/final' never sits on a kickoff still ahead;
      ladder as-of < kickoff                                                              REFUSE
  C9  schedule kickoff vs Yahoo's game text (+-5 min); Yahoo's time is used                DEGRADE
  C10 props event ids are all this week's ESPN event ids (else the props are dropped)       REFUSE(input)
  C11 Kalshi completeness vs the previous archive: events >= 80%, series >= prev-1 per
      game (else 'markets withdrawn' is not inferred)                                      DEGRADE
  C12 transactions log as-of >= roster as-of; every row parses (else BSB add/drop BLOCK)    DEGRADE
  C13 one waiver run (rules.waiver_run_at) — enforced by test/test_contract.py's grep
  C14 matchup: 'me' == my team; opponent is a roster owner; side totals == starter rows    REFUSE
  C15 required columns per file; numeric columns parse; no '%' in a points column          REFUSE
  C16 roles.json / ledger.json parse (else REFUSE); add_yes older than 14 days demoted     REFUSE / WARN
  C17 single writer: a container run refuses when the pump repo's engine/data ledger or
      state is newer than the local copy (skipped in the Action and when the repo is absent) REFUSE
"""
from . import paths as _paths
import csv, glob, hashlib, json, os, re, datetime as dt
from collections import defaultdict, Counter
from . import clock as C, ts as T, rules as RU
from .leagues import ALL
from .names import key, team, DST_FULL, NICK2ABBR, CITY2ABBR

REFUSE, DEGRADE, WARN = 'REFUSE', 'DEGRADE', 'WARN'
ROOT = _paths.root()
REPO = os.environ.get('FFDATA_REPO', '/home/claude/ffdata_repo')

FRESH_H = dict(kalshi=6.0, sleeper=24.0, rosters_lineup=18.0, rosters_add_drop=30.0)
WEEK_TAIL = dt.timedelta(hours=36)
KICK_TOL = dt.timedelta(minutes=5)
FUTURE_GRACE = dt.timedelta(minutes=10)
KALSHI_EVENTS_MIN = 0.80
SLEEPER_MIN_ROWS = 100
GAME_LINE_SERIES = ('KXNFLSPREAD', 'KXNFLTOTAL', 'KXNFLGAME', 'KXNFLTEAMPTS')
YAHOO_BLANK = ('', '–', '-', '—', 'NONE')        # Yahoo's dash for 'no points yet'; DraftKings' NONE for 'no line'
BARE_TEAM_WORDS = (set(NICK2ABBR) | set(CITY2ABBR) | {'los angeles', 'new york', 'la', 'ny'}
                   | {v for v in DST_FULL.values()})

# The result of the check that ff.build() ran, read by gate G8 and Projections.
# None outside a run (the regression suites, ad-hoc calls): callers fall back.
RESULT = None
result = None

def install(res):
    global RESULT, result
    RESULT = result = res
    return res

def kick_override():
    return dict(RESULT.kick_override) if RESULT is not None else {}

def dropped(name):
    return RESULT is not None and name in RESULT.dropped


class Violation:
    __slots__ = ('code', 'severity', 'msg', 'evidence', 'drops')
    def __init__(self, code, severity, msg, evidence=None, drops=None):
        assert severity in (REFUSE, DEGRADE, WARN), severity
        self.code, self.severity, self.msg, self.evidence, self.drops = code, severity, msg, evidence, drops
    def __str__(self):
        return f'{self.code} {self.severity}' + (f' (input {self.drops} dropped)' if self.drops else '') + f': {self.msg}'
    __repr__ = __str__
    def as_dict(self):
        ev = self.evidence
        try: json.dumps(ev)
        except TypeError: ev = repr(ev)
        return dict(code=self.code, severity=self.severity, msg=self.msg, evidence=ev, drops=self.drops)


class Refused(RuntimeError):
    def __init__(self, res):
        self.result = res
        super().__init__('INPUT CONTRACT REFUSED: ' + '; '.join(f'{v.code} {v.msg}' for v in res.refused)[:600])


class Result:
    def __init__(self, root, now, week, manifest, violations, flags):
        self.root, self.now, self.week = root, now, week
        self.manifest = manifest
        self.violations = violations
        f = flags
        self._roster_lineup = list(f.get('roster_lineup', []))
        self._feed = list(f.get('feed', []))
        self._feed_now = bool(f.get('feed_now'))
        self._add_drop = {lg: list(v) for lg, v in f.get('add_drop', {}).items()}
        self._ages = dict(f.get('ages', {}))
        self.steam_gone_off = f.get('steam_gone_off')
        self.kick_override = dict(f.get('kick_override', {}))
        self.dropped = {v.drops for v in violations if v.severity == REFUSE and v.drops}

    # ---- verdicts
    @property
    def refused(self):
        return [v for v in self.violations if v.severity == REFUSE and not v.drops]
    @property
    def ok(self):
        return not self.refused
    def by_code(self, code):
        return [v for v in self.violations if v.code == code]
    def codes(self):
        """[(code, label)]: the severity, or 'input dropped: <file>' for a REFUSE scoped to one input."""
        return sorted({(v.code, f'{v.severity} (input dropped: {v.drops})' if v.drops else v.severity) for v in self.violations},
                      key=lambda x: (int(x[0][1:]), x[1]))

    # ---- degrade flags the engine reads
    def lineup_reason(self, kick=None):
        """Why a lineup call for a game at `kick` must be PROVISIONAL, or None.
        Roster staleness applies to every lineup call; Kalshi/Sleeper staleness only
        to games inside the 36h decide window (kick=None: any of my starters')."""
        rs = list(self._roster_lineup)
        if kick is None:
            if self._feed_now: rs += self._feed
        elif C.lineup_phase(kick) in ('decide', 'alert'):
            rs += self._feed
        return '; '.join(rs) if rs else None
    @property
    def degrade_lineup(self):
        return bool(self.lineup_reason())
    def add_drop_reason(self, league=None):
        rs = []
        for lg, v in self._add_drop.items():
            if league is None or lg == league: rs += v
        return '; '.join(rs) if rs else None
    @property
    def degrade_add_drop(self):
        return bool(self.add_drop_reason())
    def age_h(self, name):
        return self._ages.get(name)
    def ages_txt(self):
        def f(h): return 'unknown' if h is None else (f'{h:.0f}h' if h < 48 else f'{h/24:.0f}d')
        parts = []
        if 'rosters_BSB' in self._ages or 'rosters_HH' in self._ages:
            parts.append('rosters ' + '/'.join(f'{lg} {f(self._ages.get("rosters_" + lg))}' for lg in ALL if 'rosters_' + lg in self._ages))
        for nm, lab in (('kalshi', 'Kalshi'), ('sleeper_off', 'Sleeper'), ('transactions_BSB', 'BSB log')):
            if nm in self._ages: parts.append(f'{lab} {f(self._ages[nm])}')
        return ' · '.join(parts) or 'no inputs on record'

    # ---- reporting
    def codes_line(self):
        if not self.violations: return 'clean — every invariant C1-C17 holds'
        return ' · '.join(f'{c} {s}' for c, s in self.codes())
    def text(self):
        L = [f'# input contract — {C.stamp(self.now)} · engine week {self.week} · root {self.root}',
             f'verdict: {"REFUSED" if self.refused else "OK"} · {self.codes_line()}']
        for v in sorted(self.violations, key=lambda v: (('REFUSE', 'DEGRADE', 'WARN').index(v.severity), int(v.code[1:]))):
            L.append(f'  {v}')
            if v.evidence not in (None, '', [], {}): L.append(f'      evidence: {str(v.evidence)[:400]}')
        lr, ar = self.lineup_reason(), self.add_drop_reason()
        L.append(f'flags: degrade_lineup={bool(lr)}' + (f' ({lr})' if lr else '') +
                 f' · degrade_add_drop={bool(ar)}' + (f' ({ar})' if ar else '') +
                 f' · steam_gone_off={bool(self.steam_gone_off)} · kick_override={len(self.kick_override)} · dropped={sorted(self.dropped)}')
        L.append('manifest:')
        for nm, m in sorted(self.manifest.items()):
            L.append(f"  {nm:22s} as_of {m.get('as_of')} ({m.get('as_of_src')}) week {m.get('week')} rows {m.get('rows')} sha {m.get('sha')}  {m.get('path')}")
        return '\n'.join(L) + '\n'
    def summary(self, n=6):
        out = [f'  INPUT CONTRACT: {"REFUSED" if self.refused else "ok"} — {self.codes_line()}']
        for v in [v for v in self.violations if v.severity != WARN][:n]: out.append(f'    {v}'[:240])
        return '\n'.join(out)


# ======================================================================= helpers
def _sha(path):
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as fh:
            for b in iter(lambda: fh.read(1 << 20), b''): h.update(b)
        return h.hexdigest()[:12]
    except OSError:
        return None

def _csv(path):
    """-> (fieldnames, rows) or (None, None) when missing. A file that is not CSV raises."""
    if not os.path.exists(path): return None, None
    with open(path, newline='') as fh:
        r = csv.DictReader(fh)
        rows = list(r)
        return list(r.fieldnames or []), rows

def _num(v):
    try: float(v); return True
    except (TypeError, ValueError): return False

def _in_window(t, week):
    return C.week_start(week) <= t < C.week_start(week + 1) + WEEK_TAIL

def _fmt(t):
    return t.isoformat(timespec='minutes') if isinstance(t, dt.datetime) else str(t)

def _pull_md(d):
    """Parse data/pulls/ffdata_pull.md (the loader's record of its last load) into
    {relative file: (as_of, src)}, plus pump head and week. Only files the last load
    installed are listed; a 'NOT installed' line says nothing about the file on disk."""
    p = os.path.join(d, 'pulls', 'ffdata_pull.md')
    out, info = {}, {}
    if not os.path.exists(p): return out, info
    lines = open(p).read().splitlines()
    head = None
    for ln in lines:
        m = re.search(r'repo head: (\S+)', ln)
        if m:
            head = T.try_ts(m.group(1), 'pump')
            if head: info['head'] = head
        m = re.match(r'^week (\d+)\s*$', ln.strip())
        if m: info['week'] = int(m.group(1))
    wk = info.get('week')
    yts = {}
    for ln in lines:
        m = re.match(r'^(BSB|HH) rosters: .*?(?:pulled|pump pull) (\S+)', ln)
        if m:
            t = T.try_ts(m.group(2), 'pump')
            if t: yts[m.group(1)] = t
    for ln in lines:
        if 'NOT installed' in ln or 'NOT written' in ln: continue
        m = re.match(r'^(kalshi\.csv): .* pulled (\S+)', ln)
        if m:
            t = T.try_ts(m.group(2), 'kalshi')
            if t: out['kalshi.csv'] = (t, 'ffdata_pull.md')
            continue
        m = re.match(r'^((?:espn_games|trending_adds)\.csv|sleeper_(?:off|idp)_wk\d+\.csv|usage_wk\d+_[A-Z]+\.csv):', ln)
        if m and head:
            out[m.group(1)] = (head, 'ffdata_pull.md repo head'); continue
        m = re.match(r'^(BSB|HH) (rosters|matchup wk(\d+)|transactions):', ln)
        if m and m.group(1) in yts:
            lg, what = m.group(1), m.group(2); t = yts[lg]
            if what == 'rosters' and wk: out[f'yahoo_{lg}_wk{wk}.csv'] = (t, 'ffdata_pull.md yahoo pull')
            elif what.startswith('matchup'):
                out[f'actuals/{lg}_wk{m.group(3)}.csv'] = (t, 'ffdata_pull.md yahoo pull')
                out[f'matchups.json#{m.group(3)}/{lg}'] = (t, 'ffdata_pull.md yahoo pull')
            elif what == 'transactions':
                out[('bsb' if lg == 'BSB' else 'hh') + '_transactions.csv'] = (t, 'ffdata_pull.md yahoo pull')
    return out, info

def _asof_index(d):
    """{relative file: (as_of datetime, src)} from data/asof.json (the loader's
    structured record), falling back to data/pulls/ffdata_pull.md."""
    idx, info = _pull_md(d)
    p = os.path.join(d, 'asof.json')
    if os.path.exists(p):
        try:
            j = json.load(open(p))
            for f, v in (j.get('files') or {}).items():
                t = T.try_ts(v.get('as_of'), 'pump')
                if t: idx[f] = (t, v.get('src') or 'asof.json')
            if j.get('pump_week'): info['week'] = int(j['pump_week'])
            if j.get('pump_head'):
                t = T.try_ts(j['pump_head'], 'pump')
                if t: info['head'] = t
        except Exception:
            pass
    return idx, info

def file_as_of(rel, root=None):
    """As-of of one data file from the loader's records -> (datetime|None, src).
    The replacement for the file's mtime: content and provenance, not the filesystem."""
    d = os.path.join(root or ROOT, 'data')
    idx, _ = _asof_index(d)
    return idx.get(rel, (None, 'unknown'))

def data_week(root=None, now=None):
    """clock.data_week() for an arbitrary root: the calendar week once its Sleeper
    projections are on disk, else the previous week."""
    d = os.path.join(root or ROOT, 'data')
    w = C.nfl_week(now)
    if os.path.exists(os.path.join(d, f'sleeper_off_wk{w}.csv')): return w
    if w > 1 and os.path.exists(os.path.join(d, f'sleeper_off_wk{w - 1}.csv')): return w - 1
    return w

def def_key_violations(rows, league=''):
    """C6 on rows that carry pos / tm / key (as the engine keyed them)."""
    bad = []
    for r in rows:
        pos = (r.get('pos') or '').upper(); k = r.get('key') or ''
        tm = team(r.get('tm') or r.get('nfl') or '')
        if pos == 'DEF':
            if tm not in DST_FULL:
                bad.append(f"{league} {r.get('owner')}: DEF '{r.get('player')}' has nfl {r.get('nfl') or r.get('tm')!r}, not one of the 32 codes")
            elif k != f'DST:{tm}':
                bad.append(f"{league} {r.get('owner')}: DEF '{r.get('player')}' keyed {k!r}, not DST:{tm}")
        if str(k).lower() in BARE_TEAM_WORDS:
            bad.append(f"{league} {r.get('owner')}: rostered key {k!r} is a bare city/nickname ('{r.get('player')}' pos {pos or '?'})")
    return bad

def _teams_of(code):
    """'DETBUF' -> ('DET', 'BUF'); None when the split is not two known teams."""
    for i in (2, 3):
        a, b = team(code[:i]), team(code[i:])
        if a in DST_FULL and b in DST_FULL: return a, b
    return None

def kalshi_week_events(path, week):
    """{event: dict(code, teams, series, date)} for the in-week events of a Kalshi file
    (the same week rule lib/project.py applies), and the file's as-of."""
    _, rows = _csv(path)
    if rows is None: return None, None
    w0, w1 = C.week_start(week), C.week_start(week + 1)
    ev, stamps = {}, set()
    for r in rows:
        stamps.add(r.get('pulled_at'))
        e = r.get('event') or ''
        if e in ev: ev[e]['series'].add(r.get('series')); continue
        try: d = T.kalshi_event_date(e)
        except T.TsError: continue
        if not (w0 <= d + dt.timedelta(hours=12) < w1 + dt.timedelta(hours=12)): continue
        tail = e.split('-', 1)[1]; code = tail[7:]
        ev[e] = dict(code=code, teams=_teams_of(code), series={r.get('series')}, date=d)
    ts = [t for t in (T.try_ts(s, 'kalshi') for s in stamps if s) if t]
    return ev, (max(ts) if ts else None)


# ======================================================================= context
class _Ctx:
    def __init__(self, root, now, week, repo, in_action):
        self.root, self.d = root, os.path.join(root, 'data')
        self.now, self.week = now, week
        self.w0, self.w1 = C.week_start(week), C.week_start(week + 1)
        self.repo, self.in_action = repo, in_action
        self.asof, self.pump = _asof_index(self.d)
        self.manifest, self.t = {}, {}
        self.flags = dict(roster_lineup=[], feed=[], feed_now=False, add_drop=defaultdict(list), ages={},
                          steam_gone_off=None, kick_override={})
        self._cache = {}

    def p(self, *a): return os.path.join(self.d, *a)

    def csv(self, rel):
        if rel not in self._cache: self._cache[rel] = _csv(self.p(rel))
        return self._cache[rel]

    def note(self, name, rel, t, src, week=None, rows=None, extra=None):
        path = self.p(rel) if rel else None
        m = dict(path=path, as_of=_fmt(t) if t else 'unknown', as_of_src=src if t else (src or 'no stamp in content'),
                 week=week, rows=rows, sha=_sha(path) if path and os.path.exists(path) else None)
        if extra: m.update(extra)
        self.manifest[name] = m; self.t[name] = t
        self.flags['ages'][name] = T.age_h(t, self.now) if t else None
        return m

    def as_of(self, rel):
        return self.asof.get(rel, (None, 'unknown'))

    # ---- snapshots
    def snap(self, lg):
        k = ('snap', lg)
        if k not in self._cache:
            fs = sorted(glob.glob(self.p('state', lg, '*.json')))
            if not fs: self._cache[k] = None
            else:
                self._cache[k] = dict(path=fs[-1], j=json.load(open(fs[-1])), files=fs)
        return self._cache[k]

    def log_rows(self, lg):
        _, rows = self.csv('bsb_transactions.csv' if lg == 'BSB' else 'hh_transactions.csv')
        return rows

    def state(self, lg):
        """The snapshot as the engine sees it: State keys, after the log is replayed."""
        k = ('state', lg)
        if k not in self._cache:
            from . import state as ST
            s = self.snap(lg)
            if not s: self._cache[k] = None
            else:
                rows = [dict(r) for r in s['j'].get('rows', [])]
                lr = self.log_rows(lg)
                rec, net = ST.reconcile(lg, rows, [r for r in (lr or []) if 'datetime' in r], now=self.now)
                st = ST.State(lg, rec, s['j'].get('pulled'), source=os.path.basename(s['path']),
                              others_pulled=s['j'].get('others_pulled'))
                st.reconciled = net
                self._cache[k] = st
        return self._cache[k]

    # ---- schedule
    def games(self):
        """Week-W rows of espn_games.csv -> list of dict(away, home, kick, event_id, status, lines)."""
        if 'games' not in self._cache:
            _, rows = self.csv('espn_games.csv')
            out = []
            for r in rows or []:
                k = T.try_ts(r.get('kickoff'), 'espn')
                if k is None or not (self.w0 <= k < self.w1): continue
                out.append(dict(away=team(r.get('away')), home=team(r.get('home')), kick=k, event_id=r.get('event_id'),
                                status=(r.get('status') or '').upper(),
                                lines=_num(r.get('over_under')) and _num(r.get('spread'))))
            self._cache['games'] = out
        return self._cache['games']

    def sched(self, engine=True):
        """{team: kickoff}. engine=True: only rows lib/market.load_games keeps (a row
        without a parseable line never reaches Projections.kick), plus C9's overrides."""
        out = {}
        for g in self.games():
            if engine and not g['lines']: continue
            out[g['away']] = g['kick']; out[g['home']] = g['kick']
        if engine: out.update(self.flags['kick_override'])
        return out

    def yahoo_rows(self):
        """Every row of the installed raw Yahoo pages (rosters + this week's matchups)."""
        if 'yrows' not in self._cache:
            rows = []
            for lg in ALL:
                for rel in (f'yahoo/{lg}_rosters.csv', f'yahoo/{lg}_matchup_wk{self.week}.csv'):
                    _, rr = self.csv(rel)
                    for r in rr or []: rows.append(dict(r, _lg=lg, _src=rel))
            self._cache['yrows'] = rows
        return self._cache['yrows']

    def yahoo_games(self):
        """{team: Counter(game text)} from the raw Yahoo pages."""
        g = defaultdict(Counter)
        for r in self.yahoo_rows():
            tm = team(r.get('nfl') or '')
            txt = T._PRIVATE.sub('', r.get('game') or '').strip()
            if tm and txt: g[tm][txt] += 1
        return g


# ======================================================================= manifest
def _build_manifest(c):
    W = c.week
    # Kalshi
    ev, kt = kalshi_week_events(c.p('kalshi.csv'), W)
    if ev is not None:
        _, rows = c.csv('kalshi.csv')
        c.note('kalshi', 'kalshi.csv', kt, 'pulled_at column', week=W if ev else None, rows=len(rows),
               extra=dict(in_week_events=len(ev)))
    arch = sorted(glob.glob(c.p('kalshi_archive', 'kalshi_*.csv')))
    if arch:
        m = re.search(r'kalshi_(\d{4}-\d{2}-\d{2}T\d{4}Z)', arch[-1])
        c.note('kalshi_archive', os.path.relpath(arch[-1], c.d), T.try_ts(m.group(1), 'archive') if m else None,
               'archive file stamp', rows=len(arch))
    # schedule, props
    _, g = c.csv('espn_games.csv')
    if g is not None:
        t, src = c.as_of('espn_games.csv')
        c.note('espn_games', 'espn_games.csv', t, src, week=W if c.games() else None, rows=len(g))
    _, pr = c.csv('espn_props.csv')
    if pr is not None:
        t, src = c.as_of('espn_props.csv')
        c.note('espn_props', 'espn_props.csv', t, src, rows=len(pr), extra=dict(event_ids=sorted({r.get('event_id') for r in pr})[:8]))
    # Sleeper + usage + trending
    for kind in ('off', 'idp'):
        rel = f'sleeper_{kind}_wk{W}.csv'
        _, rr = c.csv(rel)
        t, src = c.as_of(rel)
        c.note(f'sleeper_{kind}', rel, t, src, week=W, rows=len(rr) if rr is not None else 0,
               extra=None if rr is not None else dict(missing=True))
    for uw in (W - 1, W):
        rels = [f'usage_wk{uw}_{p}.csv' for p in ('QB', 'RB', 'WR', 'TE') if os.path.exists(c.p(f'usage_wk{uw}_{p}.csv'))]
        if not rels: continue
        ts = [c.as_of(r) for r in rels]
        known = [t for t, _ in ts if t]
        c.note(f'usage_wk{uw}', rels[0], max(known) if known and len(known) == len(ts) else None,
               ts[0][1] if known and len(known) == len(ts) else 'unknown for some position file', week=uw,
               rows=sum(len(c.csv(r)[1] or []) for r in rels))
    if os.path.exists(c.p('trending_adds.csv')):
        t, src = c.as_of('trending_adds.csv'); c.note('trending', 'trending_adds.csv', t, src, rows=len(c.csv('trending_adds.csv')[1] or []))
    # rosters, transactions, matchups, actuals, Yahoo projections
    for lg in ALL:
        s = c.snap(lg)
        if s:
            t = T.try_ts(s['j'].get('pulled'), 'state')
            c.note(f'rosters_{lg}', os.path.relpath(s['path'], c.d), t, 'snapshot pulled', week=C.nfl_week(t) if t else None,
                   rows=len(s['j'].get('rows', [])), extra=dict(others_pulled=s['j'].get('others_pulled')))
        rel = 'bsb_transactions.csv' if lg == 'BSB' else 'hh_transactions.csv'
        _, tr = c.csv(rel)
        if tr is not None:
            t, src = c.as_of(rel)
            if t is None:
                _, raw = c.csv(f'yahoo/{lg}_transactions.csv')
                st = [T.try_ts(r.get('pulled_at'), 'pump') for r in raw or []]
                st = [x for x in st if x]
                if st: t, src = max(st), 'raw page pulled_at'
            c.note(f'transactions_{lg}', rel, t, src, rows=len(tr))
        rel = f'actuals/{lg}_wk{W}.csv'
        _, ar = c.csv(rel)
        if ar is not None:
            st = [x for x in (T.try_ts(r.get('pulled_at'), 'pump') for r in ar if r.get('pulled_at')) if x]
            t, src = (max(st), 'pulled_at column') if st else c.as_of(rel)
            c.note(f'actuals_{lg}', rel, t, src, week=W, rows=len(ar))
        rel = f'yahoo_{lg}_wk{W}.csv'
        _, yr = c.csv(rel)
        if yr is not None:
            st = [x for x in (T.try_ts(r.get('pulled_at'), 'pump') for r in yr if r.get('pulled_at')) if x]
            t, src = (max(st), 'pulled_at column') if st else c.as_of(rel)
            c.note(f'yahoo_proj_{lg}', rel, t, src, week=W, rows=len(yr))
        rel = f'yahoo/{lg}_matchup_wk{W}.csv'
        _, mr = c.csv(rel)
        if mr is not None:
            st = [x for x in (T.try_ts(r.get('pulled_at'), 'pump') for r in mr) if x]
            c.note(f'matchup_{lg}', rel, max(st) if st else None, 'pulled_at column', week=W, rows=len(mr))
    mp = c.p('matchups.json')
    if os.path.exists(mp):
        try: mj = json.load(open(mp))
        except Exception: mj = None
        for lg in ALL:
            if not isinstance(mj, dict): break
            t, src = None, 'unknown'
            pv = ((mj.get('_pulled') or {}).get(str(W)) or {}).get(lg)
            if pv: t, src = T.try_ts(pv, 'pump'), '_pulled'
            if t is None:
                ms = re.findall(rf'wk{W} {lg} from the pump (\S+)', mj.get('_src') or '')
                if ms: t, src = T.try_ts(ms[-1], 'pump'), '_src'
            if t is None: t, src = c.as_of(f'matchups.json#{W}/{lg}')
            c.note(f'matchups_{lg}', 'matchups.json', t, src, week=W if (mj.get(str(W)) or {}).get(lg) else None,
                   extra=dict(opponent=(mj.get(str(W)) or {}).get(lg)))
    # pump
    pw, pt = None, None
    _, _x = None, None
    pp = c.p('yahoo', 'pulled.txt')
    if os.path.exists(pp):
        first = open(pp).readline()
        m = re.search(r'pull (\S+) week (\d+)', first)
        if m: pt, pw = T.try_ts(m.group(1), 'pump'), int(m.group(2))
        c.note('pump', 'yahoo/pulled.txt', pt, 'pulled.txt header', week=pw)
    elif c.pump:
        c.note('pump', 'pulls/ffdata_pull.md', c.pump.get('head'), 'ffdata_pull.md', week=c.pump.get('week'))
    # registry, ledger
    if os.path.exists(c.p('roles.json')):
        try: j = json.load(open(c.p('roles.json'))); t = T.try_ts(str(j.get('_checked', ''))[:10], 'date')
        except Exception: t = None
        c.note('roles', 'roles.json', t, '_checked')
    if os.path.exists(c.p('ledger.json')):
        try:
            L = json.load(open(c.p('ledger.json')))
            st = [x for x in (T.try_ts(e.get('ts'), 'ledger') for e in L if isinstance(e, dict)) if x]
            t = max(st) if st else None
        except Exception: t, L = None, []
        c.note('ledger', 'ledger.json', t, 'newest entry ts', rows=len(L) if isinstance(L, list) else None)


def manifest(root=None, now=None, week=None):
    """{input: {path, as_of, as_of_src, week, rows, sha}} — every input the engine reads,
    with its as-of from content. 'unknown' where the file carries none."""
    root = root or ROOT; now = now or C.now(); week = week or data_week(root, now)
    c = _Ctx(root, now, week, REPO, True)
    _build_manifest(c)
    return c.manifest


# ======================================================================= invariants
def c1(c):
    out = []; W = c.week
    pm = c.manifest.get('pump')
    if pm and pm.get('week') is not None and pm['week'] != W:
        out.append(Violation('C1', REFUSE, f"pump/loader week {pm['week']} ({pm['as_of_src']}) is not the engine's data week {W} — "
                             f'the pull and the projections describe different weeks', evidence=dict(pump=pm, data_week=W)))
    if W > C.nfl_week(c.now):
        out.append(Violation('C1', REFUSE, f'engine week {W} is ahead of the calendar week {C.nfl_week(c.now)}'))
    so = c.manifest.get('sleeper_off') or {}
    if (so.get('rows') or 0) < SLEEPER_MIN_ROWS:
        out.append(Violation('C1', REFUSE, f"sleeper_off_wk{W}.csv has {so.get('rows') or 0} rows (< {SLEEPER_MIN_ROWS}) — no projection base for week {W}"))
    lo, hi = C.week_start(W), C.week_start(W + 1) + WEEK_TAIL
    for lg in ALL:
        for nm, what in ((f'rosters_{lg}', 'roster snapshot'), (f'actuals_{lg}', 'actuals'), (f'matchups_{lg}', 'matchup'),
                         (f'yahoo_proj_{lg}', 'Yahoo projections'), (f'matchup_{lg}', 'matchup page')):
            if nm not in c.manifest:
                if nm == f'rosters_{lg}': out.append(Violation('C1', REFUSE, f'{lg}: no roster snapshot on disk'))
                continue
            t = c.t.get(nm)
            if nm.startswith('matchups_') and c.manifest[nm].get('week') is None:
                out.append(Violation('C1', DEGRADE, f'{lg}: no week-{W} opponent in matchups.json')); continue
            if t is None:
                out.append(Violation('C1', DEGRADE, f'{lg}: {what} for week {W} has no as-of in its content — unknown, not assumed current',
                                     evidence=c.manifest[nm].get('path')))
            elif not (lo <= t < hi):
                out.append(Violation('C1', REFUSE, f'{lg}: {what} pulled {_fmt(t)} is outside week {W} '
                                     f'[{_fmt(lo)}, {_fmt(hi)})', evidence=c.manifest[nm].get('path')))
    return out

def _stamp_checks(c, items):
    out = []
    for where, s, src, future_ok in items:
        if s in (None, ''): continue
        try: t = T.parse_ts(s, src, now=c.now)
        except T.TsError as e:
            out.append(Violation('C2', REFUSE, f'{where}: {e}', evidence=s)); continue
        if not future_ok and t > c.now + FUTURE_GRACE:
            out.append(Violation('C2', REFUSE, f'{where}: stamp {s!r} = {_fmt(t)} is in the future — a UTC time written as ET (or a wrong clock)', evidence=s))
    return out

def c2(c):
    items = []
    for lg in ALL:
        s = c.snap(lg)
        if s:
            items += [(f'{lg} snapshot pulled', s['j'].get('pulled'), 'state', False),
                      (f'{lg} snapshot others_pulled', s['j'].get('others_pulled'), 'state', False),
                      (f'{lg} snapshot name', os.path.basename(s['path'])[:-5], 'snapshot', False)]
        for rel in (f'yahoo/{lg}_rosters.csv', f'yahoo/{lg}_matchup_wk{c.week}.csv', f'yahoo/{lg}_transactions.csv',
                    f'actuals/{lg}_wk{c.week}.csv', f'yahoo_{lg}_wk{c.week}.csv'):
            _, rr = c.csv(rel)
            for v in sorted({r.get('pulled_at') for r in rr or [] if r.get('pulled_at')}):
                items.append((f'{rel} pulled_at', v, 'pump', False))
        _, raw = c.csv(f'yahoo/{lg}_transactions.csv')
        for r in raw or []:
            ref = T.try_ts(r.get('pulled_at'), 'pump') or c.now
            try: T.parse_ts(r.get('ts'), 'yahoo_page', now=ref)
            except T.TsError as e: items.append((f'yahoo/{lg}_transactions.csv ts', r.get('ts'), 'yahoo_page', False))
    _, kr = c.csv('kalshi.csv')
    for v in sorted({r.get('pulled_at') for r in kr or []}):
        items.append(('kalshi.csv pulled_at', v if v else '<empty>', 'kalshi', False))
    for f in glob.glob(c.p('kalshi_archive', '*.csv')):
        m = re.search(r'kalshi_(.+)\.csv$', os.path.basename(f))
        items.append((f'archive {os.path.basename(f)}', m.group(1) if m else os.path.basename(f), 'archive', False))
    _, gr = c.csv('espn_games.csv')
    for r in gr or []:
        items.append((f"espn_games.csv kickoff (event {r.get('event_id')})", r.get('kickoff') or '<empty>', 'espn', True))
    p = c.p('asof.json')
    if os.path.exists(p):
        try:
            for f, v in (json.load(open(p)).get('files') or {}).items(): items.append((f'asof.json {f}', v.get('as_of'), 'pump', False))
        except Exception as e:
            return [Violation('C2', REFUSE, f'asof.json does not parse: {e}')]
    if os.path.exists(c.p('matchups.json')):
        try:
            for w, d in (json.load(open(c.p('matchups.json'))).get('_pulled') or {}).items():
                for lg, v in d.items(): items.append((f'matchups.json _pulled {w}/{lg}', v, 'pump', False))
        except Exception: pass
    if os.path.exists(c.p('ledger.json')):
        try:
            for e in json.load(open(c.p('ledger.json'))):
                items.append((f"ledger {e.get('id')} ts", e.get('ts'), 'ledger', False))
                if e.get('status_ts'): items.append((f"ledger {e.get('id')} status_ts", e.get('status_ts'), 'ledger', False))
        except Exception: pass         # C16 reports the parse error
    return _stamp_checks(c, items)

def c3(c):
    out = []
    for lg in ALL:
        s = c.snap(lg)
        if not s: continue
        t = T.try_ts(s['j'].get('pulled'), 'state'); to = T.try_ts(s['j'].get('others_pulled') or s['j'].get('pulled'), 'state')
        a = T.age_h(t, c.now) if t else None
        ao = max(a, T.age_h(to, c.now)) if (t and to) else None
        if a is None or a > FRESH_H['rosters_lineup']:
            why = f'{lg} rosters ' + (f'{a:.0f}h old (> {FRESH_H["rosters_lineup"]:.0f}h for a lineup call)' if a is not None else 'as-of unknown')
            c.flags['roster_lineup'].append(why); out.append(Violation('C3', DEGRADE, why + ' — lineup calls are PROVISIONAL'))
        if ao is None or ao > FRESH_H['rosters_add_drop']:
            why = f'{lg} league read ' + (f'{ao:.0f}h old (> {FRESH_H["rosters_add_drop"]:.0f}h for an add/drop)' if ao is not None else 'as-of unknown')
            c.flags['add_drop'][lg].append(why); out.append(Violation('C3', DEGRADE, why + ' — adds and drops BLOCK'))
    feed = []
    for nm, lab, lim in (('kalshi', 'Kalshi', FRESH_H['kalshi']), ('sleeper_off', 'Sleeper', FRESH_H['sleeper'])):
        a = c.flags['ages'].get(nm)
        if nm not in c.manifest or a is None: feed.append(f'{lab} as-of unknown')
        elif a > lim: feed.append(f'{lab} {a:.0f}h old (> {lim:.0f}h)')
    sched = c.sched()
    near = []
    for lg in ALL:
        st = c.state(lg)
        if not st: continue
        for r in st.starters():
            k = sched.get(r['tm'])
            if k and C.lineup_phase(k) in ('decide', 'alert') and k - c.now > dt.timedelta(0):
                near.append(f"{lg} {r['player']}")
    c.flags['feed'] = feed
    c.flags['feed_now'] = bool(near)
    if feed:
        out.append(Violation('C3', DEGRADE if near else WARN,
                             f"{'; '.join(feed)} — " + (f'lineup calls on games inside 36h are PROVISIONAL ({len(near)} starters: {", ".join(near[:4])}{"…" if len(near) > 4 else ""})'
                                                        if near else 'no starter is inside the 36h decide window yet'),
                             evidence=dict(ages={k: c.flags['ages'].get(k) for k in ('kalshi', 'sleeper_off')})))
    return out

def _shape(lg, rows, owners_key='owner'):
    cfg = ALL[lg]; out = []
    lo, hi = len(cfg.slots) + cfg.bench - 2, len(cfg.slots) + cfg.bench + cfg.ir_slots
    players = [r for r in rows if (r.get('player') or '').strip()]
    owners = sorted({r.get(owners_key) for r in players})
    if len(owners) != cfg.managers:
        out.append(f'{len(owners)} rostered teams, the league has {cfg.managers} — a missing team page turns its whole roster into free agents')
    if cfg.name not in owners:
        out.append(f'my team {cfg.name!r} is not among the owners')
    emp = [f"{r.get(owners_key)} {r.get('slot')}" for r in players if '--empty--' in (r.get('player') or '').lower()]
    if emp: out.append(f"'--empty--' rows (an empty slot parsed as a player): {', '.join(emp[:4])}")
    cnt = Counter(r.get(owners_key) for r in players)
    off = {o: n for o, n in cnt.items() if not (lo <= n <= hi)}
    if off: out.append(f'rows per team outside [{lo}, {hi}]: {off}')
    return out

def c4(c):
    out = []
    for lg in ALL:
        s = c.snap(lg)
        if not s: out.append(Violation('C4', REFUSE, f'{lg}: no roster snapshot')); continue
        for m in _shape(lg, s['j'].get('rows', [])):
            out.append(Violation('C4', REFUSE, f'{lg} snapshot {os.path.basename(s["path"])}: {m}'))
        _, raw = c.csv(f'yahoo/{lg}_rosters.csv')
        if raw:
            for m in raw_roster_shape(lg, raw):
                out.append(Violation('C4', REFUSE, f'{lg} yahoo/{lg}_rosters.csv: {m}'))
    return out

def raw_roster_shape(lg, raw):
    """C4 on the pump's roster CSV (team_id per owner, my team id, shape)."""
    cfg = ALL[lg]; out = _shape(lg, raw)
    ids = defaultdict(set); own = defaultdict(set)
    for r in raw:
        ids[r.get('team_id')].add(r.get('owner')); own[r.get('owner')].add(r.get('team_id'))
    dup = {i: sorted(o) for i, o in ids.items() if len(o) > 1}
    dup2 = {o: sorted(i) for o, i in own.items() if len(i) > 1}
    if dup or dup2: out.append(f'team_id <-> owner is not one-to-one: {dup or dup2}')
    if str(cfg.team) not in ids or cfg.name not in ids.get(str(cfg.team), set()):
        out.append(f'team_id {cfg.team} is not {cfg.name!r} ({sorted(ids.get(str(cfg.team), []))})')
    return out

def c5(c):
    out = []
    for lg in ALL:
        st = c.state(lg)
        if not st: continue
        cfg = st.cfg; mx = len(cfg.slots) + cfg.bench + cfg.ir_slots
        where = defaultdict(set)
        for r in st.rows: where[r['key']].add(r['owner'])
        dup = {k: sorted(o) for k, o in where.items() if len(o) > 1}
        if dup:
            out.append(Violation('C5', REFUSE, f'{lg}: after replaying the transactions log, {len(dup)} player(s) sit on two rosters — '
                                 f'a frozen team page the log cannot correct: ' + '; '.join(f'{k} on {", ".join(v)}' for k, v in list(dup.items())[:4]),
                                 evidence=dict(duplicates=dup, reconciled=st.reconciled)))
        over = {o: len(rs) for o, rs in st.by_owner.items() if len(rs) > mx}
        if over:
            out.append(Violation('C5', REFUSE, f'{lg}: team(s) over the {mx}-player maximum after reconcile: {over}', evidence=dict(reconciled=st.reconciled)))
    return out

def c6(c):
    out = []
    for lg in ALL:
        st = c.state(lg)
        if st:
            for m in def_key_violations(st.rows, lg): out.append(Violation('C6', REFUSE, m))
        _, raw = c.csv(f'yahoo/{lg}_rosters.csv')
        for r in raw or []:
            if (r.get('pos') or '').upper() == 'DEF' and (r.get('player') or '').strip() and team(r.get('nfl') or '') not in DST_FULL:
                out.append(Violation('C6', REFUSE, f"{lg} yahoo/{lg}_rosters.csv: DEF '{r.get('player')}' on {r.get('owner')} has nfl {r.get('nfl')!r}"))
    return out

def c7(c):
    out = []
    for lg in ALL:
        s = c.snap(lg)
        if not s: continue
        unk = defaultdict(list)
        for r in s['j'].get('rows', []):
            d = r.get('designation')
            if RU.unknown_tags([d]): unk[d].append(r.get('player'))
        for r in c.csv(f'yahoo/{lg}_rosters.csv')[1] or []:
            d = r.get('status') or ''
            if RU.unknown_tags([d]) and r.get('player'): unk[d].append(r.get('player'))
        for d, who in unk.items():
            out.append(Violation('C7', WARN, f'{lg}: designation {d!r} is not in the vocabulary (rules.VOCAB) — treated as clear until a person files it: {", ".join(sorted(set(who))[:5])}'))
    return out

def c8(c):
    out = []
    ev, kt = kalshi_week_events(c.p('kalshi.csv'), c.week)
    if not ev: return out
    sched = c.sched()
    status = {}
    for g in c.games():
        st_ = 'final' if 'FINAL' in g['status'] else ('live' if ('PROGRESS' in g['status'] or 'HALFTIME' in g['status'] or 'END_PERIOD' in g['status']) else None)
        if st_: status[g['away']] = status[g['home']] = (st_, 'ESPN ' + g['status'])
    for tm, cnt in c.yahoo_games().items():
        for txt in cnt:
            s_ = T.yahoo_game_state(txt)
            if s_ in ('live', 'final') and tm not in status: status[tm] = (s_, f'Yahoo {txt!r}')
    games = defaultdict(lambda: dict(events=set(), series=set()))
    for e, v in ev.items():
        games[v['code']]['events'].add(e); games[v['code']]['series'] |= v['series']; games[v['code']]['teams'] = v['teams']
    unknown, stale = [], []
    for code, g in sorted(games.items()):
        tms = g.get('teams')
        if not tms:
            unknown.append(f'{code} (teams not resolvable)'); continue
        k = sched.get(tms[0]) or sched.get(tms[1])
        if k is None:
            unknown.append(f'{code} ({len(g["events"])} events)'); continue
        if k <= c.now: continue                                   # the live guard drops these
        st_ = status.get(tms[0]) or status.get(tms[1])
        if st_:
            stale.append(f'{code}: {st_[1]} but the schedule kickoff {_fmt(k)} is still ahead — its ladders would be read as pregame')
        if kt and kt >= k:
            stale.append(f'{code}: ladders as of {_fmt(kt)} are not before kickoff {_fmt(k)}')
    if unknown:
        out.append(Violation('C8', REFUSE, f'{len(unknown)} in-week Kalshi game(s) have no known kickoff, so the live guard cannot drop '
                             f'their in-game ladders: ' + ', '.join(unknown[:6]), evidence=unknown))
    for s_ in stale:
        out.append(Violation('C8', REFUSE, s_))
    return out

def check_projections(P, now=None):
    """C8 after Projections is built: no event of a kicked-off game is left in the
    pregame set, and no Kalshi game line of a kicked-off game overrides the schedule."""
    now = now or C.now(); out = []
    kicked = {t for t, k in (P.kick or {}).items() if k and k <= now}
    left = sorted(e for e in getattr(P, 'in_week_events', set())
                  if (lambda tms: tms and (tms[0] in kicked or tms[1] in kicked))(_teams_of(e.split('-', 1)[1][7:])))
    if left:
        out.append(Violation('C8', REFUSE, f'{len(left)} Kalshi event(s) of games already kicked off reached pregame projections: {", ".join(left[:4])}', evidence=left[:20]))
    kg = [f'{a}@{h}' for (a, h) in (getattr(P, 'kal_games', {}) or {}) if a in kicked or h in kicked]
    if kg:
        out.append(Violation('C8', REFUSE, f'in-game Kalshi spread/total ladders override the line for {", ".join(kg[:4])}', evidence=kg))
    return out

def c9(c):
    out = []
    yg = c.yahoo_games()
    if not yg: return out
    raw = c.sched(engine=False); eng = c.sched(engine=True)
    for tm, cnt in sorted(yg.items()):
        pre = [(txt, n) for txt, n in cnt.items() if T.yahoo_game_state(txt) == 'pre']
        if not pre: continue
        txt = max(pre, key=lambda x: x[1])[0]
        try: ty = T.parse_ts(txt, 'yahoo_game', week_start=c.w0)
        except T.TsError: continue
        ks = raw.get(tm)
        if ks is None or abs(ks - ty) > KICK_TOL:
            c.flags['kick_override'][tm] = ty
            out.append(Violation('C9', DEGRADE, f'{tm}: schedule kickoff ' + (f'{_fmt(ks)}' if ks else 'missing') +
                                 f' vs Yahoo {txt!r} = {_fmt(ty)} — using Yahoo\'s time', evidence=dict(schedule=_fmt(ks) if ks else None, yahoo=txt)))
        elif tm not in eng:
            c.flags['kick_override'][tm] = ty           # schedule row without a line: Projections would not see its kickoff
    return out

def c10(c):
    _, pr = c.csv('espn_props.csv')
    if not pr: return []
    ids = {r.get('event_id') for r in pr}
    wk = {g['event_id'] for g in c.games() if g.get('event_id')}
    foreign = sorted(ids - wk)
    if foreign:
        return [Violation('C10', REFUSE, f'espn_props.csv carries {len(foreign)} event id(s) that are not week-{c.week} games '
                          f'(e.g. {", ".join(foreign[:3])}) — props from another week are never applied', evidence=foreign[:10], drops='espn_props.csv')]
    return []

def c11(c):
    out = []
    cur, ct = kalshi_week_events(c.p('kalshi.csv'), c.week)
    if not cur or ct is None: return out
    prev = None
    for f in sorted(glob.glob(c.p('kalshi_archive', 'kalshi_*.csv'))):
        m = re.search(r'kalshi_(\d{4}-\d{2}-\d{2}T\d{4}Z)', f)
        t = T.try_ts(m.group(1), 'archive') if m else None
        if t and c.w0 <= t < c.w1 and t < ct - dt.timedelta(minutes=1): prev = (t, f)
    if not prev: return out
    pev, _ = kalshi_week_events(prev[1], c.week)
    sched = c.sched()
    def live(v):
        tms = v['teams']; k = (sched.get(tms[0]) or sched.get(tms[1])) if tms else None
        return k is not None and k <= c.now
    P_ = {e: v for e, v in (pev or {}).items() if not live(v)}
    C_ = {e: v for e, v in cur.items() if not live(v)}
    if not P_: return out
    kept = len(set(P_) & set(C_)) / len(P_)
    bad = []
    if kept < KALSHI_EVENTS_MIN:
        bad.append(f'{len(set(P_) & set(C_))}/{len(P_)} of the previous pull\'s pregame events are present ({kept:.0%} < {KALSHI_EVENTS_MIN:.0%})')
    ps, cs = defaultdict(set), defaultdict(set)
    for v in P_.values(): ps[v['code']] |= v['series']
    for v in C_.values(): cs[v['code']] |= v['series']
    thin = {g: (len(cs.get(g, ())), len(s)) for g, s in ps.items() if len(cs.get(g, ())) < len(s) - 1}
    if thin: bad.append('series per game fell by more than one: ' + ', '.join(f'{g} {a}/{b}' for g, (a, b) in list(thin.items())[:5]))
    if bad:
        c.flags['steam_gone_off'] = '; '.join(bad)
        out.append(Violation('C11', DEGRADE, f'Kalshi pull {_fmt(ct)} is incomplete against {os.path.basename(prev[1])}: ' + '; '.join(bad) +
                             " — 'markets withdrawn = OUT' is not inferred from this pull", evidence=dict(previous=os.path.basename(prev[1]))))
    return out

def c12(c):
    out = []
    for lg in ALL:
        rel = 'bsb_transactions.csv' if lg == 'BSB' else 'hh_transactions.csv'
        fields, rows = c.csv(rel)
        if rows is None: continue
        problems = []
        for i, r in enumerate(rows, 2):
            if T.try_ts(r.get('datetime'), 'yahoo_log') is None: problems.append(f'line {i}: datetime {r.get("datetime")!r}')
            elif r.get('action') not in ('Add', 'Drop'): problems.append(f'line {i}: action {r.get("action")!r}')
            elif not (r.get('player') or '').strip() or not (r.get('team') or '').strip(): problems.append(f'line {i}: no player/team')
        nm = f'transactions_{lg}'
        t = c.t.get(nm); rt = c.t.get(f'rosters_{lg}')
        if t is None: problems.append('transactions log as-of unknown')
        elif rt is not None and t < rt - dt.timedelta(minutes=1):
            problems.append(f'transactions log as of {_fmt(t)} is OLDER than the rosters ({_fmt(rt)}) — moves since then cannot correct a frozen team page')
        if problems:
            why = f'{lg} transactions log: ' + '; '.join(problems[:3]) + (f' (+{len(problems) - 3} more)' if len(problems) > 3 else '')
            if lg == 'BSB': c.flags['add_drop'][lg].append(why)
            out.append(Violation('C12', DEGRADE, why + (' — BSB adds and drops BLOCK' if lg == 'BSB' else ''), evidence=problems[:10]))
    return out

def c14(c):
    out = []
    try: mj = json.load(open(c.p('matchups.json'))) if os.path.exists(c.p('matchups.json')) else {}
    except Exception as e: return [Violation('C14', REFUSE, f'matchups.json does not parse: {e}')]
    for lg in ALL:
        cfg = ALL[lg]; st = c.state(lg)
        owners = set(st.by_owner) if st else set()
        opp = (mj.get(str(c.week)) or {}).get(lg)
        if opp is not None and owners and (opp not in owners or opp == cfg.name):
            out.append(Violation('C14', REFUSE, f'{lg}: week-{c.week} opponent {opp!r} in matchups.json is not another roster owner'))
        _, mr = c.csv(f'yahoo/{lg}_matchup_wk{c.week}.csv')
        if not mr: continue
        me = {r.get('owner') for r in mr if r.get('side') == 'me'}
        op = {r.get('owner') for r in mr if r.get('side') == 'opp'}
        if me != {cfg.name}:
            out.append(Violation('C14', REFUSE, f"{lg}: matchup page 'me' side is {sorted(me)}, not {cfg.name!r}"))
        if len(op) != 1 or (owners and not op <= owners) or cfg.name in op:
            out.append(Violation('C14', REFUSE, f"{lg}: matchup page opponent {sorted(op)} is not exactly one other roster owner"))
        if opp is not None and op and opp not in op:
            out.append(Violation('C14', REFUSE, f'{lg}: matchups.json says {opp!r}, the matchup page says {sorted(op)}'))
        for side in ('me', 'opp'):
            rs = [r for r in mr if r.get('side') == side]
            if not rs: continue
            tots = {r.get('total') for r in rs}
            if len(tots) != 1 or not _num(next(iter(tots))):
                out.append(Violation('C14', REFUSE, f'{lg} {side}: side total is not one number: {sorted(tots)}')); continue
            tot = float(next(iter(tots)))
            s = sum(float(r['fan_pts']) for r in rs if r.get('slot') not in ('BN', 'IR') and _num(r.get('fan_pts')))
            if abs(tot - s) > 0.05:
                out.append(Violation('C14', REFUSE, f'{lg} {side}: posted total {tot:.2f} != sum of starter rows {s:.2f} — the rows are not the page', evidence=dict(total=tot, rows=round(s, 2))))
    return out

# required columns, numeric columns (blank allowed), numeric columns where Yahoo's dash is allowed
SPEC = {
    'kalshi.csv': (('event', 'series', 'ticker', 'title', 'yes_bid', 'yes_ask', 'last_price', 'pulled_at'), ('yes_bid', 'yes_ask', 'last_price'), ()),
    'espn_games.csv': (('event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under'), ('spread', 'over_under'), ()),
    'espn_props.csv': (('event_id', 'player', 'prop_type', 'line'), (), ('line',)),       # DraftKings writes 'NONE' for a missing line
    'sleeper_off_wk{W}.csv': (('player', 'team', 'pos', 'pts_ppr'), ('pts_ppr', 'rec', 'rec_yd', 'rush_yd', 'pass_yd'), ()),
    'sleeper_idp_wk{W}.csv': (('player', 'team', 'pos', 'solo', 'ast'), ('solo', 'ast', 'sack'), ()),
    'yahoo_{LG}_wk{W}.csv': (('player', 'tm', 'pos', 'pts'), ('pts',), ()),
    'actuals/{LG}_wk{W}.csv': (('owner', 'slot', 'player', 'tm', 'status', 'pts', 'final'), ('pts',), ()),
    '{lg}_transactions.csv': (('datetime', 'team', 'action', 'player'), (), ()),
    'usage_wk{U}_{POS}.csv': (('first_name', 'last_name', 'team', 'off_snp', 'tm_off_snp'), ('off_snp', 'tm_off_snp'), ()),
    'yahoo/{LG}_rosters.csv': (('team_id', 'owner', 'slot', 'player', 'nfl', 'pos', 'status', 'game', 'fan_pts', 'proj_pts', 'pulled_at'), (), ('fan_pts', 'proj_pts')),
    'yahoo/{LG}_matchup_wk{W}.csv': (('side', 'team_id', 'owner', 'total', 'slot', 'player', 'nfl', 'game', 'fan_pts', 'proj_pts', 'pulled_at'), ('total',), ('fan_pts', 'proj_pts')),
    'yahoo/{LG}_transactions.csv': (('ts', 'team', 'player', 'kind', 'action', 'pulled_at'), (), ()),
}
POINTS_COLS = ('pts', 'pts_ppr', 'fan_pts', 'proj_pts', 'total', 'line')

def columns_violations(rel, fields, rows, spec):
    """C15 for one file -> list of messages."""
    req, num, dash = spec; out = []
    miss = [f for f in req if f not in (fields or [])]
    if miss: return [f'{rel}: missing required column(s) {miss}']
    for col in num + dash:
        if col not in fields: continue
        badv = []
        for i, r in enumerate(rows, 2):
            v = (r.get(col) or '').strip()
            if '%' in v: badv.append(f'line {i} {col}={v!r} (a percentage in a points column)'); continue
            blank = (v in YAHOO_BLANK) if col in dash else (v == '')
            if blank: continue
            if not _num(v): badv.append(f'line {i} {col}={v!r}')
        if badv: out.append(f'{rel}: {len(badv)} non-numeric value(s) in {col}: ' + '; '.join(badv[:3]))
    for col in POINTS_COLS:
        if col in fields and col not in num + dash:
            pc = [i for i, r in enumerate(rows, 2) if '%' in (r.get(col) or '')]
            if pc: out.append(f"{rel}: '%' in points column {col} on line(s) {pc[:3]}")
    return out

def _spec_files(c):
    W = c.week
    for pat, spec in SPEC.items():
        names = []
        if '{LG}' in pat: names = [pat.replace('{LG}', lg).replace('{W}', str(W)) for lg in ALL]
        elif '{lg}' in pat: names = [pat.replace('{lg}', lg) for lg in ('bsb', 'hh')]
        elif '{U}' in pat: names = [pat.replace('{U}', str(u)).replace('{POS}', p) for u in (W - 1, W) for p in ('QB', 'RB', 'WR', 'TE')]
        else: names = [pat.replace('{W}', str(W))]
        for n in names: yield n, spec

def c15(c):
    out = []
    for rel, spec in _spec_files(c):
        fields, rows = c.csv(rel)
        if rows is None: continue
        for m in columns_violations(rel, fields, rows, spec):
            # a points-only FALLBACK source (props, Yahoo's projections off the team pages)
            # is dropped, not the run: Yahoo's Sunday pages put a percentage in the
            # points column (10-04, 14 rows) and the run must still decide
            fallback = rel == 'espn_props.csv' or rel.startswith('yahoo_')
            out.append(Violation('C15', REFUSE, m, drops=rel if fallback else None))
    return out

def c16(c):
    out = []
    p = c.p('roles.json')
    try:
        R = RU.load_roles(p, strict=True, today=c.now.date())
        dem = R.get('_demoted_add_yes') or {}
        fresh_dem = {k: v for k, v in dem.items() if not k.startswith('_')}
        if fresh_dem:
            out.append(Violation('C16', WARN, f'{len(fresh_dem)} add_yes registry entr{"y" if len(fresh_dem) == 1 else "ies"} older than {RU.ADD_YES_DAYS} days demoted '
                                 f'(no longer verified usage): ' + ', '.join(f"{k} ({v.get('as_of')})" for k, v in list(fresh_dem.items())[:5])))
    except ValueError as e:
        out.append(Violation('C16', REFUSE, f'roles.json: {e} — the registry never silently becomes {{}}'))
    p = c.p('ledger.json')
    if os.path.exists(p):
        try:
            L = json.load(open(p))
            if not isinstance(L, list) or not all(isinstance(e, dict) for e in L): raise ValueError('not a list of entries')
        except Exception as e:
            out.append(Violation('C16', REFUSE, f'ledger.json does not parse ({e}) — the ledger never silently becomes []; nothing is written over it'))
    return out

def c17(c):
    if c.in_action: return []
    rd = os.path.join(c.repo or '', 'engine', 'data')
    if not c.repo or not os.path.isdir(rd): return []
    if os.path.realpath(rd) == os.path.realpath(c.d): return []
    out = []
    def newest_ledger(d):
        try:
            L = json.load(open(os.path.join(d, 'ledger.json')))
            ts = [T.try_ts(e.get(k), 'ledger') for e in L for k in ('ts', 'status_ts') if e.get(k)]
            ts = [t for t in ts if t]
            return max(ts) if ts else None
        except Exception: return None
    a, b = newest_ledger(rd), newest_ledger(c.d)
    if a and (b is None or a > b + dt.timedelta(minutes=1)):
        out.append(Violation('C17', REFUSE, f'the pump repo\'s engine/data/ledger.json is newer ({_fmt(a)}) than the local one ({_fmt(b) if b else "none"}) — '
                             'the repo is the authoritative record; refresh the local copy before deciding anything here'))
    for lg in ALL:
        fr = sorted(glob.glob(os.path.join(rd, 'state', lg, '*.json'))); fl = sorted(glob.glob(c.p('state', lg, '*.json')))
        if not fr: continue
        def pulled(f):
            try: return T.try_ts(json.load(open(f)).get('pulled'), 'state')
            except Exception: return None
        ta, tb = pulled(fr[-1]), (pulled(fl[-1]) if fl else None)
        if ta and (tb is None or ta > tb + dt.timedelta(minutes=1)):
            out.append(Violation('C17', REFUSE, f'{lg}: the pump repo\'s newest snapshot ({os.path.basename(fr[-1])}, pulled {_fmt(ta)}) is newer than the local one '
                                 f'({os.path.basename(fl[-1]) if fl else "none"}{", pulled " + _fmt(tb) if tb else ""})'))
    return out

CHECKS = [('C1', c1), ('C2', c2), ('C9', c9), ('C3', c3), ('C4', c4), ('C5', c5), ('C6', c6), ('C7', c7), ('C8', c8),
          ('C10', c10), ('C11', c11), ('C12', c12), ('C14', c14), ('C15', c15), ('C16', c16), ('C17', c17)]

def check(root=None, now=None, week=None, repo=None, only=None, in_action=None):
    """Run every invariant against the inputs under `root` -> Result.
    now: the decision time (default the real clock); week: the engine's data week
    (default data_week(root, now)); only: an iterable of codes to run (tests)."""
    root = root or ROOT; now = (now or C.now()).astimezone(C.ET); week = week or data_week(root, now)
    if in_action is None: in_action = bool(os.environ.get('FFDATA_IN_ACTION'))
    c = _Ctx(root, now, week, REPO if repo is None else repo, in_action)
    vs = []
    try:
        _build_manifest(c)
    except Exception as e:                        # a manifest that cannot be built is an input that cannot be read
        vs.append(Violation('C15', REFUSE, f'manifest could not be built: {e!r}'))
    for code, fn in CHECKS:                        # C9 runs before C3/C8: they read its kickoff overrides
        if only and code not in only: continue
        try:
            vs += fn(c)
        except Exception as e:
            vs.append(Violation(code, REFUSE, f'{code} could not be evaluated: {e!r}'))
    return Result(root, now, week, c.manifest, vs, c.flags)

def check_pump_file(kind, path, league=None, week=None, now=None):
    """The loader's per-file contract (ffdata_load refuses to install a violating pump
    file and names the code). kind: rosters | matchup | transactions | kalshi | sleeper_off |
    sleeper_idp | espn -> list of Violation."""
    now = now or C.now(); out = []
    fields, rows = _csv(path)
    if rows is None: return out
    nm = os.path.basename(path)
    spec = {'rosters': SPEC['yahoo/{LG}_rosters.csv'], 'matchup': SPEC['yahoo/{LG}_matchup_wk{W}.csv'],
            'transactions': SPEC['yahoo/{LG}_transactions.csv'], 'kalshi': SPEC['kalshi.csv'],
            'sleeper_off': SPEC['sleeper_off_wk{W}.csv'], 'sleeper_idp': SPEC['sleeper_idp_wk{W}.csv'],
            'espn': (('event_id', 'away', 'home', 'kickoff'), (), ())}[kind]
    for m in columns_violations(nm, fields, rows, spec): out.append(Violation('C15', REFUSE, m))
    if any('missing required column' in v.msg for v in out): return out
    stamps = sorted({r.get('pulled_at') for r in rows if r.get('pulled_at')}) if 'pulled_at' in fields else []
    for s in stamps:
        try:
            t = T.parse_ts(s, 'pump')
            if t > now + FUTURE_GRACE: out.append(Violation('C2', REFUSE, f'{nm}: pulled_at {s!r} is in the future'))
        except T.TsError as e: out.append(Violation('C2', REFUSE, f'{nm}: {e}'))
    if kind == 'rosters':
        for m in raw_roster_shape(league, rows): out.append(Violation('C4', REFUSE, f'{nm}: {m}'))
        for r in rows:
            if (r.get('pos') or '').upper() == 'DEF' and (r.get('player') or '').strip() and team(r.get('nfl') or '') not in DST_FULL:
                out.append(Violation('C6', REFUSE, f"{nm}: DEF '{r.get('player')}' on {r.get('owner')} has nfl {r.get('nfl')!r}"))
    if kind == 'matchup':
        cfg = ALL[league]
        me = {r.get('owner') for r in rows if r.get('side') == 'me'}
        if me != {cfg.name}: out.append(Violation('C14', REFUSE, f"{nm}: 'me' side is {sorted(me)}, not {cfg.name!r}"))
        for side in ('me', 'opp'):
            rs = [r for r in rows if r.get('side') == side]
            if not rs: continue
            try: tot = float(rs[0]['total'])
            except (TypeError, ValueError): out.append(Violation('C14', REFUSE, f'{nm} {side}: total {rs[0].get("total")!r}')); continue
            s = sum(float(r['fan_pts']) for r in rs if r.get('slot') not in ('BN', 'IR') and _num(r.get('fan_pts')))
            if abs(tot - s) > 0.05: out.append(Violation('C14', REFUSE, f'{nm} {side}: total {tot:.2f} != starter rows {s:.2f}'))
    if kind == 'transactions':
        for i, r in enumerate(rows, 2):
            ref = T.try_ts(r.get('pulled_at'), 'pump') or now
            try: T.parse_ts(r.get('ts'), 'yahoo_page', now=ref)
            except T.TsError as e: out.append(Violation('C2', REFUSE, f'{nm} line {i}: {e}')); break
    if kind == 'kalshi' and not stamps:
        out.append(Violation('C2', REFUSE, f'{nm}: no pulled_at stamp'))
    if kind in ('sleeper_off',) and len(rows) < SLEEPER_MIN_ROWS:
        out.append(Violation('C1', REFUSE, f'{nm}: {len(rows)} rows (< {SLEEPER_MIN_ROWS})'))
    if kind == 'espn':
        for r in rows:
            if r.get('kickoff') and T.try_ts(r['kickoff'], 'espn') is None:
                out.append(Violation('C2', REFUSE, f"{nm}: kickoff {r['kickoff']!r} does not parse")); break
    return out
