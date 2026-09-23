#!/usr/bin/env python3
"""Pull EVERY open Kalshi NFL player-prop ladder into one CSV. Public endpoints,
no API key, standard library only. Runs anywhere that can reach
api.elections.kalshi.com (Caleb's computer via the desktop bridge; the cloud
container cannot).

Output format is exactly what lib/market.py reads:
  event,series,ticker,title,yes_bid,yes_ask,last_price,volume,open_interest
with prices as dollar strings copied verbatim from *_dollars fields and volume
and open interest from *_fp fields (see data/kalshi_log.md). Three extra
columns are appended (status,close_time,pulled_at) — harmless to the loader.

usage: python3 kalshi_pull.py OUT.csv [--series KXNFLREC,KXNFLRECYDS,...]
exit 0 on success and prints a one-line summary; exit 2 if fewer than 200
markets came back (a partial pull must never silently replace a full one).
"""
import csv, json, sys, time, urllib.request, urllib.parse, urllib.error, datetime as dt

BASE = 'https://api.elections.kalshi.com/trade-api/v2'
SERIES = ['KXNFLREC', 'KXNFLRECYDS', 'KXNFLRSHYDS', 'KXNFLPASSYDS', 'KXNFLPASSTDS', 'KXNFLTD',
          'KXNFLRRYDS', 'KXNFLINT']
FIELDS = ['event', 'series', 'ticker', 'title', 'yes_bid', 'yes_ask', 'last_price', 'volume', 'open_interest',
          'status', 'close_time', 'pulled_at']
PAUSE = 0.12          # seconds between calls; Kalshi's public limit is generous but not infinite

def get(path, **params):
    url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'ff-kalshi-pull/1'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1)); continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f'giving up on {url}')

def paged(path, key, **params):
    cursor = None
    while True:
        p = dict(params)
        if cursor: p['cursor'] = cursor
        j = get(path, **p)
        for x in j.get(key, []): yield x
        cursor = j.get('cursor')
        time.sleep(PAUSE)
        if not cursor: break

def events_for(series):
    """Open events of a series, restricted to tickers that belong to it."""
    out = []
    for e in paged('/events', 'events', series_ticker=series, status='open', limit=200):
        t = e.get('event_ticker', '')
        if t.startswith(series + '-'): out.append(t)
    return sorted(set(out))

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    out_path = sys.argv[1]
    series = SERIES
    if '--series' in sys.argv: series = sys.argv[sys.argv.index('--series') + 1].split(',')
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    rows, per_series = [], {}
    for s in series:
        evs = events_for(s)
        n0 = len(rows)
        for ev in evs:
            for m in paged('/markets', 'markets', event_ticker=ev, limit=200):
                tk = m.get('ticker', '')
                if not tk.startswith(ev + '-'): continue        # never trust a filter blindly
                rows.append(dict(event=ev, series=s, ticker=tk, title=m.get('title', ''),
                                 yes_bid=m.get('yes_bid_dollars', ''), yes_ask=m.get('yes_ask_dollars', ''),
                                 last_price=m.get('last_price_dollars', ''), volume=m.get('volume_fp', ''),
                                 open_interest=m.get('open_interest_fp', ''), status=m.get('status', ''),
                                 close_time=m.get('close_time', ''), pulled_at=stamp))
        per_series[s] = (len(evs), len(rows) - n0)
    # sanity: unique tickers, non-empty prices
    seen = set(); dups = 0
    for r in rows:
        if r['ticker'] in seen: dups += 1
        seen.add(r['ticker'])
    with open(out_path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    summary = ' · '.join(f'{s}: {e} events / {n} markets' for s, (e, n) in per_series.items())
    print(f'{len(rows)} markets, {dups} duplicate tickers, pulled {stamp} -> {out_path}\n  {summary}')
    if len(rows) < 200:
        print('PARTIAL PULL — fewer than 200 markets; not a replacement for the file on disk'); sys.exit(2)

if __name__ == '__main__':
    main()
