#!/usr/bin/env python3
"""Scenario harness — a class of failure is tested before Caleb sees it.

  python3 scenarios/run.py [id ...] [-v] [--keep]      (or: python3 ff.py scenarios)

Each scenarios/<id>/scenario.yaml names a frozen base (scenarios/_base, made by
freeze.py from a real week), the clock (`now`), mutations (mutate.py operators) and
an `expect:` block. Per scenario the runner copies the base's ENGINE data files into
a temp FF_ROOT, applies the mutations, and runs ff.build() + the card + the sanity
read in a subprocess (scenarios/_one.py) with FF_ROOT / FF_NOW / FF_FAST=1 and the
pump repo pointed at nothing, so nothing outside the temp root is read as state or
written. Then data/plan.json is diffed against `expect`:

  refused: [C4]                  the contract REFUSED with (at least) these codes
  contract_codes: [C8]           these codes are among the violations (run not refused)
  sanity: pass | fail            the sanity read (checks 1-8) and plan simulation (11)
  lineup: {HH: {K: Name}}        partial slot -> player match on the engine's lineup
  actions_include / actions_exclude: [{league, kind, add, drop, subject, verb, when_contains,
                                       when_excludes, drop_in, drop_not_in, slot, start, sit, provisional}]
  blocked_include: [{league, subject, gate}]
  counts: [{league, kind, verb, eq | max | min}]
  card_contains / card_excludes: [text]
  plan_include / plan_exclude: [{league, kind, add, drop, ir, when_contains}]  (shadow planner)
  twice: true                    run twice on the same root: identical plan.json, no new ledger rows

A stub (status: stub) is listed, not run. A scenario with `known_failure: <why>` is a
real engine bug found by the harness and not yet fixed: it runs, prints XFAIL with the
mismatch, and does not block; once it passes it prints XPASS (remove the field).
Exit 1 on any FAIL.
"""
import os, sys, json, shutil, subprocess, tempfile, time, copy
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
CODE = os.path.dirname(HERE)
sys.path.insert(0, CODE); sys.path.insert(0, HERE)
try:
    import yaml
except ImportError:                     # the pump's runner without PyYAML: say so loudly, do not refuse every card over a library
    yaml = None

def load(sid):
    return yaml.safe_load(open(os.path.join(HERE, sid, 'scenario.yaml')))

def all_ids():
    return sorted(d for d in os.listdir(HERE) if os.path.isfile(os.path.join(HERE, d, 'scenario.yaml')) and not d.startswith('_'))

def build_root(sid, sc):
    import mutate as MU
    tmp = tempfile.mkdtemp(prefix=f'ffscn_{sid}_')
    base = sc.get('base', '_base')
    src = os.path.join(HERE, base, 'data') if base else None
    own = os.path.join(HERE, sid, 'data')
    shutil.copytree(src if src and os.path.isdir(src) else own, os.path.join(tmp, 'data'))
    if src and os.path.isdir(own): shutil.copytree(own, os.path.join(tmp, 'data'), dirs_exist_ok=True)
    ctx = dict(now=str(sc['now']), week=int(sc.get('week', 4)))
    os.environ.setdefault('FF_NOW', ctx['now'])
    for m in sc.get('mutations') or []:
        ctx = MU.apply(tmp, m, ctx)
    return tmp, ctx

def _env(root, now):
    e = dict(os.environ, FF_ROOT=root, FF_NOW=now, FF_FAST='1', FFDATA_REPO='/nonexistent/ffdata_repo',
             FFDATA_ROOT='/nonexistent/ffdata_repo', PYTHONWARNINGS='ignore', PYTHONHASHSEED='0')
    e.pop('FF_PLANNER', None) if not os.environ.get('FF_SCN_PLANNER') else None
    return e

def _work(root, now):
    r = subprocess.run([sys.executable, os.path.join(HERE, '_one.py')], env=_env(root, now), capture_output=True, text=True, timeout=300)
    p = os.path.join(root, 'out.json')
    if not os.path.exists(p):
        return dict(crash=(r.stdout[-1500:] + '\n' + r.stderr[-2500:]))
    return json.load(open(p))

def run_one(sid, keep=False):
    sc = load(sid)
    t0 = time.time()
    root, ctx = build_root(sid, sc)
    try:
        res = _work(root, ctx['now'])
        if (sc.get('expect') or {}).get('twice') and not res.get('crash') and not res.get('refused'):
            pj1 = open(os.path.join(root, 'data', 'plan.json')).read(); led1 = res.get('ledger_rows')
            res2 = _work(root, ctx['now'])
            pj2 = open(os.path.join(root, 'data', 'plan.json')).read()
            res['twice'] = dict(identical=(pj1 == pj2), ledger_before=led1, ledger_after=res2.get('ledger_rows'),
                                diff=_first_diff(json.loads(pj1), json.loads(pj2)))
    finally:
        if not keep: shutil.rmtree(root, ignore_errors=True)
        else: print(f'  [{sid}] root kept: {root}')
    res['_secs'] = round(time.time() - t0, 1); res['_now'] = ctx['now']
    return res

def _first_diff(a, b, path=''):
    if type(a) != type(b): return f'{path}: {str(a)[:80]} != {str(b)[:80]}'
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b: return f'{path}/{k}: only on one side'
            d = _first_diff(a[k], b[k], f'{path}/{k}')
            if d: return d
        return None
    if isinstance(a, list):
        if len(a) != len(b): return f'{path}: len {len(a)} != {len(b)}'
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_diff(x, y, f'{path}[{i}]')
            if d: return d
        return None
    return None if a == b else f'{path}: {str(a)[:80]} != {str(b)[:80]}'

# ------------------------------------------------------------------ matching
def _eq(a, b):
    if b is None: return a is None
    if isinstance(b, bool): return bool(a) == b
    return str(a or '').strip().lower() == str(b).strip().lower()

def match(item, flt):
    for k, v in flt.items():
        if k in ('league', 'why'): continue
        if k == 'when_contains':
            if str(v).lower() not in str(item.get('when') or '').lower(): return False
        elif k == 'when_excludes':
            if str(v).lower() in str(item.get('when') or '').lower(): return False
        elif k == 'drop_in':
            if not any(_eq(item.get('drop'), x) for x in v): return False
        elif k == 'drop_not_in':
            if any(_eq(item.get('drop'), x) for x in v): return False
        elif k == 'drop_contains':
            if str(v).lower() not in str(item.get('drop') or '').lower(): return False
        elif k == 'kind_in':
            if not any(_eq(item.get('kind'), x) for x in v): return False
        elif k == 'verb_in':
            if not any(_eq(item.get('verb'), x) for x in v): return False
        elif k == 'gate':
            if not any(g.split(':')[0].startswith(str(v)) for g in item.get('gates') or []): return False
        elif k == 'txn_contains':
            if not any(str(v).lower() in t.lower() for t in item.get('txns') or []): return False
        elif not _eq(item.get(k), v): return False
    return True

def _leagues(flt, plan):
    return [flt['league']] if flt.get('league') else list(plan['leagues'])

def check(sc, res):
    """-> first mismatch string, or None."""
    E = sc.get('expect') or {}
    if res.get('crash'): return 'worker crashed: ' + res['crash'][-900:]
    if 'refused' in E:
        want = set(E['refused'] or [])
        if not want and res.get('refused'): return f"contract REFUSED {res['refused']} (expected to run)"
        if want and not want <= set(res.get('refused') or []): return f"expected contract REFUSE {sorted(want)}, got refused={res.get('refused')} codes={res.get('codes')}"
        if want: return None
    elif res.get('refused'):
        return f"contract REFUSED {res['refused']}: " + (res.get('log') or '')[-400:]
    plan = res['plan']
    for c in E.get('contract_codes') or []:
        if c not in (res.get('codes') or []): return f'expected contract code {c} among {res.get("codes")}'
    if 'sanity' in E:
        bad = (res.get('sanity') or []) + [s for s in (res.get('plan_sim') or [])]
        if E['sanity'] == 'pass' and bad: return 'sanity read failed: ' + ' | '.join(bad)[:500]
        if E['sanity'] == 'fail' and not bad: return 'expected the sanity read to fail; it passed'
    for lg, slots in (E.get('lineup') or {}).items():
        lu = plan['leagues'][lg]['lineup']
        for s, who in slots.items():
            if isinstance(who, dict) and 'not' in who:
                if _eq(lu.get(s), who['not']): return f'{lg} lineup {s}: {lu.get(s)!r} must not be there'
            elif not _eq(lu.get(s), who): return f'{lg} lineup {s}: expected {who!r}, engine has {lu.get(s)!r}'
    for f in E.get('actions_include') or []:
        if not any(match(a, f) for lg in _leagues(f, plan) for a in plan['leagues'][lg]['actions']):
            return f'actions_include not found: {f} — have: ' + '; '.join(_brief(a) for lg in _leagues(f, plan) for a in plan['leagues'][lg]['actions'] if a['kind'] != 'breakout' or a.get('verb') in ('ADD', 'ADD-DEAD'))[:600]
    for f in E.get('actions_exclude') or []:
        hit = [a for lg in _leagues(f, plan) for a in plan['leagues'][lg]['actions'] if match(a, f)]
        if hit: return f'actions_exclude matched: {f} -> {_brief(hit[0])}'
    for f in E.get('blocked_include') or []:
        if not any(match(b, f) for lg in _leagues(f, plan) for b in plan['leagues'][lg]['blocked']):
            return f'blocked_include not found: {f} — blocked: {[(b["subject"], b["gates"]) for lg in _leagues(f, plan) for b in plan["leagues"][lg]["blocked"]]}'
    for f in E.get('counts') or []:
        fl = {k: v for k, v in f.items() if k not in ('eq', 'max', 'min')}
        n = sum(1 for lg in _leagues(f, plan) for a in plan['leagues'][lg]['actions'] if match(a, fl))
        if 'eq' in f and n != f['eq']: return f'count {fl}: {n} != {f["eq"]}'
        if 'max' in f and n > f['max']: return f'count {fl}: {n} > max {f["max"]}'
        if 'min' in f and n < f['min']: return f'count {fl}: {n} < min {f["min"]}'
    txt = (res.get('card_text') or '').lower()
    for s in E.get('card_contains') or []:
        if str(s).lower() not in txt: return f'card does not contain {s!r}'
    for s in E.get('card_excludes') or []:
        if str(s).lower() in txt: return f'card contains {s!r}'
    for key_, want in (('plan_include', True), ('plan_exclude', False)):
        for f in E.get(key_) or []:
            moves = [m for lg in _leagues(f, plan) for m in (plan['leagues'][lg]['planner'].get('moves') or [])]
            hit = [m for m in moves if match(m, f)]
            if want and not hit: return f'plan_include not found: {f} — planner moves: {[m["txns"] for m in moves]}'
            if not want and hit: return f'plan_exclude matched: {f} -> {hit[0]["txns"]} [{hit[0]["when"]}]'
    if E.get('twice'):
        tw = res.get('twice') or {}
        if not tw.get('identical'): return f"second run changed plan.json: {tw.get('diff')}"
        if tw.get('ledger_after') != tw.get('ledger_before'): return f"second run added ledger rows: {tw.get('ledger_before')} -> {tw.get('ledger_after')}"
    return None

def _brief(a):
    return f"{a['kind']}:{a.get('verb') or ''} add={a.get('add')} drop={a.get('drop')} start={a.get('start')} sit={a.get('sit')} when={str(a.get('when'))[:40]} {a.get('verdict')}"

def golden_expect(res):
    """A frozen real case: its current plan becomes the expectation (freeze.py --golden)."""
    if res.get('refused'): return dict(refused=res['refused'])
    E = dict(sanity='pass' if not (res.get('sanity') or res.get('plan_sim')) else 'fail', lineup={}, actions_include=[], plan_include=[])
    for lg, L in res['plan']['leagues'].items():
        E['lineup'][lg] = {s: p for s, p in L['lineup'].items() if p}
        for a in L['actions']:
            if a['kind'] == 'breakout' and a.get('verb') not in ('ADD', 'ADD-DEAD'): continue
            E['actions_include'].append({k: v for k, v in dict(league=lg, kind=a['kind'], add=a.get('add'), drop=a.get('drop'), start=a.get('start')).items() if v is not None})
        for m in L['planner'].get('moves') or []:
            E['plan_include'].append({k: v for k, v in dict(league=lg, kind=m['kind'], add=m.get('add'), drop=m.get('drop'), ir=m.get('ir')).items() if v is not None})
    return E

def main(argv=()):
    argv = list(argv)
    if yaml is None:
        print('SCENARIO SUITE SKIPPED: PyYAML is not installed (pip install pyyaml) — the card was NOT checked against the scenarios'); return 0
    verbose = '-v' in argv; keep = '--keep' in argv
    ids = [a for a in argv if not a.startswith('-')] or all_ids()
    t0 = time.time()
    todo, stubs = [], []
    for sid in ids:
        sc = load(sid)
        (stubs if sc.get('status') == 'stub' else todo).append(sid)
    jobs = int(os.environ.get('FF_SCN_JOBS', os.cpu_count() or 2))
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        results = dict(zip(todo, ex.map(lambda s: run_one(s, keep), todo)))
    fails = 0
    print('=' * 96); print(f'SCENARIOS — {len(todo)} run, {len(stubs)} stub(s)'); print('=' * 96)
    for sid in todo:
        sc = load(sid); res = results[sid]
        why = check(sc, res)
        kf = sc.get('known_failure')
        tag = ('XFAIL' if why else 'XPASS') if kf else ('FAIL' if why else 'PASS')
        fails += bool(why) and not kf
        print(f"[{tag}] {sid:34s} {res.get('_secs', 0):5.1f}s  {sc.get('title', '')[:60]}")
        if why: print(f'        first mismatch: {why}')
        if kf: print(f'        known failure (reported, not blocking): {kf[:200]}' if why else '        known_failure no longer reproduces — remove it from scenario.yaml')
        if verbose and not res.get('crash') and res.get('plan'):
            for lg, L in res['plan']['leagues'].items():
                for a in L['actions']:
                    if a['kind'] == 'breakout' and a.get('verb') not in ('ADD', 'ADD-DEAD', 'BLOCKED'): continue
                    print(f'        {lg} {_brief(a)}')
                for m in L['planner'].get('moves') or []: print(f"        {lg} PLAN {m['txns']} [{m['when']}]")
    for sid in stubs:
        print(f"[STUB] {sid:34s}        {load(sid).get('title', '')[:60]}")
    print(f'{len(todo) - fails}/{len(todo)} scenarios behaved as required ({time.time() - t0:.0f}s).' + (f'  {fails} FAILURES.' if fails else '  SCENARIOS SOUND.'))
    return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
