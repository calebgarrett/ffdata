#!/usr/bin/env python3
"""Pull the current NFL week's game lines from ESPN's public scoreboard into the
CSV lib/market.py reads:
  event_id,away,home,kickoff,spread_team,spread,over_under,over_odds,under_odds,away_ml,home_ml
Values are copied from the odds object verbatim; a missing field is left blank,
never estimated. Standard library only.

usage: python3 espn_pull.py OUT.csv [--week N]
"""
import csv, json, sys, urllib.request, urllib.parse

URL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
FIELDS = ['event_id', 'away', 'home', 'kickoff', 'spread_team', 'spread', 'over_under',
          'over_odds', 'under_odds', 'away_ml', 'home_ml', 'status', 'away_score', 'home_score']

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    params = {'seasontype': '2'}
    if '--week' in sys.argv: params['week'] = sys.argv[sys.argv.index('--week') + 1]
    req = urllib.request.Request(URL + '?' + urllib.parse.urlencode(params), headers={'User-Agent': 'ff-espn-pull/1'})
    j = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
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
