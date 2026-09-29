"""ONE STATE MODEL.

What is actually on each roster, in which slot, with what designation, as of a
KNOWN time. Every recommendation in this system is a diff against this object,
so "swap in the 49ers" cannot be said about a defense that is already in the slot
(2026-09-16), and "an add is not a start" (2026-09-10) is checked, not assumed.

The state knows its own age and refuses purposes it is too old for. That is the
whole defence against the stale-Yahoo-page failures of 09-06 and 09-08 and the
day-old pool that missed the Chargers DEF on 09-15.

Snapshots live in data/state/<LEAGUE>/<iso>.json. The newest is loaded. The
Yahoo pull that writes a snapshot is a separate concern (sources/yahoo.py); this
module only reads and reasons.
"""
import os, json, csv, glob
from collections import defaultdict
from . import clock as C
from .names import key, team
from .leagues import ALL

ROOT = '/home/claude/bsb2/data'

# How old a snapshot may be for each purpose before the answer is not trustworthy.
# Irreversible things get the short leash.
STALE_H = {'status': 48, 'lineup': 18, 'add_drop': 30, 'trade': 72, 'season': 24*7}

UNUSABLE = {'IR','IR-R','O','NA','PUP','PUP-R','SUSP','CEL'}
RISKY    = {'Q','D'}


class State:
    def __init__(self, league, rows, pulled, source='snapshot', others_pulled=None):
        self.league = league
        self.cfg = ALL[league]
        self.pulled = pulled
        # when EVERY roster in the league was last read (my own and my opponent's
        # are refreshed off the matchup page far more often than the other ten)
        self.others_pulled = others_pulled or pulled
        self.records = {}
        self.source = source
        self.reconciled = []
        self.rows = rows
        for r in rows:
            r['key'] = key(r['player'])
            r['tm'] = team(r.get('nfl') or r.get('tm') or '')
            r['elig'] = _elig(r.get('pos', ''), league)
        self.by_owner = defaultdict(list)
        for r in rows: self.by_owner[r['owner']].append(r)
        # Yahoo repeats slot names (RB, RB, WR, WR, WR). The league config names
        # them RB1/RB2/WR1/WR2/WR3. Number them per owner, in roster order, so a
        # lineup dict never silently drops a starter (2026-09-16: BSB 'current'
        # lineup came back with 6 of 10 starters and every diff was wrong).
        for owner, rs in self.by_owner.items():
            seen = defaultdict(int)
            numbered = [x for x in self.cfg.slots if x[-1].isdigit()]
            for r in rs:
                base = r['slot']
                if base in ('BN', 'IR'): continue
                cands = [x for x in numbered if x.rstrip('123') == base]
                if cands:
                    seen[base] += 1
                    r['slot'] = f'{base}{seen[base]}' if seen[base] <= len(cands) else base
        self.me = self.cfg.name
        self.mine = self.by_owner.get(self.me, [])
        self.roster_keys = {r['key'] for r in rows}
        self._slot = {r['key']: r['slot'] for r in self.mine}
        self._row = {r['key']: r for r in self.mine}

    # ---- age
    @property
    def age_h(self):
        return C.age_hours(self.pulled)

    def stale_for(self, purpose):
        a = self.age_h
        lim = STALE_H.get(purpose, 24)
        if a is None: return True, 'pull time unknown'
        if a > lim: return True, f'state is {a:.0f}h old; {purpose} needs <{lim}h'
        return False, f'state {a:.0f}h old, within the {lim}h limit for {purpose}'

    # ---- queries
    def slot_of(self, k):        return self._slot.get(key(k) if ' ' in k or ':' not in k else k)
    def row_of(self, k):         return self._row.get(key(k))
    def owner_of(self, k):
        kk = key(k)
        for r in self.rows:
            if r['key'] == kk: return r['owner']
        return None
    def starters(self):          return [r for r in self.mine if r['slot'] not in ('BN','IR')]
    def bench(self):             return [r for r in self.mine if r['slot'] == 'BN']
    def ir(self):                return [r for r in self.mine if r['slot'] == 'IR']
    def current_lineup(self):    return {r['slot']: r for r in self.starters()}
    def is_starting(self, k):    return self.slot_of(k) not in (None, 'BN', 'IR')
    def count(self):             return len(self.mine)

    def describe(self):
        st, why = self.stale_for('status')
        return (f'{self.league} · {self.me} · {self.count()} rostered '
                f'({len(self.starters())} starting, {len(self.bench())} bench, {len(self.ir())} IR) · '
                f'pulled {self.pulled} · {why}')


def _elig(pos_string, league):
    """Yahoo's own eligibility string ('LB,DE', 'DB,CB') is authoritative for a
    rostered player. Mapped onto the slot families each league uses."""
    out = set()
    for p in str(pos_string or '').replace('/', ',').split(','):
        p = p.strip().upper()
        if not p: continue
        if league == 'HH':
            out |= {'DE':{'DL'},'DT':{'DL'},'NT':{'DL'},'DL':{'DL'},
                    'LB':{'LB'},'OLB':{'LB'},'ILB':{'LB'},'MLB':{'LB'},
                    'CB':{'CB','DB'},'S':{'S','DB'},'FS':{'S','DB'},'SS':{'S','DB'},
                    'DB':{'DB'}}.get(p, {p})
        else:
            out.add(p)
    return out


# ---------------------------------------------------------------- loading
def _snap_dir(league):
    d = os.path.join(ROOT, 'state', league); os.makedirs(d, exist_ok=True); return d

def _log_path(league):
    return os.path.join(ROOT, 'bsb_transactions.csv' if league == 'BSB' else 'hh_transactions.csv')

def reconcile(league, rows, log_rows=None):
    """Apply the league's transaction log to the roster rows, oldest first.

    Yahoo's logged-out team pages stop reflecting adds and drops once a player's
    game has locked for the week: on Tue 09-29 at 2:48 am the pages still showed
    Jalen Coker on The STRIB Club (dropped Mon 11:31 am) and no Matthew Golden on
    Maker's Mark (added Mon 9:44 pm), so the engine proposed Golden as a free
    agent 11 hours after he was gone. The transactions page is not frozen, so
    it is the truth for the gap. Rules, in log order:
      Add  by T of P: P on no roster -> P joins T's bench. P already on a roster
                      (T's or another's) -> the page is trusted (a trade is not
                      in the add/drop log).
      Drop by T of P: P on T -> P leaves. Otherwise nothing.
    Only the log since the start of the PREVIOUS NFL week is replayed: the pages
    can lag at most from a week's first kickoff to its rollover, and the merged
    log is complete over that span but not before it (BSB 09-02..09-16 adds whose
    drops predate the log would otherwise resurrect four players).
    -> (rows, changes) where changes is the NET list of 'owner +Player' / 'owner -Player'."""
    if log_rows is None:
        p = _log_path(league)
        log_rows = [r for r in csv.DictReader(open(p))] if os.path.exists(p) else []
    since = (C.week_start(max(1, C.nfl_week() - 1))).strftime('%Y-%m-%d %H:%M')
    log = sorted((r for r in log_rows if (r.get('datetime') or '') >= since and r.get('action') in ('Add', 'Drop')), key=lambda r: r['datetime'])
    orig = [dict(r) for r in rows]
    rows = [dict(r) for r in rows]
    changes = []
    for t in log:
        k = key(t['player']); owner = t['team']
        holders = [r for r in rows if key(r['player']) == k]
        if t['action'] == 'Add':
            if holders: continue
            rows.append(dict(owner=owner, manager=owner, slot='BN', player=t['player'], pos=t.get('pos') or '', nfl=t.get('nfl') or '', designation='none'))
            changes.append(f"{owner} +{t['player']}")
        else:
            mine = [r for r in holders if r['owner'] == owner]
            if not mine: continue
            rows = [r for r in rows if not (key(r['player']) == k and r['owner'] == owner)]
            changes.append(f"{owner} -{t['player']}")
    # report the NET difference from the page, not the replay
    before = {(r['owner'], key(r['player'])): r['player'] for r in orig}
    after = {(r['owner'], key(r['player'])): r['player'] for r in rows}
    net = [f'{o} +{after[(o, k)]}' for (o, k) in after if (o, k) not in before] + \
          [f'{o} -{before[(o, k)]}' for (o, k) in before if (o, k) not in after]
    return rows, net

def latest(league, reconciled=True):
    """Newest snapshot for the league, or None. The transaction log is applied on
    top of it unless `reconciled=False` (see reconcile)."""
    fs = sorted(glob.glob(os.path.join(_snap_dir(league), '*.json')))
    if not fs: return None
    j = json.load(open(fs[-1]))
    rows, changes = reconcile(league, j['rows']) if reconciled else (j['rows'], [])
    st = State(league, rows, j['pulled'], source=os.path.basename(fs[-1]), others_pulled=j.get('others_pulled'))
    st.records = j.get('records') or {}
    st.reconciled = changes
    return st

def recently_dropped(league, days=7, snaps=None):
    """Players Caleb had on HIS roster in a snapshot within `days` who are not on
    it now -> {key: date-of-last-snapshot-that-had-him}. A move he executed is
    a decision; the scanner must not re-propose the same player on the same
    usage pull (Black 09-21: dropped Sunday, Tier A on week-1 usage on Monday)."""
    fs = snaps if snaps is not None else sorted(glob.glob(os.path.join(_snap_dir(league), '*.json')))
    if len(fs) < 2: return {}
    cfg = ALL[league]; cutoff = C.now() - C.dt.timedelta(days=days)
    now_mine = {key(r['player']) for r in json.load(open(fs[-1]))['rows'] if r['owner'] == cfg.name}
    out = {}
    for f in fs[:-1]:
        stamp = os.path.basename(f)[:-5]
        try: t = C.dt.datetime.strptime(stamp, '%Y-%m-%dT%H%M').replace(tzinfo=C.now().tzinfo)
        except Exception: continue
        if t < cutoff: continue
        for r in json.load(open(f))['rows']:
            if r['owner'] == cfg.name and key(r['player']) not in now_mine: out[key(r['player'])] = stamp[:10]
    for k, d in _my_log_moves(league, 'Drop', cutoff, snaps is None).items(): out.setdefault(k, d)
    return out

def _my_log_moves(league, action, cutoff, use_log=True):
    """Caleb's own Adds/Drops from the transaction log since `cutoff` -> {key: date}.
    The team pages lag the log once games lock (see reconcile); the log does not."""
    if not use_log: return {}
    p = _log_path(league)
    if not os.path.exists(p): return {}
    out = {}
    for r in csv.DictReader(open(p)):
        if r.get('team') != ALL[league].name or r.get('action') != action: continue
        try: t = C.dt.datetime.strptime(r['datetime'], '%Y-%m-%d %H:%M').replace(tzinfo=C.ET)
        except Exception: continue
        if t >= cutoff: out[key(r['player'])] = r['datetime'][:10]
    return out

def recently_added(league, days=7, snaps=None):
    """Players on Caleb's roster now who were NOT on it in some snapshot within
    `days` -> {key: date-of-last-snapshot-without-him}. A player he just added is
    a decision he made; the scanner must not propose him as the drop the next
    morning (Jameson Williams 09-26, added 09-25 for Fields)."""
    fs = snaps if snaps is not None else sorted(glob.glob(os.path.join(_snap_dir(league), '*.json')))
    if len(fs) < 2: return {}
    cfg = ALL[league]; cutoff = C.now() - C.dt.timedelta(days=days)
    now_mine = {key(r['player']) for r in json.load(open(fs[-1]))['rows'] if r['owner'] == cfg.name}
    out = {}
    for f in fs[:-1]:
        stamp = os.path.basename(f)[:-5]
        try: t = C.dt.datetime.strptime(stamp, '%Y-%m-%dT%H%M').replace(tzinfo=C.now().tzinfo)
        except Exception: continue
        if t < cutoff: continue
        then = {key(r['player']) for r in json.load(open(f))['rows'] if r['owner'] == cfg.name}
        for k in now_mine - then: out[k] = stamp[:10]
    for k, d in _my_log_moves(league, 'Add', cutoff, snaps is None).items(): out.setdefault(k, d)
    return out

def recently_dropped_anywhere(days=7):
    """recently_dropped across BOTH leagues -> {key: (league, date)}. Caleb's read
    on a player does not change with the league (Fields 09-26: dropped in HH on
    09-25, proposed in BSB on 09-26)."""
    out = {}
    for lg in ALL:
        for k, d in recently_dropped(lg, days).items(): out.setdefault(k, (lg, d))
    return out

def save(league, rows, pulled, note='', others_pulled=None, records=None):
    """Write a snapshot. `rows` need owner, slot, player, pos, nfl, designation.
    `others_pulled`: when the OTHER rosters were read; None means this pull read the
    whole league (Fields 09-23: an add called 'unrostered' against a 3-day-old
    league read, after a waiver run — he had been claimed)."""
    p = os.path.join(_snap_dir(league), C.now().strftime('%Y-%m-%dT%H%M') + '.json')
    RAW = ('owner','manager','slot','player','pos','nfl','designation')
    clean = [{k: r.get(k, '') for k in RAW} for r in rows]
    json.dump({'league': league, 'pulled': pulled, 'others_pulled': others_pulled or pulled, 'note': note, 'records': records or {}, 'rows': clean}, open(p, 'w'), indent=0)
    return p

def from_legacy_csv(league, pulled):
    """One-time bridge from the rosters.csv / hh_rosters.csv the old pipeline wrote."""
    if league == 'BSB':
        rows = []
        for r in csv.DictReader(open(os.path.join(ROOT, 'rosters.csv'))):
            rows.append(dict(owner=r['team_name'], manager=r['manager'], slot=r['slot'],
                             player=r['player'], pos=r['pos'], nfl=r['nfl'],
                             designation=r['designation']))
    else:
        rows = []
        for r in csv.DictReader(open(os.path.join(ROOT, 'hh_rosters.csv'))):
            rows.append(dict(owner=r['team_name'], manager=r['team_name'], slot=r['slot'],
                             player=r['player'], pos=r['pos'], nfl=r['nfl'],
                             designation=r['designation']))
    return State(league, rows, pulled, source='legacy-csv')

def load(league):
    """Newest snapshot, falling back to the legacy CSV bridged with its known pull time."""
    s = latest(league)
    if s: return s
    # the CSVs were pulled Tue 2026-09-15 in the afternoon ET (HH after its 11:11am
    # transaction; BSB after the Chargers release at 2:16pm). Recorded conservatively.
    return from_legacy_csv(league, '2026-09-15T15:00-04:00')


def diff(old, new):
    """Roster changes between two snapshots of the same league, for the ledger."""
    o = {(r['owner'], r['key']): r for r in old.rows}
    n = {(r['owner'], r['key']): r for r in new.rows}
    added   = [n[k] for k in n if k not in o]
    dropped = [o[k] for k in o if k not in n]
    moved   = [(o[k], n[k]) for k in o if k in n and o[k]['slot'] != n[k]['slot']]
    return dict(added=added, dropped=dropped, moved=moved)
