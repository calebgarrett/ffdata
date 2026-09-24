#!/usr/bin/env python3
"""Pull the two Yahoo leagues' public pages and parse them into CSVs, so every
roster, injury tag, transaction and matchup score refreshes with the pump.

Logged-out Yahoo serves a viewable league's team pages, transactions and
matchups; a unique query string defeats its stale cache. Parsing lives in
yahoo_parse.py (same directory).

Writes under OUT_DIR:
  {LG}_rosters.csv          every team: team_id,owner,record,rank,slot,player,pid,nfl,pos,status,game,bye,fan_pts,proj_pts
  {LG}_matchup_wk{W}.csv    my matchup: side,team_id,owner,record,rank,total,proj,slot,player,pid,nfl,pos,status,game,fan_pts,proj_pts
  {LG}_transactions.csv     ts,team,team_id,player,pid,nfl,pos,status,kind,action
  pulled.txt                ISO time of this pull and a per-page status line
  raw/*.html                only with --all (large)

usage: python3 yahoo_pull.py OUT_DIR [--week N] [--all]
"""
import os, re, sys, csv, time, glob, datetime as dt, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yahoo_parse as Y

LEAGUES = {'BSB': dict(id=156919, teams=12, mine=7),
           'HH':  dict(id=824489, teams=10, mine=6)}
BASE = 'https://football.fantasysports.yahoo.com/f1'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
WEEK1_TUESDAY = dt.datetime(2026, 9, 8, 11, 0, tzinfo=dt.timezone.utc)

def nfl_week(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(1, min(18, (now - WEEK1_TUESDAY).days // 7 + 1))

def get(url):
    cb = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S%f')
    url = url + ('&' if '?' in url else '?') + 'cachebust=' + cb
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml',
                                               'Accept-Language': 'en-US,en;q=0.9'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            return e.code, ''
        except Exception:
            time.sleep(2.0 * (attempt + 1))
    return 0, ''

def write(path, rows, fields):
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    week = int(sys.argv[sys.argv.index('--week') + 1]) if '--week' in sys.argv else nfl_week()
    save_all = '--all' in sys.argv
    if not save_all:
        for f in glob.glob(os.path.join(out, 'raw', '*.html')): os.remove(f)
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    status = [f'# yahoo pull {stamp} week {week}']
    R_FIELDS = ['team_id', 'owner', 'record', 'rank', 'slot', 'player', 'pid', 'nfl', 'pos', 'status', 'game', 'bye', 'fan_pts', 'proj_pts', 'pulled_at']
    M_FIELDS = ['side', 'team_id', 'owner', 'record', 'rank', 'total', 'proj', 'slot', 'player', 'pid', 'nfl', 'pos', 'status', 'game', 'fan_pts', 'proj_pts', 'pulled_at']
    T_FIELDS = ['ts', 'team', 'team_id', 'player', 'pid', 'nfl', 'pos', 'status', 'kind', 'action', 'pulled_at']
    bad = 0
    for lg, cfg in LEAGUES.items():
        rosters = []
        for t in range(1, cfg['teams'] + 1):
            st, html = get(f'{BASE}/{cfg["id"]}/{t}')
            owner, record, rank, rows = Y.parse_team(html) if html else ('', '', '', [])
            status.append(f'{lg}_team{t}\t{st}\t{len(html)}\t{owner}\t{len(rows)} rows')
            if not rows: bad += 1
            for r in rows:
                rosters.append(dict(r, team_id=str(t), owner=owner, record=record, rank=rank, pulled_at=stamp))
            if save_all and html:
                os.makedirs(os.path.join(out, 'raw'), exist_ok=True)
                open(os.path.join(out, 'raw', f'{lg}_team{t}.html'), 'w').write(html)
            time.sleep(0.6)
        write(os.path.join(out, f'{lg}_rosters.csv'), rosters, R_FIELDS)
        st, html = get(f'{BASE}/{cfg["id"]}/matchup?week={week}&mid1={cfg["mine"]}')
        teams = Y.parse_matchup(html) if html else []
        mrows = []
        for tm in teams:
            for r in tm['rows']:
                mrows.append(dict(r, side=tm['side'], team_id=tm['team_id'], owner=tm['owner'], record=tm['record'],
                                  rank=tm['rank'], total=tm['total'], proj=tm['proj'], pulled_at=stamp))
        status.append(f'{lg}_matchup_wk{week}\t{st}\t{len(html)}\t' + ' vs '.join(t['owner'] for t in teams) + f'\t{len(mrows)} rows')
        if mrows: write(os.path.join(out, f'{lg}_matchup_wk{week}.csv'), mrows, M_FIELDS)
        else: bad += 1
        time.sleep(0.6)
        st, html = get(f'{BASE}/{cfg["id"]}/transactions')
        trs = Y.parse_transactions(html) if html else []
        status.append(f'{lg}_transactions\t{st}\t{len(html)}\t{len(trs)} rows')
        if trs: write(os.path.join(out, f'{lg}_transactions.csv'), [dict(x, pulled_at=stamp) for x in trs], T_FIELDS)
        time.sleep(0.6)
    with open(os.path.join(out, 'pulled.txt'), 'w') as fh: fh.write('\n'.join(status) + '\n')
    print('\n'.join(status))
    if bad: print(f'PARTIAL — {bad} page(s) gave no rows'); sys.exit(2)

if __name__ == '__main__':
    main()
