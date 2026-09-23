#!/usr/bin/env python3
"""Split the big pulls into small files a fetch tool can read whole (each well
under 10 KB), and write index.txt listing every file's raw URL. Fetching
index.txt once is what makes every listed URL readable afterwards.

usage: python3 digest.py DATA_DIR REPO_SLUG BRANCH
  e.g. python3 digest.py data ctgarret/ffdata main
"""
import csv, os, sys, glob, datetime as dt
from collections import defaultdict

def main():
    data, slug, branch = sys.argv[1], sys.argv[2], sys.argv[3]
    raw = f'https://raw.githubusercontent.com/{slug}/{branch}/{data}/'
    files = []
    # ---- Kalshi: one compact file per event (ticker,yes_bid,yes_ask,last)
    kd = os.path.join(data, 'kalshi'); os.makedirs(kd, exist_ok=True)
    for f in glob.glob(os.path.join(kd, '*.csv')): os.remove(f)
    src = os.path.join(data, 'kalshi.csv')
    if os.path.exists(src):
        by_ev = defaultdict(list)
        for r in csv.DictReader(open(src)): by_ev[r['event']].append(r)
        for ev, rows in sorted(by_ev.items()):
            p = os.path.join(kd, ev + '.csv')
            with open(p, 'w', newline='') as fh:
                w = csv.writer(fh); w.writerow(['ticker', 'yes_bid', 'yes_ask', 'last_price', 'volume'])
                for r in rows: w.writerow([r['ticker'], r['yes_bid'], r['yes_ask'], r['last_price'], r['volume']])
            files.append(p)
    # ---- Sleeper stats/projections are already per position; large ones get split in halves
    for p in sorted(glob.glob(os.path.join(data, 'sleeper', '*.csv'))):
        if os.path.getsize(p) <= 9000:
            files.append(p); continue
        rows = list(csv.DictReader(open(p))); n = max(1, len(rows) // (os.path.getsize(p) // 9000 + 1))
        base = p[:-4]
        for i in range(0, len(rows), n):
            q = f'{base}_part{i // n + 1}.csv'
            with open(q, 'w', newline='') as fh:
                w = csv.DictWriter(fh, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows[i:i + n])
            files.append(q)
    for name in ('espn_games.csv',):
        if os.path.exists(os.path.join(data, name)): files.append(os.path.join(data, name))
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec='minutes')
    with open(os.path.join(data, 'index.txt'), 'w') as fh:
        fh.write(f'# ffdata index — written {stamp}\n')
        for p in files:
            rel = os.path.relpath(p, data).replace(os.sep, '/')
            fh.write(raw + rel + f'  ({os.path.getsize(p)} bytes)\n')
    print(f'{len(files)} files indexed at {stamp}')

if __name__ == '__main__':
    main()
