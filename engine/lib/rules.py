"""ONE RULE BOOK — the designation vocabulary, the lock, and the BSB waiver run.

Before this module the UNUSABLE set was typed out in seven files (state, scoring,
sanity, card, playoff, rivals, plus inline copies in wire and breakout), RISKY in
two, and the BSB waiver run had two meanings: the gate read the run's ACTUAL time
off the transactions log (09-30: it ran at 4:12 am), while the breakout scanner,
the waiver list and the card kept the assumed Wednesday 06:00. Every one of those
now imports from here; test/test_contract.py greps that no copy comes back.

Designations (Yahoo's tag on a player, `designation` on a state row):
  CLEAR      no tag ('none' in a snapshot, '' on the pump's pages)
  RISKY      Q, D — startable, needs a named contingency
  UNUSABLE   IR, IR-R, O, NA, PUP, PUP-R, SUSP, CEL — cannot be started this week
  VOCAB      CLEAR | RISKY | UNUSABLE — the whole explicit vocabulary. A tag outside
             it (Yahoo invents one: 'NFI-R', 'PUP-P', 'COV') is NOT silently clear:
             the contract raises C7 WARN naming it, and a person decides where it goes.
Derived families (were local copies; same members as before):
  TAGGED     UNUSABLE | RISKY            (wire: any tag at all)
  LONG_TERM  UNUSABLE - {'O'}            (wire: a designation that outlives one week)
  OUT_TAGS   UNUSABLE | {'D'}            (nextup: a starter whose backup inherits the role)
"""
from . import paths as _paths
import csv, json, os, re, tempfile, datetime as dt
from . import clock as C, ts as T

ROOT = _paths.root()

CLEAR = frozenset({'none', ''})
RISKY = frozenset({'Q', 'D'})
UNUSABLE = frozenset({'IR', 'IR-R', 'O', 'NA', 'PUP', 'PUP-R', 'SUSP', 'CEL'})
VOCAB = CLEAR | RISKY | UNUSABLE
TAGGED = UNUSABLE | RISKY
LONG_TERM = UNUSABLE - {'O'}
OUT_TAGS = UNUSABLE | {'D'}

def unknown_tags(tags):
    """Tags outside the explicit vocabulary -> sorted list (C7)."""
    return sorted({(t if t is not None else '') for t in tags} - VOCAB)

# ------------------------------------------------------------------ the lock
_STARTED = re.compile(r'^(Final|Q[1-4]\b|End\s+Q|Half\b|OT\b)')

def locked(row, now=None):
    """Is this player's slot frozen for the rest of the week?

    True when any of: his game is final; it is in progress (live points on file);
    the lineup phase says locked; his kickoff has passed; Yahoo's game text shows the
    game started or finished; or the row carries Yahoo's week-lock (a player started
    this week stays locked until the week rolls — Burns 09-28, 'I can't move him to IR
    yet because I started him this week')."""
    if row is None: return False
    if row.get('final') or row.get('live') or row.get('phase') in ('locked', 'final', 'live'): return True
    if row.get('week_locked'): return True
    k = row.get('kick')
    if k is not None:
        n = now or C.now()
        if k <= n: return True
    g = row.get('game')
    if g and _STARTED.match(str(g).strip()): return True
    return False

# ------------------------------------------------------------------ BSB waivers
def _bsb_log(path=None):
    return path or os.path.join(ROOT, 'data', 'bsb_transactions.csv')

def waiver_run_at(w=None, log_path=None):
    """When week w's BSB waiver run happened — THE one notion of it.

    The actual time is the latest 'Waiver' add on the transactions log dated that
    Wednesday (09-30: 4:12 am). Until one is logged, the assumed Wednesday 06:00 ET
    (clock.bsb_waiver_deadline). -> aware ET datetime."""
    wd = C.bsb_waiver_deadline(w)
    p = _bsb_log(log_path)
    if not os.path.exists(p): return wd
    day = wd.date(); ts = []
    try:
        rows = list(csv.DictReader(open(p)))
    except Exception:
        return wd
    for row in rows:
        if row.get('action') != 'Add' or (row.get('note') or '').strip().lower() != 'waiver': continue
        t = T.try_ts(row.get('datetime'), 'yahoo_log')
        if t is not None and t.date() == day: ts.append(t)
    return max(ts) if ts else wd

def last_waiver_run(now=None, log_path=None):
    """The most recent BSB waiver run at or before `now` (this week's if it has
    happened, else last week's)."""
    n = now or C.now()
    w = C.nfl_week(n)
    r = waiver_run_at(w, log_path)
    if r > n: r = waiver_run_at(max(1, w - 1), log_path) if w > 1 else r - dt.timedelta(days=7)
    return r

def bsb_claims_open(now=None, log_path=None):
    """True from the week's rollover (Tue 07:00 ET) until this week's waiver run:
    last week's games are all played and the run has not processed, so every
    unrostered player who played is a waiver CLAIM, not a free agent (the Jets DEF,
    Tue 09-29)."""
    n = now or C.now()
    return n < waiver_run_at(C.nfl_week(n), log_path)

# ------------------------------------------------------------------ registry + ledger IO
ADD_YES_DAYS = 14
_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})')

def atomic_write_json(path, obj, indent=1):
    """Write JSON via a temp file in the same directory and an atomic rename, so a
    crash mid-write never leaves a half file that the next run swallows into {}."""
    d = os.path.dirname(os.path.abspath(path)) or '.'
    fd, tmp = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w') as fh:
            json.dump(obj, fh, indent=indent)
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def roles_path(root=None):
    return os.path.join(root or ROOT, 'data', 'roles.json')

def add_yes_as_of(entry, registry=None):
    """When an add_yes entry was verified: its own `as_of`, else the newest date in its
    `src` (the evidence date), else the registry's `_checked`. -> (date|None, how)."""
    if entry.get('as_of'):
        t = T.try_ts(str(entry['as_of'])[:10], 'date')
        if t: return t.date(), 'as_of'
    ds = _DATE.findall(str(entry.get('src') or ''))
    if ds: return max(T.parse_ts(d, 'date').date() for d in ds), 'src'
    if registry and registry.get('_checked'):
        t = T.try_ts(str(registry['_checked'])[:10], 'date')
        if t: return t.date(), '_checked'
    return None, 'unknown'

def demote_add_yes(R, today=None, days=ADD_YES_DAYS):
    """Move add_yes entries verified more than `days` ago into R['_demoted_add_yes'].
    A role verified on week-1 usage is not still verified in week 4 (RUNBOOK:
    re-verify after seven days); after fourteen it stops ranking a player first on
    the wire and stops counting as usage evidence in G11. Mutates and returns R."""
    today = today or C.today()
    ay = R.get('add_yes') or {}
    keep, demoted = {}, dict(R.get('_demoted_add_yes') or {})
    for k, v in ay.items():
        if k.startswith('_') or not isinstance(v, dict): keep[k] = v; continue
        d, how = add_yes_as_of(v, R)
        if d is None or (today - d).days > days:
            demoted[k] = dict(v, as_of=d.isoformat() if d else 'unknown', as_of_from=how,
                              demoted=f'{(today - d).days}d old' if d else 'no date on record')
        else:
            keep[k] = dict(v, as_of=d.isoformat(), as_of_from=how)
    R['add_yes'] = keep
    R['_demoted_add_yes'] = demoted
    return R

def load_roles(path=None, strict=False, demote=True, today=None):
    """The role registry. strict=True raises on a parse error (the contract, C16);
    strict=False returns {} so a module import never crashes — the contract has
    already refused the run before any decision reads the empty registry."""
    p = path or roles_path()
    if not os.path.exists(p):
        if strict: raise ValueError(f'{p}: missing')
        return {}
    try:
        R = json.load(open(p))
        if not isinstance(R, dict): raise ValueError('top level is not an object')
    except Exception as e:
        if strict: raise ValueError(f'{p} does not parse: {e}')
        return {}
    return demote_add_yes(R, today=today) if demote else R

def save_roles(R, path=None, today=None):
    """Write the registry atomically; every add_yes entry carries an as_of (stamped
    today when a new entry arrives without one). Demoted entries are written back
    under _demoted_add_yes so nothing verified is lost."""
    today = today or C.today()
    out = dict(R)
    out['add_yes'] = {k: (dict(v, as_of=v.get('as_of') or today.isoformat()) if isinstance(v, dict) and not k.startswith('_') else v)
                      for k, v in (R.get('add_yes') or {}).items()}
    for v in out['add_yes'].values():
        if isinstance(v, dict): v.pop('as_of_from', None)
    atomic_write_json(path or roles_path(), out)
