#!/usr/bin/env python3
"""Build the input-contract fixtures from REAL inputs (run once; the output is committed).

    python3 test/fixtures/contract/make_fixtures.py [ENGINE_ROOT] [PUMP_REPO]

ENGINE_ROOT (default: this checkout) supplies data/ as it stood at the 2026-10-04
baseline commit: the 09-29 frozen-page snapshot (Coker on The STRIB Club, the
'--empty--' row), the 10-01 'Minnesota' defense, the 09-30 4:12 am waiver log, the
week-2 DraftKings props, the Sunday 09-27 2:20 pm Kalshi archive (the in-game
ladders), the 10-04 pulls. PUMP_REPO (default /home/claude/ffdata_repo, read-only)
supplies its git history: pump commit 28e1a7f (2026-09-29T06:49Z) — pulled.txt
'week 3' and the HH roster CSV whose '--empty--' row carries '3%' in proj_pts.

Each fixture is a minimal root: <name>/data/... — test/test_contract.py runs
contract.check(root=<name>, now=..., week=...) on it, or on a copy it mutates.
"""
import csv, io, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(HERE, '..', '..', '..'))
PUMP = sys.argv[2] if len(sys.argv) > 2 else '/home/claude/ffdata_repo'
BASE = '301546c'      # the baseline commit of the engine (Sun Oct 4, 8:35 am ET)

def eng(rel):
    """A file of data/ at the baseline commit (never the working tree, which runs change)."""
    return subprocess.run(['git', '-C', ENGINE, 'show', f'{BASE}:data/{rel}'], capture_output=True, check=True).stdout

def pump(commit, rel):
    return subprocess.run(['git', '-C', PUMP, 'show', f'{commit}:data/{rel}'], capture_output=True, check=True).stdout

def put(fx, rel, data):
    p = os.path.join(HERE, fx, 'data', rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'wb').write(data if isinstance(data, bytes) else data.encode())

def csv_rows(b):
    r = csv.DictReader(io.StringIO(b.decode()))
    return r.fieldnames, list(r)

def csv_bytes(fields, rows):
    s = io.StringIO(); w = csv.DictWriter(s, fieldnames=fields, lineterminator='\n'); w.writeheader(); w.writerows(rows); return s.getvalue()

def keep_events(b, events):
    f, rows = csv_rows(b)
    return csv_bytes(f, [r for r in rows if r['event'].split('-', 1)[1] in events])

def main():
    for d in os.listdir(HERE):
        if os.path.isdir(os.path.join(HERE, d)): shutil.rmtree(os.path.join(HERE, d))
    off4 = csv_rows(eng('sleeper_off_wk4.csv')); off4_150 = csv_bytes(off4[0], off4[1][:150])
    snapB = eng('state/BSB/2026-10-04T0748.json'); snapH = eng('state/HH/2026-10-04T0748.json')

    # C1 — Tue 09-29 07:30 ET: the calendar rolled to week 4 at 7 am, the pump pulled at
    # 2:49 am with week-3 pages (pump commit 28e1a7f), week-4 Sleeper is on disk.
    put('C1', 'yahoo/pulled.txt', pump('28e1a7f', 'yahoo/pulled.txt'))
    put('C1', 'sleeper_off_wk4.csv', off4_150)
    put('C1', 'state/BSB/2026-09-29T0810.json', eng('state/BSB/2026-09-29T0810.json'))
    put('C1', 'state/HH/2026-09-29T0810.json', eng('state/HH/2026-09-29T0810.json'))

    # C3/C2/C10/C9/C11 share a clean 10-04 base: snapshots, Sleeper, schedule, Kalshi (3 games)
    games3 = ('26OCT04NEBUF', '26OCT04MIAMIN', '26OCT05ATLNO')
    for fx in ('base',):
        put(fx, 'state/BSB/2026-10-04T0748.json', snapB); put(fx, 'state/HH/2026-10-04T0748.json', snapH)
        put(fx, 'sleeper_off_wk4.csv', off4_150)
        put(fx, 'espn_games.csv', eng('espn_games.csv'))
        put(fx, 'kalshi.csv', keep_events(eng('kalshi.csv'), games3))
        put(fx, 'kalshi_archive/kalshi_2026-10-04T0158Z.csv', keep_events(eng('kalshi_archive/kalshi_2026-10-04T0158Z.csv'), games3))
        put(fx, 'bsb_transactions.csv', eng('bsb_transactions.csv')); put(fx, 'hh_transactions.csv', eng('hh_transactions.csv'))
        put(fx, 'pulls/ffdata_pull.md', eng('pulls/ffdata_pull.md'))
        put(fx, 'roles.json', eng('roles.json'))
        put(fx, 'yahoo/BSB_rosters.csv', pump('e9eaa1f', 'yahoo/BSB_rosters.csv'))
        put(fx, 'matchups.json', eng('matchups.json'))

    # C4 — (a) the real '--empty--' row (HH, 09-29 snapshot); (b) the 10-04 BSB snapshot
    # with one team removed (a missing team page)
    put('C4_empty', 'state/HH/2026-09-29T0810.json', eng('state/HH/2026-09-29T0810.json'))
    j = json.loads(snapB); j['rows'] = [r for r in j['rows'] if r['owner'] != 'Bad News Bears']
    put('C4_team_missing', 'state/BSB/2026-10-04T0748.json', json.dumps(j, indent=0))

    # C5 — the 09-29 frozen pages: The STRIB Club's page still shows Jalen Coker (real
    # snapshot), Maker's Mark's fresh page shows him added (synthesized), the log has the
    # add but not STRIB's drop (the page the log came from was behind)
    j = json.loads(eng('state/HH/2026-09-29T0810.json'))
    j['rows'] = [r for r in j['rows'] if r['player'] != '--empty--']
    j['rows'].append(dict(owner="Maker's Mark", manager="Maker's Mark", slot='BN', player='Jalen Coker', pos='WR', nfl='CAR', designation='Q'))
    put('C5', 'state/HH/2026-09-29T0810.json', json.dumps(j, indent=0))
    f, rows = csv_rows(eng('hh_transactions.csv'))
    add = dict(datetime='2026-09-28 21:44', team="Maker's Mark", action='Add', player='Jalen Coker', pos='WR', nfl='CAR', bid='', note='Free Agent')
    put('C5', 'hh_transactions_full.csv', csv_bytes(f, [add] + rows))                                 # STRIB's real 11:29 drop is in here
    put('C5', 'hh_transactions.csv', csv_bytes(f, [add] + [r for r in rows if not (r['player'] == 'Jalen Coker' and r['action'] == 'Drop')]))

    # C6 — T-rex's Vikings as Yahoo printed them on 10-01 ('Minnesota'), real row; the
    # fixture snapshot drops the nfl code (a city-only render)
    j = json.loads(eng('state/HH/2026-10-01T1853.json'))
    for r in j['rows']:
        if r['player'] == 'Minnesota': r['nfl'] = ''
    put('C6', 'state/HH/2026-10-01T1853.json', json.dumps(j, indent=0))

    # C8 — Sunday 09-27, 2:20 pm ET: the real in-game Kalshi pull (Treadwell '135 rec yds'),
    # with the schedule the runner's ESPN returned (one week-3 row: ATL@GB)
    put('C8', 'kalshi.csv', keep_events(eng('kalshi_archive/kalshi_2026-09-27T1820Z.csv'), ('26SEP27CARCLE', '26SEP27ARISF', '26SEP28LARDEN')))
    f, rows = csv_rows(eng('lines_wk3_9.csv'))
    wk3 = [r for r in rows if r['week'] == '3']
    def espn(rs): return csv_bytes(['event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under', 'status'],
                                   [dict(event_id=r['event_id'], away=r['away'], home=r['home'], kickoff=r['kickoff'], spread_team=r['favorite'],
                                         spread=r['spread'], over_under=r['over_under'], status='') for r in rs])
    put('C8', 'espn_games.csv', espn([r for r in wk3 if r['home'] == 'GB']))
    put('C8', 'espn_games_full.csv', espn(wk3))
    # the 09-29 06:48Z roster page shows Coker's game text; the fixture puts him mid-game
    f, rows = csv_rows(pump('28e1a7f', 'yahoo/HH_rosters.csv'))
    rows = [dict(r, game='Q2 5:12, 7-3 @ Cle') for r in rows if r['player'] == 'Jalen Coker']
    put('C8', 'yahoo_live_rows.csv', csv_bytes(f, rows))

    # C10 — the week-2 DraftKings props that the runner applied in week 4 (10-04)
    put('C10', 'espn_props.csv', eng('espn_props.csv'))
    put('C10', 'espn_games.csv', eng('espn_games.csv'))

    # C12/C13 — the BSB log with the 09-30 4:12 am waiver run
    put('C13', 'bsb_transactions.csv', eng('bsb_transactions.csv'))

    # C14 — a real matchup page (BSB week 3: 147.40 vs 114.65, reconciles)
    put('C14', 'yahoo/BSB_matchup_wk3.csv', pump('e9eaa1f', 'yahoo/BSB_matchup_wk3.csv'))

    # C15 — the real pump roster CSV with the misaligned '--empty--' row ('3%' in proj_pts)
    put('C15', 'yahoo/HH_rosters.csv', pump('28e1a7f', 'yahoo/HH_rosters.csv'))

    # C16/C17 — the registry and ledger as they stood
    put('C16', 'roles.json', eng('roles.json'))
    put('C16', 'ledger.json', json.dumps(json.loads(eng('ledger.json'))[-20:], indent=1))
    print('fixtures written under', HERE)

if __name__ == '__main__':
    main()
