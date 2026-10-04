#!/usr/bin/env python3
"""freeze.py — copy the live week's inputs into a scenario base (or a scenario).

  python3 scenarios/freeze.py <name> [--src /home/claude/bsb2] [--now ISO] [--golden]

Writes scenarios/<name>/data/ with exactly the files ff.build() reads for the data
week (ENGINE files, not pump files): roster snapshots (the newest, plus one per day
for 8 days so recently_dropped/recently_added see history), sleeper_off/idp for the
week TRIMMED to the rostered players plus the top FAs per position and every player
with real usage (the phantom audit is O(pool x rosters): trimming takes a build from
~9 s to ~3 s), games, look-ahead lines, season blend/env, windows, roles.json,
matchups.json, the week's actuals and Yahoo projections, usage for the two previous
weeks, trending adds, both transactions logs, asof.json and yahoo/ when present.
NOT copied: kalshi.csv / archive (fitting a full pull costs ~70 s; a scenario that
needs ladders writes a small kalshi.csv), espn_props.csv, the ledger (empty), the
outcome stores, proj_log. A scenario.yaml with `now:` is written; with --golden the
current plan (run through the harness) is recorded as the scenario's expect block.
Reads --src only; never writes outside scenarios/<name>.
"""
import sys, os, csv, json, glob, shutil, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

TOP_FA = 30

def _rows(p):
    return list(csv.DictReader(open(p))) if os.path.exists(p) else []

def freeze(name, src, now=None, golden=False):
    os.environ['FF_ROOT'] = src
    if now: os.environ['FF_NOW'] = now
    from lib import clock as C
    from lib.names import key
    S = os.path.join(src, 'data'); out = os.path.join(HERE, name); D = os.path.join(out, 'data')
    if os.path.exists(D): shutil.rmtree(D)
    os.makedirs(D)
    W = C.data_week()
    cp = lambda rel: (os.makedirs(os.path.dirname(os.path.join(D, rel)), exist_ok=True),
                      shutil.copy(os.path.join(S, rel), os.path.join(D, rel))) if os.path.exists(os.path.join(S, rel)) else None
    for rel in ('espn_games.csv', 'lines_wk3_9.csv', 'lines_wk10_18.csv', 'season_blend.json', 'season_env.json',
                'windows.json', 'roles.json', 'matchups.json', 'trending_adds.csv', 'bsb_transactions.csv',
                'hh_transactions.csv', 'asof.json', f'actuals/BSB_wk{W}.csv', f'actuals/HH_wk{W}.csv',
                f'yahoo_BSB_wk{W}.csv', f'yahoo_HH_wk{W}.csv'):
        cp(rel)
    for w in (W - 1, W - 2):
        for pos in ('QB', 'RB', 'WR', 'TE'): cp(f'usage_wk{w}_{pos}.csv')
    if os.path.isdir(os.path.join(S, 'yahoo')):
        for f in os.listdir(os.path.join(S, 'yahoo')):
            if f.endswith(f'wk{W}.csv') or f.endswith('_rosters.csv') or f == 'pulled.txt': cp(f'yahoo/{f}')
    # snapshots: newest + the last of each day for 8 days
    rostered = set()
    tnow = C.now()
    for lg in ('BSB', 'HH'):
        fs = sorted(glob.glob(os.path.join(S, 'state', lg, '*.json')))
        keep, days = [], set()
        for f in reversed(fs):
            stamp = os.path.basename(f)[:-5]
            try: t = dt.datetime.strptime(stamp, '%Y-%m-%dT%H%M').replace(tzinfo=C.ET)
            except ValueError: continue
            if t > tnow: continue                       # never a snapshot from after the pinned clock
            if not keep or (t.date() not in days and (tnow - t).days <= 8): keep.append(f); days.add(t.date())
        os.makedirs(os.path.join(D, 'state', lg), exist_ok=True)
        for f in keep:
            shutil.copy(f, os.path.join(D, 'state', lg, os.path.basename(f)))
            for r in json.load(open(f))['rows']: rostered.add(key(r['player']))
    # usage keys (players with a role the breakout scan reads)
    used = set()
    for f in glob.glob(os.path.join(D, 'usage_wk*.csv')):
        for r in _rows(f):
            try:
                if float(r.get('off_snp') or 0) >= 0.4 * float(r.get('tm_off_snp') or 1e9) or float(r.get('rec_tgt') or 0) >= 4:
                    used.add(key(f"{r['first_name']} {r['last_name']}"))
            except ValueError: pass
    for fn, ppos in ((f'sleeper_off_wk{W}.csv', 'pos'), (f'sleeper_idp_wk{W}.csv', 'pos')):
        rows = _rows(os.path.join(S, fn))
        if not rows: continue
        by = {}
        for r in rows: by.setdefault(r[ppos], []).append(r)
        keepk = set()
        for pos, rs in by.items():
            sc = (lambda r: float(r.get('pts_ppr') or 0)) if 'pts_ppr' in rs[0] else (lambda r: sum(float(r.get(c) or 0) for c in ('solo', 'ast', 'sack')))
            for r in sorted(rs, key=sc, reverse=True)[:TOP_FA]: keepk.add(key(r['player']))
        kept = [r for r in rows if key(r['player']) in rostered or key(r['player']) in used or key(r['player']) in keepk]
        with open(os.path.join(D, fn), 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(kept)
    open(os.path.join(D, 'ledger.json'), 'w').write('[]\n')
    # as-of from content: when the source has no data/asof.json (a clone, not the
    # loader's output) the frozen files are stamped with the newest snapshot's pull
    # time — the moment the week was frozen, stated as such
    ap = os.path.join(D, 'asof.json')
    if not os.path.exists(ap):
        pulled = max(json.load(open(f))['pulled'] for f in glob.glob(os.path.join(D, 'state', '*', '*.json')))
        files = {rel: dict(as_of=pulled, src='freeze.py: newest snapshot pull') for rel in
                 ['bsb_transactions.csv', 'hh_transactions.csv', f'sleeper_off_wk{W}.csv', f'sleeper_idp_wk{W}.csv',
                  'espn_games.csv', 'trending_adds.csv', f'yahoo_BSB_wk{W}.csv', f'yahoo_HH_wk{W}.csv',
                  f'actuals/BSB_wk{W}.csv', f'actuals/HH_wk{W}.csv'] + [os.path.relpath(p, D) for p in glob.glob(os.path.join(D, 'usage_wk*.csv'))]
                 if os.path.exists(os.path.join(D, rel))}
        json.dump(dict(pump_week=W, files=files), open(ap, 'w'), indent=1)
    y = os.path.join(out, 'scenario.yaml')
    if not os.path.exists(y):
        open(y, 'w').write(f"id: {name}\ntitle: frozen from {src} week {W}\nnow: '{C.iso(tnow)}'\nweek: {W}\nbase: null\nexpect:\n  sanity: pass\n")
    print(f'frozen week {W} from {src} -> {out} ({sum(len(f) for _, _, f in os.walk(D))} files)')
    if golden:
        import run as R
        res = R.run_one(name)
        import yaml
        sc = yaml.safe_load(open(y))
        sc['expect'] = R.golden_expect(res)
        yaml.safe_dump(sc, open(y, 'w'), sort_keys=False)
        print('golden expect written')
    return out

if __name__ == '__main__':
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(2)
    src = a[a.index('--src') + 1] if '--src' in a else os.environ.get('FF_ROOT', '/home/claude/bsb2')
    now = a[a.index('--now') + 1] if '--now' in a else None
    freeze(a[0], src, now, golden='--golden' in a)
