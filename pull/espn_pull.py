#!/usr/bin/env python3
"""Pull the current NFL week's game lines from ESPN's public scoreboard into the
CSV lib/market.py reads:
  event_id,away,home,kickoff,spread_team,spread,over_under,over_odds,under_odds,away_ml,home_ml
Values are copied from the odds object verbatim; a missing field is left blank,
never estimated. Standard library only.

usage: python3 espn_pull.py OUT.csv [--week N]
"""
import csv, json, sys, time, urllib.request, urllib.parse

URL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'

ALT = ['https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
       'https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
       'https://cdn.espn.com/core/nfl/scoreboard?xhr=1']
ERRORS = []

def fetch(params):
    for base in ALT:
        for attempt in range(3):
            try:
                sep = '&' if '?' in base else '?'
                req = urllib.request.Request(base + (sep + urllib.parse.urlencode(params) if params else ''),
                                             headers={'User-Agent': UA, 'Accept': 'application/json', 'Accept-Language': 'en-US,en;q=0.9'})
                with urllib.request.urlopen(req, timeout=30) as r:
                    j = json.loads(r.read().decode())
                # the cdn shape nests the scoreboard under content.sbData
                if 'events' not in j and isinstance(j.get('content'), dict):
                    j = j['content'].get('sbData') or j['content']
                if j.get('events'): return j
                ERRORS.append(f'{base}: 200 but no events')
                break
            except Exception as e:
                ERRORS.append(f'{base}: {e!r}'); time.sleep(2.0 * (attempt + 1))
    return {}
FIELDS = ['event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under',
          'over_odds', 'under_odds', 'away_ml', 'home_ml', 'status', 'away_score', 'home_score']

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    params = {'seasontype': '2', 'dates': '2026'}
    if '--week' in sys.argv: params['week'] = sys.argv[sys.argv.index('--week') + 1]
    j = fetch(params)
    if not j.get('events'): j = fetch({})          # second shape: ESPN's own current-week default
    if not j.get('events'):
        with open(sys.argv[1] + '.error.txt', 'w') as fh: fh.write('\n'.join(ERRORS) + '\n')
        print('ESPN: no events from any endpoint; errors written beside the output'); sys.exit(2)
    rows = []
    for ev in j.get('events', []):
        comp = ev['competitions'][0]
        teams = {c['homeAway']: c for c in comp['competitors']}
        away, home = teams['away'], teams['home']
        odds = (comp.get('odds') or [{}])[0]
        details = odds.get('details', '') or ''
        spread_team, spread = '', ''
        if details and details.upper() != 'EVEN':
            parts = details.split()
            if len(parts) == 2: spread_team, spread = parts[0], parts[1]
        ao, ho = odds.get('awayTeamOdds') or {}, odds.get('homeTeamOdds') or {}
        rows.append(dict(event_id=ev['id'], away=away['team']['abbreviation'], home=home['team']['abbreviation'],
                         kickoff=ev.get('date', ''), spread_team=spread_team, spread=spread,
                         over_under=odds.get('overUnder', ''), over_odds=odds.get('overOdds', ''),
                         under_odds=odds.get('underOdds', ''), away_ml=ao.get('moneyLine', ''), home_ml=ho.get('moneyLine', ''),
                         status=ev.get('status', {}).get('type', {}).get('name', ''),
                         away_score=away.get('score', ''), home_score=home.get('score', '')))
    with open(sys.argv[1], 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print(f"week {j.get('week', {}).get('number')}: {len(rows)} games -> {sys.argv[1]}")
    if len(rows) < 10: print('PARTIAL — fewer than 10 games'); sys.exit(2)

if __name__ == '__main__':
    main()
