"""OUTCOME LEDGER — every decision point, what was chosen, and what it was worth.

lib/ledger.py records calls so a run never re-raises or silently reverses one.
Nothing scored them. This module does, in five stores under data/outcomes/
(JSONL, one JSON object per line):

  decisions.jsonl     one row per DECISION POINT (not per run), keyed by
                      (league, nfl_week, kind, subject, alternative). A re-run
                      updates the open row in place; once its deadline passes the
                      row is frozen and never rewritten. Kinds:
                        lineup_slot   the engine's occupant vs the current occupant of one slot
                        add_drop      a weekly upgrade or a bench swap (add subject, drop alternative)
                        claim         a BSB breakout add that is a Wednesday claim (recommended bid)
                        stream        a DEF/K stream or bye cover for next week
                        ir            an IR move
                        nextup        the next man up for an OUT starter
                        breakout_tier every Tier A/B breakout row (verb ADD / WAIT / NONE, tier kept)
                        plan_move     the shadow planner's moves (run['plan'] / run['plans'])
                      Deadlines: lineup_slot and nextup at kickoff; claim at the Wednesday
                      run; everything else at the Tuesday rollover.
  resolutions.jsonl   what was chosen: followed | overridden | ignored | moot, and how.
                      Lineups are read from the last snapshot before that player's kickoff
                      IN THAT WEEK; adds and drops from the transactions log and snapshot
                      diffs inside [created, deadline].
  outcomes.jsonl      computed only once the week's actuals are complete (every game
                      final): horizons 1, 3 and rest-of-season. lineup: actual(recommended)
                      - actual(chosen). add/drop: V(roster with the add) - V(roster with the
                      drop), V = the hindsight-optimal lineup on actual points
                      (lib/lineup.optimal_points), for executed, declined AND ignored calls —
                      a missed add has a cost.
  claims.jsonl        BSB: recommended bid, Caleb's bid (`ff.py bid <player> <amount>` — a
                      losing bid never reaches the pump), won/lost, winner, winning bid.
  league_moves.jsonl  every rival add on the logs, when we first flagged that player (and at
                      what tier), the lead time, and what he scored for the adder afterwards.
  pwin.jsonl          P(beat opponent) / P(beat median) of the current lineup per league-week,
                      frozen at the first starter's kickoff (the reliability table needs it).

Rows are never deleted; a row is only replaced by a newer version of the same key,
and a frozen row (deadline passed, horizon final) is never replaced. Writes are
atomic (tmp + rename). Everything here is idempotent: `ff.py outcomes` can run any
number of times and converges.

Actual points: Yahoo's matchup-page number where the player is on it (exact league
scoring; my roster and my opponent's), else his Sleeper stat line scored by
lib/score.actual. IDP has no stat feed: an IDP outcome that needs a player Yahoo did
not print is UNAVAILABLE, never zero. `fidelity()` prints how far the Sleeper-scored
stand-in lands from Yahoo's number on the players both cover.
"""
from . import paths as _paths
import os, json, csv, glob, hashlib, subprocess, datetime as dt, re, tempfile
from collections import defaultdict
from . import clock as C, score as SC, ts as T
from .names import key, team
from .leagues import ALL

ROOT = _paths.root()
FFDATA = os.environ.get('FFDATA_ROOT', '/home/claude/ffdata_repo')
KINDS = ('lineup_slot', 'add_drop', 'claim', 'stream', 'ir', 'nextup', 'breakout_tier', 'plan_move')
STATUSES = ('followed', 'overridden', 'ignored', 'moot')
HORIZONS = ('1', '3', 'ros')
LAST_WEEK = 17
ADD_KINDS = ('add_drop', 'claim', 'stream', 'nextup', 'breakout_tier', 'plan_move')
OFF_POS = ('QB', 'RB', 'WR', 'TE')
IDP_FAM = ('DL', 'LB', 'DB', 'DE', 'DT', 'CB', 'S', 'NT', 'OLB', 'ILB', 'MLB', 'FS', 'SS')

# ------------------------------------------------------------------ store IO
def _dir(root=None):
    return os.path.join(root or ROOT, 'data', 'outcomes')

def _path(name, root=None):
    return os.path.join(_dir(root), name + '.jsonl')

def read(name, root=None):
    """All rows of one store, in file order. A line that does not parse is an error,
    not an empty store (the ledger lesson: swallowing it would let the next write
    overwrite every row on record)."""
    p = _path(name, root)
    if not os.path.exists(p): return []
    out = []
    for i, line in enumerate(open(p), 1):
        line = line.strip()
        if not line: continue
        try: out.append(json.loads(line))
        except ValueError as e: raise ValueError(f'{p}:{i} does not parse ({e}) — refusing to treat the store as empty')
    return out

def _write(name, rows, root=None):
    d = _dir(root); os.makedirs(d, exist_ok=True)
    p = _path(name, root)
    fd, tmp = tempfile.mkstemp(prefix='.' + name + '.', suffix='.tmp', dir=d)
    try:
        with os.fdopen(fd, 'w') as fh:
            for r in rows: fh.write(json.dumps(r, sort_keys=True, default=str) + '\n')
            fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, p)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise

_VOLATILE = ('updated', 'seen', 'runs', 'computed', 'resolved_at')

def _sig(r):
    return json.dumps({k: v for k, v in r.items() if k not in _VOLATILE}, sort_keys=True, default=str)

def upsert(name, rows, key_field='id', root=None, merge=None):
    """Insert or replace rows by key. A stored row with frozen=True is never replaced.
    `merge(old, new) -> row` combines an existing row with its new version (created
    carried forward, history appended). -> dict(new, updated, unchanged, frozen)."""
    cur = read(name, root)
    idx = {r[key_field]: i for i, r in enumerate(cur)}
    n = dict(new=0, updated=0, unchanged=0, frozen=0)
    changed = False
    for r in rows:
        k = r[key_field]
        if k in idx:
            old = cur[idx[k]]
            if old.get('frozen'): n['frozen'] += 1; continue
            nr = merge(old, r) if merge else r
            if _sig(nr) == _sig(old): n['unchanged'] += 1; continue
            cur[idx[k]] = nr; n['updated'] += 1; changed = True
        else:
            idx[k] = len(cur); cur.append(r); n['new'] += 1; changed = True
    if changed: _write(name, cur, root)
    return n

def latest(name, key_field='id', root=None):
    out = {}
    for r in read(name, root): out[r[key_field]] = r
    return out

def decision_id(league, week, kind, subject, alternative=''):
    s = f'{league}|{int(week)}|{kind}|{subject or ""}|{alternative or ""}'
    return hashlib.sha1(s.encode()).hexdigest()[:12]

# ------------------------------------------------------------------ provenance
_SHA = {}

def engine_sha(root=None):
    r = root or ROOT
    if r in _SHA: return _SHA[r]
    v = None
    try:
        p = subprocess.run(['git', '-C', r, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=5)
        if p.returncode == 0 and p.stdout.strip(): v = p.stdout.strip()
    except Exception: pass
    if v is None:
        # the pump runs the engine from engine.tar.gz (no .git): hash the code itself
        h = hashlib.sha1()
        for f in sorted(glob.glob(os.path.join(r, '*.py')) + glob.glob(os.path.join(r, 'lib', '*.py'))):
            try: h.update(open(f, 'rb').read())
            except OSError: pass
        v = 'tree:' + h.hexdigest()[:10]
    _SHA[r] = v
    return v

def kalshi_stamp(now=None, root=None):
    """Newest archived Kalshi pull at or before now (its file stamp, UTC)."""
    now = now or C.now()
    best = None
    for f in glob.glob(os.path.join(root or ROOT, 'data', 'kalshi_archive', 'kalshi_*.csv')):
        s = os.path.basename(f)[7:-4]
        t = T.try_ts(s, 'pump')
        if t is not None and t <= now and (best is None or t > best[0]): best = (t, s)
    return best[1] if best else None

def provenance(run, st, root=None, now=None):
    sl = None
    try:
        man = getattr(run.get('contract'), 'manifest', None) or {}
        sl = (man.get('sleeper_off') or {}).get('as_of')
    except Exception: pass
    return dict(engine=engine_sha(root), snapshot=getattr(st, 'source', None), kalshi=kalshi_stamp(now, root),
                sleeper_as_of=str(sl) if sl else None)

# ------------------------------------------------------------------ helpers
def _iso(t): return C.iso(t) if t is not None else None

def _ts(s):
    if not s: return None
    if isinstance(s, dt.datetime): return s
    return T.try_ts(s, 'legacy')

def _num(v, d=2):
    try: return None if v is None else round(float(v), d)
    except (TypeError, ValueError): return None

def tue_rollover(week):
    """Week `week`'s decisions close when the next week rolls (Tue 07:00 ET)."""
    return C.week_start(week + 1)

def _proj(P, league, k, pos, tm, cache):
    """Every source's number for one player under the league's scoring (as calib.log)."""
    ck = (league, k)
    if ck in cache: return cache[ck]
    out = dict(engine=None, sleeper=None, yahoo=None, kalshi_fields='')
    if P is None or not k or str(k).startswith('__'):
        cache[ck] = out; return out
    try:
        L = P.line(k, pos, tm)
        Ls = P.line(k, pos, tm, market=False)
        out['engine'] = _num(SC.points(L, league)) if not L.get('unknown') else None
        out['sleeper'] = _num(SC.points(Ls, league)) if not Ls.get('unknown') and 'sleeper' in Ls.get('sources', []) else None
        out['yahoo'] = _num((getattr(P, 'yahoo', {}).get(k) or {}).get(league))
        out['kalshi_fields'] = ','.join(f for f in ('rec', 'rec_yd', 'rush_yd', 'pass_yd', 'pass_td', 'td') if f in (L.get('prov') or {}))
    except Exception:
        pass
    cache[ck] = out
    return out

def _opt(role, k, name, pos, tm, proj, pts=None, p_win=None, **kw):
    d = dict(role=role, key=k, name=name, pos=pos, tm=tm, proj=proj, pts=_num(pts))
    if p_win is not None: d['p_win'] = p_win
    d.update(kw)
    return d

def _merge_decision(old, new):
    nr = dict(new)
    nr['created'] = old.get('created') or new.get('created')
    nr['runs'] = int(old.get('runs') or 1) + 1
    h = list(old.get('history') or [])
    if (old.get('recommended'), old.get('gate'), old.get('provisional'), old.get('surfaced_on_decide')) != \
       (new.get('recommended'), new.get('gate'), new.get('provisional'), new.get('surfaced_on_decide')):
        h.append(dict(at=old.get('updated'), recommended=old.get('recommended'), margin=old.get('margin'),
                      gate=old.get('gate'), provisional=old.get('provisional'), surfaced=old.get('surfaced_on_decide')))
    nr['history'] = h[-12:]
    # a call surfaced once stays 'surfaced' for the record
    nr['ever_surfaced'] = bool(old.get('ever_surfaced') or new.get('surfaced_on_decide'))
    # the alternative a lineup call proposed to replace: the newest proposed change wins;
    # once Caleb makes the move the next run sees no change (rec == current), so the
    # earlier proposal's alternative is kept — following a call is not 'agreeing'
    if new.get('kind') == 'lineup_slot':
        nf, of = new.get('first_current'), old.get('first_current')
        if nf == new.get('recommended') and of is not None and of != old.get('recommended') and old.get('recommended') == new.get('recommended'):
            nr['first_current'] = of
            nr['margin'] = old.get('margin')          # the predicted gain is the proposal's, not the 0 after it was made
    else:
        nr['first_current'] = old.get('first_current', new.get('first_current'))
    return nr

def _decision(league, week, kind, subject, alternative, *, now, deadline, deadline_kind, options, recommended,
              margin, margin_unit, gate, provisional, surfaced, prov, subject_name=None, alternative_name=None, extra=None):
    did = decision_id(league, week, kind, subject, alternative)
    return dict(id=did, league=league, nfl_week=int(week), kind=kind, subject=subject or '', subject_name=subject_name,
                alternative=alternative or '', alternative_name=alternative_name,
                created=_iso(now), updated=_iso(now), deadline=_iso(deadline), deadline_kind=deadline_kind,
                options=options, recommended=recommended, margin=_num(margin, 3), margin_unit=margin_unit,
                gate=gate, provisional=bool(provisional), surfaced_on_decide=bool(surfaced), ever_surfaced=bool(surfaced),
                provenance=prov, extra=extra or {}, runs=1, history=[], frozen=False)

# ------------------------------------------------------------------ record (one call at the end of ff.build)
def record(run, root=None, now=None):
    """Write every decision point this run produced. Additive, never raises into the
    run (ff.build wraps it); returns a summary dict for the card/run log."""
    now = now or C.now()
    week = int(run['week'])
    P = run.get('proj')
    rows, pwin = [], []
    cache = {}
    for lg, R in (run.get('leagues') or {}).items():
        st = R['state']
        prov = provenance(run, st, root, now)
        rows += _rec_lineup(lg, week, R, P, prov, now, cache)
        rows += _rec_calls(lg, week, R, P, prov, now, cache)
        rows += _rec_breakout(lg, week, R, P, prov, now, cache)
        rows += _rec_flags(lg, week, R, prov, now)
        pw = _rec_pwin(lg, week, R, P, now)
        if pw: pwin.append(pw)
    rows += _rec_plans(run, week, prov_of=lambda lg: provenance(run, run['leagues'][lg]['state'], root, now), now=now)
    # a decision first seen after its deadline was never a decision (a post-kickoff sighting)
    have = latest('decisions', root=root)
    keep, freeze = [], set()
    for r in rows:
        dl = _ts(r['deadline'])
        if dl is not None and dl <= now:
            # past its deadline: the stored PREGAME version is frozen as it stands; a
            # post-deadline sighting never replaces it, and a first sighting is no decision
            if r['id'] in have and not have[r['id']].get('frozen'): freeze.add(r['id'])
            continue
        keep.append(r)
    # one row per id inside this run (the same subject can be raised by two producers)
    uniq = {}
    for r in keep: uniq.setdefault(r['id'], r)
    res = upsert('decisions', list(uniq.values()), root=root, merge=_merge_decision)
    if freeze:
        cur = read('decisions', root)
        for r in cur:
            if r['id'] in freeze: r['frozen'] = True; r['frozen_at'] = _iso(now)
        _write('decisions', cur, root)
    res['frozen'] = res.get('frozen', 0) + len(freeze)
    if pwin: upsert('pwin', pwin, root=root, merge=lambda o, n: dict(n, created=o.get('created')))
    cl = _rec_claims(run, week, now)
    if cl: upsert('claims', cl, root=root, merge=_merge_claim)
    res['kinds'] = dict(sorted(_count(r['kind'] for r in uniq.values()).items()))
    return res

def _count(it):
    d = defaultdict(int)
    for x in it: d[x] += 1
    return d

def _rec_lineup(lg, week, R, P, prov, now, cache):
    st, lu = R['state'], R['lineup']
    out = []
    opt, cur = lu.get('optimal') or {}, lu.get('current') or {}
    changes = {c['slot']: c for c in lu.get('changes', [])}
    calls = {c['change']['slot']: c for c in R.get('calls', []) if c['kind'] == 'start'}
    win = R.get('win') or {}
    wopt = {o['label']: o for o in (win.get('options') or [])}
    for s in st.cfg.slots:
        o, c = opt.get(s), cur.get(s)
        if o is None and c is None: continue
        kicks = [x.get('kick') for x in (o, c) if x and x.get('kick')]
        dl = min(kicks) if kicks else tue_rollover(week)
        rec = o['key'] if o else None
        opts = []
        for role, x in (('recommended', o), ('current', c)):
            if not x: continue
            if role == 'current' and o and x['key'] == o['key']: continue
            pw = None
            if role == 'recommended' and c and o and o['key'] != c['key']:
                sw = wopt.get(f"{o['player']} for {c['player']} at {s}")
                if sw: pw = dict(p_opp=_num(sw.get('p_opp'), 4), p_med=_num(sw.get('p_med'), 4))
            if role == 'current':
                cw = win.get('current') or {}
                if cw: pw = dict(p_opp=_num(cw.get('p_opp'), 4), p_med=_num(cw.get('p_med'), 4))
            opts.append(_opt(role, x['key'], x['player'], x.get('pos'), x.get('tm'), _proj(P, lg, x['key'], x.get('pos'), x.get('tm'), cache),
                             pts=x.get('pts'), p_win=pw, designation=x.get('designation'), kick=_iso(x.get('kick'))))
        ch = changes.get(s); call = calls.get(s)
        margin = ((o.get('pts') or 0) - (c.get('pts') or 0)) if (o and c and o['key'] != c['key']) else (o.get('pts') or 0) if (o and not c) else 0.0
        surfaced = bool(ch and not ch['provisional'] and call and call['ledger']['status'] == 'proposed' and call['gate'].verdict != 'BLOCK')
        d = _decision(lg, week, 'lineup_slot', s, '', now=now, deadline=dl, deadline_kind='kickoff', options=opts,
                      recommended=rec, margin=margin, margin_unit='pts_week',
                      gate=(call['gate'].verdict if call else 'PASS'), provisional=bool(ch and ch['provisional']),
                      surfaced=surfaced, prov=prov, subject_name=s,
                      extra=dict(rec_name=o['player'] if o else None, cur_key=c['key'] if c else None,
                                 cur_name=c['player'] if c else None, change=bool(ch), reason=(ch or {}).get('reason') or ''))
        cur_set = {x['key'] for x in cur.values() if x}
        if rec is not None and rec in cur_set:                                          # already starting (a permutation): nothing proposed
            d['first_current'] = rec; d['margin'] = 0.0
        else: d['first_current'] = (ch['sit']['key'] if ch and ch.get('sit') else (c['key'] if c else None))
        out.append(d)
    return out

def _gate_v(*gs):
    vs = [g.verdict for g in gs if g is not None]
    return 'BLOCK' if 'BLOCK' in vs else 'WARN' if 'WARN' in vs else 'PASS' if vs else None

def _rec_calls(lg, week, R, P, prov, now, cache):
    """Weekly upgrades and bench swaps (add_drop) and DEF/K streams (stream)."""
    out = []
    wu = R.get('week_upgrade')
    wu_key = ((wu or {}).get('call') or {}).get('item', {}).get('add', {}).get('key') if wu else None
    for c in R.get('calls', []):
        if c['kind'] == 'upgrade':
            u = c['item']; a, ov = u['add'], u['over']
            drop = (wu or {}).get('drop') if wu_key == a['key'] else None
            opts = [_opt('add', a['key'], a['name'], a.get('pos') or u['fam'], a.get('tm'), _proj(P, lg, a['key'], a.get('pos') or u['fam'], a.get('tm'), cache), pts=a.get('week')),
                    _opt('over', ov['key'], ov['player'], ov.get('pos'), ov.get('tm'), _proj(P, lg, ov['key'], ov.get('pos'), ov.get('tm'), cache), pts=ov.get('pts'))]
            if drop: opts.append(_opt('drop', drop['key'], drop['player'], drop.get('pos'), drop.get('tm'), _proj(P, lg, drop['key'], drop.get('pos'), drop.get('tm'), cache)))
            out.append(_decision(lg, week, 'add_drop', a['key'], drop['key'] if drop else '', now=now, deadline=tue_rollover(week),
                                 deadline_kind='tue_rollover', options=opts, recommended='add', margin=u['gain'], margin_unit='pts_week',
                                 gate=c['gate'].verdict, provisional=False,
                                 surfaced=(wu_key == a['key'] and c['ledger']['status'] == 'proposed'), prov=prov,
                                 subject_name=a['name'], alternative_name=drop['player'] if drop else None,
                                 extra=dict(source='upgrade', fam=u['fam'], over=ov['player'], ledger=c['ledger']['status'], call=c['ledger']['call'])))
        elif c['kind'] == 'swap':
            b = c['item']; a, d = b['add'], b['drop']
            opts = [_opt('add', a['key'], a['name'], a.get('pos'), a.get('tm'), _proj(P, lg, a['key'], a.get('pos'), a.get('tm'), cache), pts=a.get('week')),
                    _opt('drop', d['key'], d['player'], d.get('pos'), d.get('tm'), _proj(P, lg, d['key'], d.get('pos'), d.get('tm'), cache), pts=d.get('pts'))]
            v = _gate_v(c.get('gate_add'), c.get('gate_drop'))
            out.append(_decision(lg, week, 'add_drop', a['key'], d['key'], now=now, deadline=tue_rollover(week), deadline_kind='tue_rollover',
                                 options=opts, recommended='add', margin=b['gain'], margin_unit='pts_' + str(b.get('basis') or 'basis').split()[0],
                                 gate=v, provisional=False, surfaced=(c['ledger']['status'] == 'proposed' and v != 'BLOCK'), prov=prov,
                                 subject_name=a['name'], alternative_name=d['player'],
                                 extra=dict(source='swap', basis=b.get('basis'), dead=b.get('dead'), ledger=c['ledger']['status'])))
    for c in R.get('stream_calls', []):
        a, d, b = c['add'], c.get('drop'), c['board']
        fam = c['fam']
        opts = [_opt('add', a['key'], a['name'], fam, a.get('tm'), _proj(P, lg, a['key'], fam, a.get('tm'), cache), pts=a.get('week'))]
        if d: opts.append(_opt('drop', d['key'], d['player'], d.get('pos'), d.get('tm'), _proj(P, lg, d['key'], d.get('pos'), d.get('tm'), cache), pts=d.get('pts')))
        v = _gate_v(c.get('gate_add'), c.get('gate_drop'))
        out.append(_decision(lg, week, 'stream', a['key'], d['key'] if d else '', now=now, deadline=_stream_deadline(lg, week),
                             deadline_kind='kickoff', options=opts, recommended='add', margin=b.get('edge'), margin_unit='implied_total',
                             gate=v, provisional=False, surfaced=(c['ledger']['status'] == 'proposed' and v != 'BLOCK'), prov=prov,
                             subject_name=a['name'], alternative_name=d['player'] if d else None,
                             extra=dict(fam=fam, for_week=week + 1, hole=bool(c.get('hole')), ledger=c['ledger']['status'])))
    for a in (R.get('nextup') or {}).get('alerts', []):
        fa = a.get('fa')
        if not fa: continue
        r = a['row']
        dk = key(a['drop']) if a.get('drop') and not str(a['drop']).startswith(('an open', 'the spot')) else ''
        opts = [_opt('add', fa['key'], fa['name'], fa.get('pos'), fa.get('tm'), _proj(P, lg, fa['key'], fa.get('pos'), fa.get('tm'), cache), pts=fa.get('pts')),
                _opt('out_starter', r['key'], r['player'], r.get('pos'), r.get('tm'), None)]
        if dk: opts.append(_opt('drop', dk, a['drop'], None, None, None))
        dl = r.get('kick') or tue_rollover(week)
        out.append(_decision(lg, week, 'nextup', fa['key'], dk, now=now, deadline=dl, deadline_kind='kickoff', options=opts,
                             recommended='add', margin=fa.get('pts'), margin_unit='pts_week', gate=None, provisional=False,
                             surfaced=True, prov=prov, subject_name=fa['name'], alternative_name=a.get('drop'),
                             extra=dict(for_starter=r['player'], status=r.get('status'), drop_why=a.get('drop_why'))))
    return out

def _stream_deadline(lg, week):
    """A stream is for NEXT week: it closes at the first kickoff of week+1 (Thu ~8:15 pm ET)."""
    return C.week_start(week + 1) + dt.timedelta(days=2, hours=13, minutes=15)

_BID = re.compile(r'bid \$(\d+)')

def _rec_breakout(lg, week, R, P, prov, now, cache):
    out = []
    bk = R.get('breakout') or {}
    for x in bk.get('rows', []):
        if x['tier'] not in ('A', 'B'): continue
        m = x.get('move') or {}
        verb = m.get('verb') or 'NONE'
        d = m.get('drop')
        dk = key(d) if d and not str(d).startswith(('an open', 'the spot')) else ''
        opts = [_opt('add', x['key'], x['name'], x['pos'], x['tm'], _proj(P, lg, x['key'], x['pos'], x['tm'], cache), pts=x.get('week_pts'))]
        if d: opts.append(_opt('drop', dk or None, d, None, None, _proj(P, lg, dk, None, None, cache) if dk else None))
        dpts = next((dd['row'].get('pts') for dd in bk.get('drops', []) if dd['row']['player'] == d), None) if d else None
        margin = (x.get('week_pts') or 0) - (dpts or 0) if x.get('week_pts') is not None else None
        bid = _BID.search(m.get('when') or '')
        claim = lg == 'BSB' and verb in ('ADD', 'ADD-DEAD') and (x.get('kicked') or 'waiver' in (m.get('when') or '').lower() or 'claim' in (m.get('when') or '').lower())
        g = x.get('gate')
        extra = dict(tier=x['tier'], verb=verb, held=x.get('held') or '', usage=x.get('usage'), market=x.get('market'),
                     crowd=x.get('crowd'), prank=x.get('prank'), undrafted=x.get('undrafted'), when=m.get('when'), why=(m.get('why') or '')[:240],
                     usage_week=bk.get('week'), bid=int(bid.group(1)) if bid else None, claim=bool(claim))
        rec = 'add' if verb in ('ADD', 'ADD-DEAD') else 'none'
        common = dict(now=now, options=opts, recommended=rec, margin=margin, margin_unit='pts_week',
                      gate=g.verdict if g is not None else None, provisional=False, prov=prov, subject_name=x['name'],
                      alternative_name=d)
        out.append(_decision(lg, week, 'breakout_tier', x['key'], '', deadline=tue_rollover(week), deadline_kind='tue_rollover',
                             surfaced=(rec == 'add'), extra=extra, **common))
        if claim:
            from . import rules as RU
            run_at = RU.waiver_run_at(C.nfl_week(now) + (0 if RU.bsb_claims_open(now) else 1))
            out.append(_decision(lg, week, 'claim', x['key'], dk, deadline=run_at, deadline_kind='wed_run', surfaced=True,
                                 extra=extra, **common))
    return out

def _rec_flags(lg, week, R, prov, now):
    out = []
    for f in R.get('flags', []):
        if 'IR MOVE' not in f: continue
        nm = f.split(' at ')[0]
        out.append(_decision(lg, week, 'ir', key(nm), '', now=now, deadline=tue_rollover(week), deadline_kind='tue_rollover',
                             options=[_opt('ir', key(nm), nm, None, None, None)], recommended='ir', margin=None, margin_unit=None,
                             gate=None, provisional=False, surfaced=True, prov=prov, subject_name=nm, extra=dict(flag=f[:300])))
    return out

def _rec_plans(run, week, prov_of, now):
    out = []
    plans = run.get('plans') or {}
    if run.get('plan') and not plans:
        p = run['plan']; plans = {getattr(p, 'league', 'BSB'): p}
    for lg, p in plans.items():
        moves = getattr(p, 'moves', None)
        if not moves or lg not in (run.get('leagues') or {}): continue
        prov = prov_of(lg)
        for m in moves:
            if m['kind'] == 'add':
                subj = m['add_key']; alt = next((t['key'] for t in m['txns'] if t['op'] == 'drop'), '') or ''
            elif m['kind'] == 'ir':
                subj = m['txns'][0]['key']; alt = ''
            else:
                subj = m['txns'][0]['key']; alt = next((t['key'] for t in m['txns'] if t['op'] == 'bench'), '') or ''
            dl = _ts(m.get('deadline')) or (tue_rollover(week) if m['kind'] != 'lineup' else tue_rollover(week))
            out.append(_decision(lg, week, 'plan_move', subj, alt, now=now, deadline=dl,
                                 deadline_kind='kickoff' if m.get('deadline') else 'tue_rollover',
                                 options=[dict(role='txn', **{k: v for k, v in t.items() if k in ('op', 'player', 'key', 'slot', 'bid')}) for t in m['txns']],
                                 recommended=m['kind'], margin=m.get('J'), margin_unit='J', gate=((m.get('gates') or {}).get('add') or {}).get('verdict') if isinstance((m.get('gates') or {}).get('add'), dict) else None,
                                 provisional=bool(m.get('provisional')), surfaced=False, prov=prov,
                                 subject_name=m.get('add_name') or m.get('ir_name') or m.get('start'), alternative_name=m.get('drop_name') or m.get('sit'),
                                 extra=dict(plan_kind=m['kind'], when=m.get('when'), eff=m.get('eff'), tier=m.get('tier'), srcs=m.get('srcs'),
                                            value_terms=m.get('value_terms'), shadow=os.environ.get('FF_PLANNER') != '1')))
    return out

def _rec_pwin(lg, week, R, P, now):
    w = R.get('win') or {}
    c = w.get('current') or {}
    if c.get('p_opp') is None and c.get('p_med') is None: return None
    st = R['state']
    kicks = [P.kickoff(r['tm']) for r in st.starters()] if P is not None else []
    kicks = [k for k in kicks if k]
    first = min(kicks) if kicks else None
    if first is not None and first <= now: return None             # P(win) at lock: frozen at the first kickoff
    return dict(id=f'{lg}|{week}', league=lg, nfl_week=int(week), opp=w.get('opp'), p_opp=_num(c.get('p_opp'), 4),
                p_med=_num(c.get('p_med'), 4), mean=_num(c.get('mean')), sd=_num(c.get('sd')), lock=_iso(first),
                created=_iso(now), updated=_iso(now), frozen=False)

def _rec_claims(run, week, now):
    R = (run.get('leagues') or {}).get('BSB')
    if not R: return []
    from . import rules as RU
    wk_run = C.nfl_week(now) + (0 if RU.bsb_claims_open(now) else 1)
    out = []
    for x in (R.get('breakout') or {}).get('rows', []):
        m = x.get('move') or {}
        if m.get('verb') not in ('ADD', 'ADD-DEAD'): continue
        b = _BID.search(m.get('when') or '')
        if not b: continue
        out.append(dict(id=f'{wk_run}|{x["key"]}', run_week=wk_run, run_at=_iso(RU.waiver_run_at(wk_run)), player=x['name'], key=x['key'],
                        tier=x['tier'], recommended_bid=int(b.group(1)), my_bid=None, entered=None, status='pending',
                        won=None, winner=None, winning_bid=None, created=_iso(now), updated=_iso(now), frozen=False))
    return out

def _merge_claim(old, new):
    nr = dict(old)
    for k in ('recommended_bid', 'tier', 'updated', 'player'):
        if new.get(k) is not None: nr[k] = new[k]
    return nr

def bid(player, amount, root=None, now=None):
    """`ff.py bid <player> <amount>`: Caleb's own BSB bid for the next Wednesday run.
    The pump only ever sees WINNING bids; a losing bid exists nowhere else."""
    now = now or C.now()
    from . import rules as RU
    wk_run = C.nfl_week(now) + (0 if RU.bsb_claims_open(now) else 1)
    k = key(player)
    cur = latest('claims', root=root).get(f'{wk_run}|{k}')
    row = dict(cur or dict(id=f'{wk_run}|{k}', run_week=wk_run, run_at=_iso(RU.waiver_run_at(wk_run)), player=player, key=k,
                           tier=None, recommended_bid=None, status='pending', won=None, winner=None, winning_bid=None,
                           created=_iso(now), frozen=False))
    row.update(my_bid=int(amount), entered=_iso(now), updated=_iso(now))
    upsert('claims', [row], root=root, merge=lambda o, n: n)
    return row

# ------------------------------------------------------------------ actuals
def _stats_paths(week, pos):
    return [os.path.join(FFDATA, 'data', 'sleeper', f'stats_wk{week}_{pos}.csv'),
            os.path.join(ROOT, 'data', f'usage_wk{week}_{pos}.csv')]

def sleeper_stats(week, root=None):
    """-> {key: (row, pos)} from the pump's per-position stats (DEF keyed DST:TEAM).
    The pump's files only: the engine's usage_wk{W} copies are the same feed for
    QB/RB/WR/TE, but week 1's are a verified SUBSET (top ~40 by snaps), and a player
    missing from a subset is not a player who did not play."""
    out = {}
    for pos in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF'):
        p = os.path.join(FFDATA, 'data', 'sleeper', f'stats_wk{week}_{pos}.csv')
        if not os.path.exists(p): continue
        for r in csv.DictReader(open(p)):
            k = 'DST:' + team(r['team']) if pos == 'DEF' else key(f"{r['first_name']} {r['last_name']}")
            out.setdefault(k, (r, pos))
    return out

def yahoo_actuals(league, week, root=None):
    p = os.path.join(root or ROOT, 'data', 'actuals', f'{league}_wk{week}.csv')
    if not os.path.exists(p): return {}
    out = {}
    for r in csv.DictReader(open(p)):
        if r.get('final', '1') not in ('1', 'true', 'True'): continue
        try: out[key(r['player'])] = dict(pts=float(r['pts']), owner=r['owner'], slot=r['slot'], player=r['player'], tm=team(r.get('tm') or ''))
        except (TypeError, ValueError): pass
    return out

def _stats_teams(week):
    t = set()
    for k, (r, p) in sleeper_stats(week).items(): t.add(team(r['team']))
    return t

def _week_teams(week, root=None):
    """Teams that played in week `week`, from the week's projection log kickoffs."""
    t = set()
    for lg in ALL:
        p = os.path.join(root or ROOT, 'data', 'proj_log', f'{lg}_wk{week}.csv')
        if not os.path.exists(p): continue
        for r in csv.DictReader(open(p)):
            if r.get('kick'): t.add(team(r['tm']))
    return t

def week_complete(week, root=None, now=None):
    """Every game of the week is final: the week has rolled (Tue 07:00 ET) and the
    stats pull covers every team that had a kickoff on the projection log (or, with
    no log for the week, at least 26 teams)."""
    now = now or C.now()
    if now < C.week_start(week + 1): return False
    have = _stats_teams(week)
    if not have: return False
    need = _week_teams(week, root)
    if need: return need <= have
    return len(have) >= 26

class Actuals:
    """Realized points per (league, week, player): Yahoo exact first, Sleeper-scored second."""
    def __init__(self, root=None, now=None):
        self.root = root; self.now = now; self._st = {}; self._y = {}; self._done = {}

    def stats(self, week):
        if week not in self._st: self._st[week] = sleeper_stats(week, self.root)
        return self._st[week]

    def yahoo(self, league, week):
        if (league, week) not in self._y: self._y[(league, week)] = yahoo_actuals(league, week, self.root)
        return self._y[(league, week)]

    def pts(self, league, week, k, pos=None):
        """-> (points, source) or (None, reason). A completed week's offense/K/DEF player
        with no stat row did not play: 0.0. IDP without a Yahoo number is unavailable."""
        y = self.yahoo(league, week).get(k)
        if y is not None: return y['pts'], 'yahoo'
        s = self.stats(week).get(k)
        if s is not None:
            v = SC.actual(s[0], s[1], league)
            if v is not None: return round(v, 2), 'sleeper'
        fam = _fam(pos)
        if fam in ('DL', 'LB', 'DB') or (pos and any(p in IDP_FAM for p in str(pos).replace('/', ',').split(','))):
            return None, 'IDP — no stat feed and not on a Yahoo matchup page'
        if not self.stats(week): return None, f'no stats for week {week}'
        if week not in self._done: self._done[week] = week_complete(week, self.root, self.now)
        if not self._done[week]:
            # a week in progress: no stat row may only mean his game has not been played
            return None, f'week {week} not final'
        return 0.0, 'no stat row (did not play)'

def _fam(pos):
    p = (str(pos or '').split(',')[0].strip().upper())
    return {'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB'}.get(p, p)

def fidelity(weeks, root=None):
    """Sleeper-scored stand-in vs Yahoo's exact number on players both cover.
    -> [{league, pos, n, mae, bias}]"""
    A = Actuals(root); err = defaultdict(list)
    for w in weeks:
        st = A.stats(w)
        for lg in ALL:
            for k, y in A.yahoo(lg, w).items():
                s = st.get(k)
                if not s: continue
                v = SC.actual(s[0], s[1], lg)
                if v is None: continue
                err[(lg, s[1])].append(v - y['pts'])
    return [dict(league=lg, pos=p, n=len(e), mae=sum(abs(x) for x in e) / len(e), bias=sum(e) / len(e))
            for (lg, p), e in sorted(err.items())]

# ------------------------------------------------------------------ snapshots
_SNAPS = {}

def snapshots(league, root=None):
    """[(pulled ET, path)] sorted by pull time."""
    ck = (root or ROOT, league)
    if ck in _SNAPS: return _SNAPS[ck]
    out = []
    for f in glob.glob(os.path.join(root or ROOT, 'data', 'state', league, '*.json')):
        try: j = json.load(open(f))
        except Exception: continue
        t = T.try_ts(j.get('pulled'), 'legacy') if j.get('pulled') else None
        if t is None: t = T.try_ts(os.path.basename(f)[:-5], 'snapshot')
        if t is None: continue
        out.append((t, f))
    out.sort()
    _SNAPS[ck] = out
    return out

def _snap_rows(path):
    return json.load(open(path))['rows']

def snapshot_before(league, t, since=None, root=None):
    """The last snapshot pulled strictly before t (and at/after `since`), or None."""
    best = None
    for pt, f in snapshots(league, root):
        if pt >= t: break
        if since is not None and pt < since: continue
        best = (pt, f)
    return best

def my_lineup_at(league, t, week, root=None):
    """{slot: key} of Caleb's starters (slots numbered as the State numbers them) and
    the set of all his rostered keys, from the last snapshot before t in that week."""
    sb = snapshot_before(league, t, since=C.week_start(week), root=root)
    if not sb: return None
    from .state import State
    rows = [dict(r) for r in _snap_rows(sb[1])]
    st = State(league, rows, C.iso(sb[0]), source=os.path.basename(sb[1]))
    return dict(slots={r['slot']: r['key'] for r in st.mine if r['slot'] not in ('BN', 'IR')},
                roster={r['key'] for r in st.mine}, ir={r['key'] for r in st.mine if r['slot'] == 'IR'},
                src='snapshot ' + os.path.basename(sb[1]), at=sb[0])

_POSX = {}

def pos_index(league, root=None):
    ck = (root or ROOT, league)
    if ck not in _POSX: _POSX[ck] = _pos_index(league, root)
    return dict(_POSX[ck])

def _pos_index(league, root=None):
    """key -> Yahoo position string, newest snapshot wins (rostered players), plus the
    projection logs (any week) for players who were never in a snapshot we kept."""
    idx = {}
    for lg_p in glob.glob(os.path.join(root or ROOT, 'data', 'proj_log', f'{league}_wk*.csv')):
        for r in csv.DictReader(open(lg_p)):
            if r.get('pos'): idx[r['key']] = r['pos']
    for pt, f in snapshots(league, root):
        for r in _snap_rows(f):
            k = 'DST:' + team(r.get('nfl') or '') if (r.get('pos') or '').upper() == 'DEF' and r.get('nfl') else key(r['player'])
            if r.get('pos'): idx[k] = r['pos']
    return idx

def roster_week(league, week, root=None):
    """Caleb's active roster (keys, IR excluded) in a completed week: the Yahoo
    matchup page's end-of-week rows, else the last snapshot of that week."""
    me = ALL[league].name
    y = [k for k, r in yahoo_actuals(league, week, root).items() if r['owner'] == me and r['slot'] != 'IR']
    if y: return set(y), 'yahoo matchup page'
    sb = snapshot_before(league, C.week_start(week + 1), since=C.week_start(week), root=root)
    if not sb: return None, 'no roster on file'
    from .state import State
    st = State(league, [dict(r) for r in _snap_rows(sb[1])], C.iso(sb[0]))
    return {r['key'] for r in st.mine if r['slot'] != 'IR'}, 'snapshot ' + os.path.basename(sb[1])

def V(league, keys, week, A, posx, cfg=None):
    """Hindsight-optimal lineup points of a roster on actual points. -> (total, missing[])"""
    from . import lineup as LU
    from .state import _elig
    cfg = cfg or ALL[league]
    rows, vals, missing = [], {}, []
    for k in keys:
        pos = posx.get(k)
        if k.startswith('DST:') and not pos: pos = 'DEF'
        v, why = A.pts(league, week, k, pos)
        if v is None: missing.append((k, why)); continue
        rows.append(dict(key=k, elig=_elig(pos or '', league))); vals[k] = v
    tot, _ = LU.optimal_points(rows, cfg, vals)
    return tot, missing

# ------------------------------------------------------------------ the transactions log
def _log(league, root=None):
    p = os.path.join(root or ROOT, 'data', 'bsb_transactions.csv' if league == 'BSB' else 'hh_transactions.csv')
    if not os.path.exists(p): return []
    out = []
    for r in csv.DictReader(open(p)):
        t = T.try_ts(r.get('datetime'), 'yahoo_log')
        if t is None: continue
        out.append(dict(r, t=t, key=key(r['player']) if (r.get('pos') or '').upper() != 'DEF' else 'DST:' + team(r.get('nfl') or r['player'])))
    out.sort(key=lambda r: r['t'])
    return out

def _declined(league, subject_name, root=None):
    try:
        L = json.load(open(os.path.join(root or ROOT, 'data', 'ledger.json')))
    except Exception: return False
    return any(e['league'] == league and e['status'] == 'declined' and key(e['subject']) == key(subject_name or '') for e in L)

# ------------------------------------------------------------------ resolve
def resolve(root=None, now=None):
    """Resolutions for every decision whose deadline has passed. Idempotent."""
    now = now or C.now()
    D = latest('decisions', root=root)
    have = latest('resolutions', key_field='decision_id', root=root)
    logs = {lg: _log(lg, root) for lg in ALL}
    out = []
    for d in D.values():
        dl = _ts(d['deadline'])
        if dl is None or dl > now: continue
        old = have.get(d['id'])
        if old and old.get('frozen'): continue
        r = _resolve_one(d, logs[d['league']], root, now)
        if r is None: continue
        r['frozen'] = True
        out.append(r)
    return upsert('resolutions', out, key_field='decision_id', root=root) if out else dict(new=0, updated=0, unchanged=0, frozen=0)

def _resolve_one(d, log, root, now):
    lg, me = d['league'], ALL[d['league']].name
    base = dict(decision_id=d['id'], league=lg, nfl_week=d['nfl_week'], kind=d['kind'], subject=d['subject'],
                subject_name=d.get('subject_name'), resolved_at=_iso(now))
    if d['kind'] == 'lineup_slot':
        dl = _ts(d['deadline'])
        lu = my_lineup_at(lg, dl, d['nfl_week'], root)
        src = lu['src'] if lu else None
        if not lu:
            # no snapshot inside the week before his kickoff: the matchup page's slots
            # (end of week; a started player is locked, so this is the lineup at lock)
            y = yahoo_actuals(lg, d['nfl_week'], root)
            mine = {k: r for k, r in y.items() if r['owner'] == me}
            if not mine: return None
            from .state import State
            st = State(lg, [dict(owner=me, slot=r['slot'], player=r['player'], pos='', nfl=r['tm'], designation='none') for r in mine.values()], C.iso(now))
            lu = dict(slots={r['slot']: r['key'] for r in st.mine if r['slot'] not in ('BN', 'IR')}, roster=set(mine), src='yahoo matchup page slots')
            src = lu['src']
        starters = set(lu['slots'].values())
        rec = d['recommended']; first = d.get('first_current')
        in_slot = lu['slots'].get(d['subject'])
        # set-based, not slot-based: a recommended player who started in ANY slot was
        # followed (permutations are not overrides); the alternative is the occupant the
        # call proposed to replace, wherever he ended up
        if rec is None: status, how, chosen = 'moot', 'no recommendation', in_slot
        elif rec == first:
            status, how = ('moot', 'agreed — no change proposed') if rec in starters else ('overridden', "benched the engine's starter")
            chosen = rec if rec in starters else None
        elif rec in starters: status, how, chosen = 'followed', 'started as recommended', rec
        elif first is not None and first in starters: status, how, chosen = 'ignored', 'left as it was', first
        else: status, how, chosen = 'overridden', 'neither: started someone else', None
        return dict(base, status=status, how=how, chosen=chosen, recommended=rec, source=src)
    if d['kind'] == 'ir':
        dl = _ts(d['deadline'])
        lu = my_lineup_at(lg, dl, d['nfl_week'], root)
        moved = bool(lu and d['subject'] in lu.get('ir', set()))
        return dict(base, status='followed' if moved else 'ignored', how='moved to IR' if moved else 'not moved', chosen='ir' if moved else 'none',
                    recommended='ir', source=lu['src'] if lu else 'no snapshot')
    if d['kind'] in ADD_KINDS:
        c0 = _ts(d['created']); dl = _ts(d['deadline'])
        if d['kind'] == 'plan_move' and d.get('recommended') != 'add':
            return dict(base, status='moot', how=f"plan {d.get('recommended')} move (scored with its kind)", chosen=None, recommended=d.get('recommended'), source=None)
        subj, alt = d['subject'], d.get('alternative') or ''
        win = [r for r in log if c0 - dt.timedelta(hours=1) <= r['t'] <= dl + dt.timedelta(hours=1)]
        added = next((r for r in win if r['team'] == me and r['action'] == 'Add' and r['key'] == subj), None)
        dropped_alt = next((r for r in win if r['team'] == me and r['action'] == 'Drop' and alt and r['key'] == alt), None)
        my_adds = [r for r in win if r['team'] == me and r['action'] == 'Add' and r['key'] != subj]
        taken = next((r for r in win if r['team'] != me and r['action'] == 'Add' and r['key'] == subj), None)
        src = 'transactions log'
        if not added:
            # snapshot diff: on my roster at the deadline and not at creation
            a0 = snapshot_before(lg, c0 + dt.timedelta(minutes=1), root=root); a1 = snapshot_before(lg, dl, root=root)
            if a0 and a1 and a1[1] != a0[1]:
                had0 = {key(r['player']) for r in _snap_rows(a0[1]) if r['owner'] == me}
                had1 = {key(r['player']) for r in _snap_rows(a1[1]) if r['owner'] == me}
                if subj in had1 and subj not in had0:
                    added = dict(t=a1[0]); src = 'snapshot diff'
        rec = d.get('recommended')
        if d.get('gate') == 'BLOCK' and rec == 'add': rec = 'none'
        if rec == 'add':
            if added: status, how = 'followed', 'executed'
            elif _declined(lg, d.get('subject_name'), root): status, how = 'overridden', 'declined'
            elif dropped_alt or my_adds: status, how = 'overridden', 'other move: ' + ', '.join(sorted({r['player'] for r in my_adds}))[:120] if my_adds else 'dropped the spot for another use'
            else: status, how = 'ignored', 'no action' + (f' (then taken by {taken["team"]} {taken["t"]:%a %-I:%M %p})' if taken else '')
        else:
            status, how = ('overridden', 'added against a no-move call') if added else ('moot', 'no move recommended' + (' (gate BLOCK)' if d.get('gate') == 'BLOCK' else ''))
        return dict(base, status=status, how=how, chosen='add' if added else 'none', recommended=rec,
                    executed_at=_iso(added['t']) if added and added.get('t') else None, source=src,
                    taken_by=taken['team'] if taken else None)
    return None

# ------------------------------------------------------------------ outcomes
def _eff_week(d, res, log_t=None):
    """The first week the add could have played for Caleb."""
    w = d['nfl_week']
    if d['kind'] == 'stream': return w + 1
    if d['kind'] == 'claim': return w + 1 if _ts(d['deadline']) >= C.week_start(w + 1) else w
    ex = _ts(res.get('executed_at')) if res.get('executed_at') else None
    add = next((o for o in d.get('options', []) if o.get('role') == 'add'), {})
    kick = _ts(add.get('kick')) if add.get('kick') else None
    t = ex or _ts(d['created'])
    if kick is not None and t is not None and t >= kick: return w + 1
    if (d.get('extra') or {}).get('verb') and 'kicked off' in ((d.get('extra') or {}).get('when') or ''): return w + 1
    return w

def compute_outcomes(root=None, now=None):
    """Outcomes for every resolved decision whose horizon weeks are complete. Idempotent."""
    now = now or C.now()
    D = latest('decisions', root=root)
    RS = latest('resolutions', key_field='decision_id', root=root)
    have = latest('outcomes', root=root)
    done = {w for w in range(1, LAST_WEEK + 1) if week_complete(w, root, now)}
    A = Actuals(root, now)
    posx = {lg: None for lg in ALL}
    out = []
    for did, res in RS.items():
        d = D.get(did)
        if d is None: continue
        lg = d['league']
        if d['kind'] == 'lineup_slot':
            w = d['nfl_week']
            if w not in done: continue
            oid = f'{did}|1'
            if (have.get(oid) or {}).get('frozen'): continue
            rec, ch = d.get('recommended'), res.get('chosen')
            pr = posx[lg] = posx[lg] or pos_index(lg, root)
            ar, sr = A.pts(lg, w, rec, pr.get(rec)) if rec else (None, 'none')
            ac, sc = A.pts(lg, w, ch, pr.get(ch)) if ch else (None, 'not attributable to one slot (overridden)')
            row = dict(id=oid, decision_id=did, league=lg, nfl_week=w, kind=d['kind'], horizon='1', weeks=[w],
                       status=res['status'], predicted=d.get('margin'), margin_unit=d.get('margin_unit'), computed=_iso(now), frozen=True)
            alt = d.get('first_current')
            aa, sa_ = A.pts(lg, w, alt, pr.get(alt)) if alt else (0.0, 'empty slot')
            if ar is None or (ac is None and res['status'] != 'overridden'):
                row.update(available=False, why=f'recommended: {sr}; chosen: {sc}', delta=None)
            elif ac is None:
                row.update(available=True, delta=None, actual_recommended=ar, actual_chosen=None, src=[sr, sc],
                           proposed_change=bool(rec and rec != alt),
                           call_value=(round(ar - aa, 2) if aa is not None and rec != alt else None))
            else:
                # delta: what following would have changed vs what was done; call_value:
                # what the call was worth against the occupant it proposed to replace
                row.update(available=True, delta=round(ar - ac, 2), actual_recommended=ar, actual_chosen=ac, src=[sr, sc],
                           proposed_change=bool(rec and rec != alt),
                           call_value=(round(ar - aa, 2) if aa is not None and rec != alt else None))
            out.append(row); continue
        if d['kind'] not in ADD_KINDS or d.get('kind') == 'plan_move' and d.get('recommended') != 'add': continue
        add = d['subject']; drop = d.get('alternative') or None
        if not add: continue
        e = _eff_week(d, res)
        pr = posx[lg] = posx[lg] or pos_index(lg, root)
        for o in d.get('options', []):
            if o.get('key') and o.get('pos') and o['key'] not in pr: pr[o['key']] = o['pos']
        for h in HORIZONS:
            weeks = [e] if h == '1' else list(range(e, e + 3)) if h == '3' else list(range(e, LAST_WEEK + 1))
            weeks = [w for w in weeks if w <= LAST_WEEK]
            have_w = [w for w in weeks if w in done]
            if h != 'ros' and len(have_w) < len(weeks): continue
            if not have_w: continue
            oid = f'{did}|{h}'
            if (have.get(oid) or {}).get('frozen'): continue
            tot, miss, srcs = 0.0, [], []
            for w in have_w:
                R0, rsrc = roster_week(lg, w, root)
                if R0 is None: miss.append((w, rsrc)); continue
                with_add = (R0 | {add}) - ({drop} if drop else set())
                with_drop = (R0 - {add}) | ({drop} if drop else set())
                v1, m1 = V(lg, with_add, w, A, pr); v0, m0 = V(lg, with_drop, w, A, pr)
                crit = [m for m in m1 + m0 if m[0] in (add, drop)]
                if crit: miss += [(w, f'{k}: {why}') for k, why in crit]; continue
                tot += v1 - v0; srcs.append(rsrc)
            row = dict(id=oid, decision_id=did, league=lg, nfl_week=d['nfl_week'], kind=d['kind'], horizon=h, eff_week=e,
                       weeks=have_w, status=res['status'], recommended=res.get('recommended'), predicted=d.get('margin'),
                       margin_unit=d.get('margin_unit'), computed=_iso(now),
                       partial=(h == 'ros' and len(have_w) < len(weeks)), frozen=not (h == 'ros' and len(have_w) < len(weeks)))
            if miss:
                row.update(available=False, delta_add=None, why='; '.join(f'wk{w} {m}' for w, m in miss)[:300])
            else:
                row.update(available=True, delta_add=round(tot, 2), roster_src=sorted(set(srcs)))
            out.append(row)
    return upsert('outcomes', out, root=root) if out else dict(new=0, updated=0, unchanged=0, frozen=0)

# ------------------------------------------------------------------ claims + league moves
def resolve_claims(root=None, now=None):
    now = now or C.now()
    log = _log('BSB', root)
    me = ALL['BSB'].name
    out = []
    for c in latest('claims', root=root).values():
        if c.get('frozen'): continue
        ra = _ts(c.get('run_at'))
        if ra is None or now < ra: continue
        day = ra.date()
        w = next((r for r in log if r['action'] == 'Add' and (r.get('note') or '').lower() == 'waiver' and r['key'] == c['key'] and r['t'].date() == day), None)
        if w is None:
            # the log may not show the run yet (the pump reads it a few hours later)
            if now - ra < dt.timedelta(hours=30): continue
            out.append(dict(c, status='unclaimed' if c.get('my_bid') is None else 'lost?', won=False if c.get('my_bid') else None,
                            winner=None, winning_bid=None, updated=_iso(now), frozen=True)); continue
        won = w['team'] == me
        out.append(dict(c, status='won' if won else ('lost' if c.get('my_bid') else 'not bid'), won=won if c.get('my_bid') or won else None,
                        winner=w['team'], winning_bid=int(w['bid']) if (w.get('bid') or '').strip().isdigit() else None,
                        my_bid=c.get('my_bid') if c.get('my_bid') is not None else (int(w['bid']) if won and (w.get('bid') or '').isdigit() else None),
                        updated=_iso(now), frozen=True))
    return upsert('claims', out, root=root, merge=lambda o, n: n) if out else dict(new=0, updated=0, unchanged=0, frozen=0)

def update_league_moves(root=None, now=None, retro=None):
    """Every rival add on the logs; first flag from the decisions store (or the retro
    breakout reconstruction `retro` = {(league, key): (flag time, tier, how)}), lead
    time, and what he scored for the adder afterwards (completed weeks, while on his
    roster in that week's last snapshot; started = in a starting slot there)."""
    now = now or C.now()
    D = list(latest('decisions', root=root).values())
    flags = {}
    for d in D:
        if d['kind'] not in ('breakout_tier', 'add_drop', 'claim', 'nextup', 'stream', 'plan_move'): continue
        k = (d['league'], d['subject']); t = _ts(d['created'])
        tier = (d.get('extra') or {}).get('tier') or d['kind']
        if k not in flags or t < flags[k][0]: flags[k] = (t, tier, 'decision ' + d['kind'])
    if retro is None:
        retro = {}
        for r in read('retro_flags', root):
            t = _ts(r.get('flagged_at'))
            if t is None: continue
            kk = (r['league'], r['key'])
            if kk not in retro or t < retro[kk][0]: retro[kk] = (t, r.get('tier'), 'retro usage scan wk' + str(r.get('usage_week')))
    for k, v in retro.items():
        if k not in flags or v[0] < flags[k][0]: flags[k] = v
    done = [w for w in range(1, LAST_WEEK + 1) if week_complete(w, root, now)]
    A = Actuals(root, now)
    out = []
    for lg in ALL:
        me = ALL[lg].name
        posx = pos_index(lg, root)
        snaps_by_week = {}
        for w in done:
            sb = snapshot_before(lg, C.week_start(w) + dt.timedelta(days=5, hours=6), since=C.week_start(w) - dt.timedelta(days=1), root=root)
            snaps_by_week[w] = _snap_rows(sb[1]) if sb else None
        for r in _log(lg, root):
            if r['action'] != 'Add' or r['team'] == me: continue
            mid = f"{lg}|{r['datetime']}|{r['team']}|{r['key']}"
            w_add = C.nfl_week(r['t'])
            pts = started = 0.0; weeks = []; unavailable = []
            for w in done:
                if w < w_add: continue
                rows = snaps_by_week.get(w)
                if rows is None: continue
                mine = [x for x in rows if x['owner'] == r['team'] and (key(x['player']) == r['key'] or ('DST:' + team(x.get('nfl') or '')) == r['key'] and (x.get('pos') or '').upper() == 'DEF')]
                if not mine: continue
                v, why = A.pts(lg, w, r['key'], posx.get(r['key']) or r.get('pos'))
                if v is None: unavailable.append(w); continue
                weeks.append(w); pts += v
                if mine[0]['slot'] not in ('BN', 'IR'): started += v
            f = flags.get((lg, r['key']))
            out.append(dict(id=mid, league=lg, at=_iso(r['t']), team=r['team'], player=r['player'], key=r['key'], pos=r.get('pos'),
                            nfl=r.get('nfl'), bid=int(r['bid']) if (r.get('bid') or '').strip().isdigit() else None, note=r.get('note'),
                            first_flag=_iso(f[0]) if f else None, flag_tier=f[1] if f else None, flag_src=f[2] if f else None,
                            lead_h=round((r['t'] - f[0]).total_seconds() / 3600, 1) if f else None,
                            pts_after=round(pts, 2), started_after=round(started, 2), weeks=weeks, idp_unavailable=unavailable,
                            updated=_iso(now)))
    return upsert('league_moves', out, root=root) if out else dict(new=0, updated=0, unchanged=0, frozen=0)

# ------------------------------------------------------------------ the one entry point for resolution
def update(root=None, now=None, retro=None):
    """Resolve, score, settle claims and refresh league moves — idempotent; cheap when
    nothing is due. -> summary dict."""
    now = now or C.now()
    s = dict(resolutions=resolve(root, now), outcomes=compute_outcomes(root, now), claims=resolve_claims(root, now))
    try: s['league_moves'] = update_league_moves(root, now, retro=retro)
    except Exception as e: s['league_moves'] = f'failed: {e!r}'
    return s

def import_ledger(root=None, now=None):
    """One-shot, idempotent: the ledger's historical start/add calls as decisions
    (provenance 'ledger'), so weeks before this store existed are scored too. Blocked
    calls come in with gate BLOCK (moot). The last version of each call wins."""
    now = now or C.now()
    try: L = json.load(open(os.path.join(root or ROOT, 'data', 'ledger.json')))
    except Exception: return dict(new=0)
    rows = {}
    last_start = {}
    for e in L:
        if e['kind'] == 'start' and e.get('week'): last_start[(e['league'], e['week'], key(e['subject']))] = e['id']
    rx_start = re.compile(r'^start (.+?) at (\S+)$'); rx_over = re.compile(r'^over (.+?) [+-]\d')
    rx_swap = re.compile(r'^drop (.+?) -> add (.+)$'); rx_up = re.compile(r'^add (.+?) \((\w+)\) over (.+)$')
    rx_stream = re.compile(r'^(?:stream|bye cover:) (.+?) for week (\d+)(?:, drop (.+))?$')
    for e in L:
        lg, wk = e['league'], e.get('week')
        if not wk: continue
        t = _ts(e['ts']) or now
        prov = dict(engine='ledger', snapshot=None, kalshi=None, sleeper_as_of=None, ledger_id=e['id'])
        m = rx_start.match(e['call'])
        if e['kind'] == 'start' and m:
            if last_start.get((lg, wk, key(e['subject']))) != e['id']: continue      # superseded by a later version of the same call
            nm, slot = m.group(1), m.group(2)
            o = rx_over.match(e.get('detail') or '')
            cur = o.group(1) if o else None
            gain = re.search(r'([+-]\d+\.\d+)', e.get('detail') or '')
            dl = _ts(e.get('resolves_at')) or tue_rollover(wk)
            d = _decision(lg, wk, 'lineup_slot', slot, '', now=t, deadline=dl, deadline_kind='kickoff',
                          options=[_opt('recommended', key(nm), nm, None, None, None), _opt('current', key(cur) if cur and cur != 'empty' else None, cur, None, None, None)],
                          recommended=key(nm), margin=float(gain.group(1)) if gain else None, margin_unit='pts_week', gate=e.get('verdict'),
                          provisional=e.get('provisional'), surfaced=(e['status'] in ('proposed', 'executed', 'expired') and not e.get('provisional')),
                          prov=prov, subject_name=slot, extra=dict(source='ledger', status=e['status'], call=e['call']))
            d['first_current'] = key(cur) if cur and cur != 'empty' else None
            rows[d['id']] = d; continue
        if e['kind'] != 'add': continue
        kind, add, drop = 'add_drop', None, None
        m1, m2, m3 = rx_swap.match(e['call']), rx_up.match(e['call']), rx_stream.match(e['call'])
        if m1: drop, add = m1.group(1), m1.group(2)
        elif m2: add = m2.group(1)
        elif m3: kind, add, drop = 'stream', m3.group(1), m3.group(3)
        else: continue
        gain = re.search(r'([+-]?\d+\.\d+)', e.get('detail') or '')
        dl = _stream_deadline(lg, wk) if kind == 'stream' else tue_rollover(wk)
        d = _decision(lg, wk, kind, key(add), key(drop) if drop else '', now=t, deadline=dl, deadline_kind='kickoff' if kind == 'stream' else 'tue_rollover',
                      options=[_opt('add', key(add), add, None, None, None)] + ([_opt('drop', key(drop), drop, None, None, None)] if drop else []),
                      recommended='add', margin=float(gain.group(1)) if gain else None, margin_unit='pts_week' if '/wk' in (e.get('detail') or '') else 'ledger',
                      gate=e.get('verdict'), provisional=e.get('provisional'), surfaced=e['status'] in ('proposed', 'executed', 'expired', 'declined'),
                      prov=prov, subject_name=add, alternative_name=drop, extra=dict(source='ledger', status=e['status'], call=e['call']))
        if d['id'] in rows and _ts(rows[d['id']]['created']) < t:
            d['created'] = rows[d['id']]['created']
        rows[d['id']] = d
    have = latest('decisions', root=root)
    fresh = []
    for d in rows.values():
        if d['id'] in have: continue                   # a live-recorded row wins
        dl = _ts(d['deadline'])
        if dl is not None and dl <= now: d['frozen'] = True
        fresh.append(d)
    return upsert('decisions', fresh, root=root) if fresh else dict(new=0, updated=0, unchanged=0, frozen=0)

def summary(root=None):
    D = latest('decisions', root=root); RS = latest('resolutions', key_field='decision_id', root=root)
    O = latest('outcomes', root=root)
    return dict(decisions=len(D), resolved=len(RS), outcomes=len(O), claims=len(read('claims', root)), league_moves=len(read('league_moves', root)))
