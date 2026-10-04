#!/usr/bin/env python3
"""mutate.py — operators that turn a frozen base into a scenario.

Each operator edits the ENGINE data files of a scenario root in place (run.py calls
them on a temp copy; never on scenarios/_base). Usage from a scenario.yaml:

  mutations:
    - {op: tag, league: HH, player: Travis Kelce, tag: O}

or from the shell, to see an operator's effect on a scratch copy:
  python3 scenarios/mutate.py <root> '{"op": "tag", "league": "HH", "player": "X", "tag": "O"}'

Operators and their EXPECTED effect on the engine (doctrine, RUNBOOK):
  tag               set a designation on the newest snapshot. OUT starter -> a firm lineup
                    change if a healthy bench player fits (sanity 1/2); never a drop reason.
  set_slot          move a player to a slot on the newest snapshot.
  add_player        add a row to a roster (newest snapshot).
  remove_player     remove a row (newest snapshot): frees a spot -> an open-spot add.
  rename_def        rename a DEF row (to its city) -> keyed by team (C6), never offered as free.
  others_pulled     set others_pulled N hours before now -> G1 WARN (>24h) / BLOCK (BSB, before
                    the Wednesday run); 30h -> add/drop STALE.
  pulled            set the snapshot's own pull time N hours before now.
  rival_add         append a rival Add to the transactions log after the snapshot -> the
                    reconcile puts him on that roster: never offered (G1).
  txn               append any transactions-log row.
  clock_past_kickoff  pin the clock N minutes after a team's kickoff (returns the new now):
                    locked players are never proposed in or out.
  bye               remove a team's game from week W+1 look-ahead lines (and espn_games if W+1).
  sleeper           scale/override a player's Sleeper line to `pts` (projected points).
  sleeper_add       add a free agent with a synthetic line (pts) to sleeper_off.
  usage             write/overwrite a usage row (snaps share, targets) for week W-1 (and W-2 with both=true).
  roles             add/replace a roles.json entry: {list: add_yes|drop_ok|hold|..., player, entry}.
  drop_owner        delete one manager's rows from the newest snapshot (a missing team page) -> C4 REFUSE.
  kalshi            write a kalshi.csv (rows given inline) — e.g. last week's ladders or an in-game ladder.
  props             write an espn_props.csv with given event ids (C10).
  file              write a file verbatim (path relative to data/).
  snapshot_prev     write an OLDER snapshot copy with edits (history: recently dropped/added).
"""
import os, sys, json, csv, glob, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

def _latest(root, lg):
    fs = sorted(glob.glob(os.path.join(root, 'data', 'state', lg, '*.json')))
    return fs[-1]

def _edit_snap(root, lg, fn, path=None):
    p = path or _latest(root, lg); j = json.load(open(p)); fn(j); json.dump(j, open(p, 'w'), indent=0)

def _me(lg):
    from lib.leagues import ALL
    return ALL[lg].name

def _now(ctx):
    from lib import ts as T, clock as C
    return T.parse_ts(ctx['now'], 'legacy', now=dt.datetime.now(C.ET))

def _iso_utc(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec='seconds')

def _csv_rw(p, fn, fields=None):
    rows = list(csv.DictReader(open(p))) if os.path.exists(p) else []
    flds = fields or (list(rows[0].keys()) if rows else None)
    rows = fn(rows)
    with open(p, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=flds); w.writeheader(); w.writerows(rows)

def apply(root, m, ctx):
    """Apply one mutation dict to the scenario root. ctx: {'now': iso, 'week': W} (may be updated)."""
    from lib.names import key
    op = m['op']; lg = m.get('league')
    if op == 'tag':
        def f(j):
            hit = [r for r in j['rows'] if key(r['player']) == key(m['player']) and (not m.get('owner') or r['owner'] == m['owner'])]
            assert hit, f"tag: {m['player']} not on a {lg} roster"
            for r in hit: r['designation'] = m['tag']
        _edit_snap(root, lg, f)
    elif op == 'set_slot':
        def f(j):
            hit = [r for r in j['rows'] if key(r['player']) == key(m['player']) and r['owner'] == m.get('owner', _me(lg))]
            assert hit, f"set_slot: {m['player']}"
            for r in hit: r['slot'] = m['slot']
        _edit_snap(root, lg, f)
    elif op == 'add_player':
        def f(j):
            j['rows'].append(dict(owner=m.get('owner', _me(lg)), manager=m.get('owner', _me(lg)), slot=m.get('slot', 'BN'),
                                  player=m['player'], pos=m['pos'], nfl=m['nfl'], designation=m.get('tag', 'none')))
        _edit_snap(root, lg, f)
    elif op == 'remove_player':
        def f(j):
            n = len(j['rows'])
            j['rows'] = [r for r in j['rows'] if not (key(r['player']) == key(m['player']) and r['owner'] == m.get('owner', _me(lg)))]
            assert len(j['rows']) < n, f"remove_player: {m['player']}"
        _edit_snap(root, lg, f)
    elif op == 'rename_def':
        def f(j):
            hit = [r for r in j['rows'] if r['pos'] == 'DEF' and key(r['player']) == key(m['player'])]
            assert hit, f"rename_def: {m['player']}"
            for r in hit: r['player'] = m['to']
        _edit_snap(root, lg, f)
    elif op in ('others_pulled', 'pulled'):
        t = _iso_utc(_now(ctx) - dt.timedelta(hours=float(m['hours'])))
        def f(j): j['others_pulled' if op == 'others_pulled' else 'pulled'] = t
        _edit_snap(root, lg, f)
    elif op in ('rival_add', 'txn'):
        p = os.path.join(root, 'data', f'{lg.lower()}_transactions.csv')
        t = m.get('at') or (_now(ctx) - dt.timedelta(hours=float(m.get('hours_ago', 1)))).strftime('%Y-%m-%d %H:%M')
        row = dict(datetime=t, team=m['team'], action=m.get('action', 'Add'), player=m['player'], pos=m.get('pos', ''),
                   nfl=m.get('nfl', ''), bid=m.get('bid', ''), note=m.get('note', 'Free Agent'))
        _csv_rw(p, lambda rows: [row] + rows, fields=['datetime', 'team', 'action', 'player', 'pos', 'nfl', 'bid', 'note'])
    elif op == 'clock_past_kickoff':
        from lib import ts as T, clock as C
        rows = list(csv.DictReader(open(os.path.join(root, 'data', 'espn_games.csv'))))
        g = next(r for r in rows if m['team'] in (r['away'], r['home']))
        k = T.parse_ts(g['kickoff'], 'espn')
        ctx['now'] = (k + dt.timedelta(minutes=float(m.get('minutes', 20)))).astimezone(C.ET).isoformat(timespec='minutes')
    elif op == 'bye':
        w = int(m.get('week', ctx['week'] + 1))
        p = os.path.join(root, 'data', 'lines_wk3_9.csv' if w <= 9 else 'lines_wk10_18.csv')
        _csv_rw(p, lambda rows: [r for r in rows if not (r['week'] == str(w) and m['team'] in (r['away'], r['home']))])
    elif op in ('sleeper', 'sleeper_add'):
        p = os.path.join(root, 'data', f"sleeper_off_wk{ctx['week']}.csv")
        def f(rows):
            hit = [r for r in rows if key(r['player']) == key(m['player'])]
            if op == 'sleeper_add' and not hit:
                tmpl = dict.fromkeys(rows[0].keys(), '')
                tmpl.update(player=m['player'], team=m['nfl'], pos=m['pos'], opp=m.get('opp', ''))
                rows.append(tmpl); hit = [tmpl]
            assert hit, f"sleeper: {m['player']}"
            for r in hit:
                pts = float(m['pts']); old = float(r.get('pts_ppr') or 0)
                num = [c for c in r if c not in ('player', 'team', 'pos', 'opp', 'pts_ppr') and r[c] not in ('', None)]
                if old > 0 and num:
                    for c in num: r[c] = f'{float(r[c]) * pts / old:.3f}'
                else:                                  # synthetic line: receptions/yards/TD (or pass for QB)
                    for c in r:
                        if c not in ('player', 'team', 'pos', 'opp'): r[c] = ''
                    if r['pos'] == 'QB': r.update(pass_att=f'{pts*1.6:.2f}', pass_cmp=f'{pts:.2f}', pass_yd=f'{pts*10:.2f}', pass_td=f'{pts/12:.3f}')
                    elif r['pos'] in ('K',): r.update(fgm=f'{pts/4.5:.3f}', xpm=f'{pts/4.5:.3f}')
                    elif r['pos'] == 'DEF': r.update(sack=f'{pts/3:.3f}', int=f'{pts/10:.3f}', pts_allow='20')
                    else: r.update(rec=f'{pts*0.25:.3f}', rec_tgt=f'{pts*0.35:.3f}', rec_yd=f'{pts*5:.2f}', rec_td=f'{pts*0.25/6:.3f}')
                r['pts_ppr'] = f'{pts:.2f}'
            return rows
        _csv_rw(p, f)
    elif op == 'usage':
        weeks = [ctx['week'] - 1] + ([ctx['week'] - 2] if m.get('both') else [])
        for w in weeks:
            p = os.path.join(root, 'data', f"usage_wk{w}_{m['pos']}.csv")
            fn_, ln_ = m['player'].split(' ', 1)
            def f(rows):
                rows = [r for r in rows if key(f"{r['first_name']} {r['last_name']}") != key(m['player'])]
                r = dict.fromkeys(rows[0].keys(), '') if rows else {}
                r.update(player_id=m.get('pid', '9' + str(abs(hash(m['player'])) % 10**6)), first_name=fn_, last_name=ln_, team=m['nfl'], pos=m['pos'],
                         gp='1.0', gs=str(m.get('gs', 1.0)), off_snp=str(m.get('snaps', 60)), tm_off_snp=str(m.get('team_snaps', 65)),
                         rec=str(m.get('rec', 6)), rec_tgt=str(m.get('targets', 8)), rec_yd=str(m.get('yds', 70)),
                         rec_air_yd=str(m.get('air', 80)), rush_att=str(m.get('rush', '')), pts_ppr=str(m.get('pts', 14)))
                return [r] + rows
            _csv_rw(p, f)
    elif op == 'roles':
        p = os.path.join(root, 'data', 'roles.json'); R = json.load(open(p))
        lst = R.setdefault(m['list'], {})
        if isinstance(lst, dict): lst[key(m['player'])] = m['entry']
        else: lst.append(dict(m['entry'], player=m['player']))
        json.dump(R, open(p, 'w'), indent=1)
    elif op == 'drop_owner':
        def f(j):
            n = len(j['rows']); j['rows'] = [r for r in j['rows'] if r['owner'] != m['owner']]
            assert len(j['rows']) < n, f"drop_owner: {m['owner']}"
        _edit_snap(root, lg, f)
    elif op in ('kalshi', 'props', 'file'):
        rel = {'kalshi': 'kalshi.csv', 'props': 'espn_props.csv'}.get(op) or m['path']
        p = os.path.join(root, 'data', rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w').write(m['content'])
    elif op == 'snapshot_prev':
        src = _latest(root, lg); j = json.load(open(src))
        t = _now(ctx) - dt.timedelta(hours=float(m['hours_ago']))
        from lib import clock as C
        p = os.path.join(root, 'data', 'state', lg, t.astimezone(C.ET).strftime('%Y-%m-%dT%H%M') + '.json')
        for a in m.get('add', []):
            j['rows'].append(dict(owner=_me(lg), manager=_me(lg), slot='BN', player=a['player'], pos=a['pos'], nfl=a['nfl'], designation='none'))
        j['pulled'] = j['others_pulled'] = _iso_utc(t)
        json.dump(j, open(p, 'w'), indent=0)
    else:
        raise ValueError(f'unknown mutation op {op!r}')
    return ctx

if __name__ == '__main__':
    root = sys.argv[1]; m = json.loads(sys.argv[2])
    ctx = dict(now=os.environ.get('FF_NOW', '2026-10-04T09:00-04:00'), week=int(os.environ.get('FF_WEEK', 4)))
    print(apply(root, m, ctx))
