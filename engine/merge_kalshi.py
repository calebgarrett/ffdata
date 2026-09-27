"""Merge one verbatim Kalshi page (CSV: ticker,title,yes_bid,yes_ask,last_price,volume,open_interest)
into data/kalshi.csv, replacing every existing row of the same event+series block.
usage: python3 merge_kalshi.py <page.csv> <EVENT e.g. KXNFLRECYDS-26SEP21NYGLAR>
"""
import csv, sys, os
D='/home/claude/bsb2/data/'
page, event = sys.argv[1], sys.argv[2]
series = event.split('-')[0]
new = []
for r in csv.DictReader(open(page)):
    t = r['ticker'].strip()
    if not t.startswith(event + '-'): continue
    new.append(dict(event=event, series=series, ticker=t, title=r['title'].strip(),
                    yes_bid=r['yes_bid'], yes_ask=r['yes_ask'], last_price=r['last_price'],
                    volume=r['volume'], open_interest=r['open_interest']))
rows = list(csv.DictReader(open(D + 'kalshi.csv')))
before = len(rows)
# replace per PLAYER block (ticker minus the strike), so a partial page never
# deletes a player the page did not reach
players = {t['ticker'].rsplit('-', 1)[0] for t in new}
keep = [r for r in rows if r['ticker'].rsplit('-', 1)[0] not in players]
merged = keep + new
w = csv.DictWriter(open(D + 'kalshi.csv', 'w', newline=''), fieldnames=rows[0].keys())
w.writeheader(); w.writerows(merged)
for f in ('kalshi.csv.fits.pkl',):
    p = D + f
    if os.path.exists(p): os.remove(p)
print(f'{event}: {len(players)} player ladders; replaced {before - len(keep)} rows with {len(new)} verbatim rows; file now {len(merged)} rows')
