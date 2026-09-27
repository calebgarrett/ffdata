"""ONE LEDGER.

Every call this system makes is written here with a status, and the next run
begins by reconciling the open ones against live state. This is what stops:
  - re-raising a move Caleb already made ("an add is not a start", 09-10)
  - telling him to do something already done ("swap in the 49ers", 09-16)
  - silently reversing a prior call (six reversals in one session, 09-15)
  - answering the same question differently twice (the reason this was rebuilt)

Statuses:
  proposed     surfaced to Caleb, not yet acted on
  executed     live state shows it done
  already_set  was already true when proposed (the engine should not have raised it)
  declined     Caleb said no -- do not re-raise without new evidence
  superseded   replaced by a later call, which is named
  expired      the window closed (game locked, waivers ran)
"""
import os, json, uuid
from . import clock as C

PATH = '/home/claude/bsb2/data/ledger.json'
OPEN = ('proposed',)

def _load():
    if os.path.exists(PATH):
        try: return json.load(open(PATH))
        except Exception: return []
    return []

def _save(L): json.dump(L, open(PATH, 'w'), indent=1)

def all_entries(): return _load()

def open_items(league=None, kind=None):
    return [e for e in _load() if e['status'] in OPEN
            and (league is None or e['league'] == league)
            and (kind is None or e['kind'] == kind)]

def prior(league, kind, subject):
    """Most recent entry of any status for this subject -- G9 reads this."""
    for e in reversed(_load()):
        if e['league'] == league and e['kind'] == kind and e['subject'] == subject: return e
    return None

def propose(league, kind, subject, call, *, detail='', evidence=(), verdict='PASS',
            week=None, resolves_at=None, provisional=False, state=None):
    """Record a call. Dedupes against an identical open call. If `state` is
    given and the call is ALREADY TRUE in it, the entry is filed as already_set
    and nothing is surfaced -- that is the whole point."""
    L = _load()
    for e in L:
        if (e['status'] in OPEN and e['league'] == league and e['kind'] == kind
                and e['subject'] == subject and e['call'] == call):
            return e
    status = 'proposed' if verdict != 'BLOCK' else 'blocked'   # a blocked call is never an open item
    if state is not None:
        if kind == 'start' and state.is_starting(subject): status = 'already_set'
        if kind == 'sit'   and not state.is_starting(subject) and state.slot_of(subject): status = 'already_set'
        if kind == 'add'   and state.owner_of(subject) == state.me: status = 'already_set'
        if kind == 'drop'  and state.owner_of(subject) != state.me and state.owner_of(subject) is not None:
            status = 'already_set'
        if kind == 'drop'  and state.owner_of(subject) is None: status = 'executed'
    # prior call on this subject, found INSIDE L so the status change persists
    p = None
    for x in reversed(L):
        if x['league'] == league and x['kind'] == kind and x['subject'] == subject: p = x; break
    reverses = None
    if p and p['call'] != call and p['status'] not in ('superseded', 'expired'):
        reverses = p['id']
        p['status'] = 'superseded'
    e = dict(id=uuid.uuid4().hex[:8], ts=C.iso(), league=league, kind=kind, subject=subject,
             call=call, detail=detail, evidence=list(evidence), verdict=verdict,
             week=week or C.nfl_week(), status=status, provisional=bool(provisional),
             resolves_at=resolves_at, reverses=reverses)
    if reverses: p['superseded_by'] = e['id']
    L.append(e); _save(L)
    return e

def set_status(eid, status, note=''):
    L = _load()
    for e in L:
        if e['id'] == eid:
            e['status'] = status; e['status_ts'] = C.iso()
            if note: e['status_note'] = note
    _save(L)

def decline(league, kind, subject, note='Caleb declined'):
    for e in open_items(league, kind):
        if e['subject'] == subject: set_status(e['id'], 'declined', note)

def reconcile(state):
    """Mark open items executed/expired against live state. Returns the changes."""
    L = _load(); out = []
    for e in L:
        if e['status'] not in OPEN or e['league'] != state.league: continue
        new = None
        if e['kind'] == 'add'   and state.owner_of(e['subject']) == state.me: new = 'executed'
        if e['kind'] == 'drop'  and state.owner_of(e['subject']) != state.me: new = 'executed'
        if e['kind'] == 'start' and state.is_starting(e['subject']): new = 'executed'
        if e['kind'] == 'sit'   and state.slot_of(e['subject']) in ('BN', 'IR'): new = 'executed'
        if e['kind'] in ('add', 'drop') and e.get('week') and e['week'] < C.nfl_week(): new = 'expired'
        if new:
            e['status'] = new; e['status_ts'] = C.iso(); out.append((e, new))
    _save(L)
    return out

def migrate_decisions_json(path='/home/claude/bsb2/data/decisions.json'):
    """Bring the old start/sit log across once, deduplicated."""
    if not os.path.exists(path): return 0
    old = json.load(open(path)); L = _load(); seen = {(e['kind'], e['subject'], e['call']) for e in L}
    n = 0
    for d in old:
        k = (d['kind'], d['subject'], d['call'])
        if k in seen: continue
        seen.add(k); n += 1
        L.append(dict(id=uuid.uuid4().hex[:8], ts=d['date'], league='BSB', kind=d['kind'],
                      subject=d['subject'], call=d['call'], detail=d.get('note', ''),
                      evidence=[], verdict=d.get('verdict', ''), week=2, status='superseded',
                      provisional=False, resolves_at=None, reverses=None, migrated=True))
    _save(L); return n
