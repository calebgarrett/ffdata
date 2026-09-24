#!/usr/bin/env python3
"""Pull the two Yahoo leagues' public pages so every roster, tag, transaction
and matchup score refreshes with the pump instead of a pasted link.

Logged-out Yahoo serves a league's team pages, transactions and matchups when
the league is viewable (both of these are). A unique query string defeats
Yahoo's stale cache. Nothing is parsed here on the first pass: the raw HTML of
one team page, one matchup page and one transactions page per league is saved
so the parser can be written against the real markup; the rest are fetched to
confirm reachability and summarised (status, bytes, a title) in reach.txt.

usage: python3 yahoo_pull.py OUT_DIR [--week N] [--all]
  --all   save the raw HTML of EVERY page (large; only when asked)
"""
import os, re, sys, time, datetime as dt, urllib.request, urllib.parse, urllib.error

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
        except Exception as e:
            time.sleep(2.0 * (attempt + 1)); last = e
    return 0, ''

def title_of(html):
    m = re.search(r'<title>(.*?)</title>', html, re.S)
    return re.sub(r'\s+', ' ', m.group(1)).strip()[:120] if m else ''

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    out = sys.argv[1]; os.makedirs(os.path.join(out, 'raw'), exist_ok=True)
    week = int(sys.argv[sys.argv.index('--week') + 1]) if '--week' in sys.argv else nfl_week()
    save_all = '--all' in sys.argv
    lines = [f'# yahoo reach check {dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")} week {week}']
    for lg, cfg in LEAGUES.items():
        pages = [(f'{lg}_team{t}', f'{BASE}/{cfg["id"]}/{t}') for t in range(1, cfg['teams'] + 1)]
        pages += [(f'{lg}_matchup_wk{week}', f'{BASE}/{cfg["id"]}/matchup?week={week}&mid1={cfg["mine"]}'),
                  (f'{lg}_transactions', f'{BASE}/{cfg["id"]}/transactions')]
        for name, url in pages:
            status, html = get(url)
            lines.append(f'{name}\t{status}\t{len(html)}\t{title_of(html)}')
            keep = save_all or name in (f'{lg}_team{cfg["mine"]}', f'{lg}_matchup_wk{week}', f'{lg}_transactions')
            if keep and html:
                with open(os.path.join(out, 'raw', name + '.html'), 'w') as fh: fh.write(html)
            time.sleep(0.6)
    with open(os.path.join(out, 'reach.txt'), 'w') as fh: fh.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))

if __name__ == '__main__':
    main()
