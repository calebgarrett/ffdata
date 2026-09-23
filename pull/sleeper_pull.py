#!/usr/bin/env python3
"""Pull Sleeper's public NFL projections, weekly stats (usage + actuals) and
48-hour trending adds/drops for the current week. No key, standard library.

Writes, under OUT_DIR:
  sleeper_off_wk{W}.csv   offense projections   (exact format lib/project.py reads)
  sleeper_idp_wk{W}.csv   IDP projections       (exact format lib/project.py reads)
  stats_wk{W}_{POS}.csv   realized stats, one file per QB/RB/WR/TE/K/DEF
                          (usage columns lib/usage.py reads + scoring stats for actuals)
  trending.csv            player_id,count,first_name,last_name,team,pos,kind

usage: python3 sleeper_pull.py OUT_DIR [--week N] [--season 2026]
"""
import csv, json, os, sys, time, datetime as dt, urllib.request, urllib.parse

BASE = 'https://api.sleeper.app'
OFF = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']
IDP = ['DL', 'LB', 'DB']
WEEK1_TUESDAY = dt.datetime(2026, 9, 8, 11, 0, tzinfo=dt.timezone.utc)   # 07:00 ET

def nfl_week(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(1, min(18, (now - WEEK1_TUESDAY).days // 7 + 1))

def get(path, **params):
    url = BASE + path + ('?' + urllib.parse.urlencode(params, doseq=True) if params else '')
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ff-sleeper-pull/1'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f'giving up on {url}')

def name_of(o):
    p = o.get('player') or {}
    n = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    if (p.get('position') == 'DEF' or o.get('player_id', '').isalpha()) and not p.get('first_name'):
        n = p.get('last_name') or o.get('team') or o.get('player_id', '')
    return n

OFF_FIELDS = ['pass_att', 'pass_cmp', 'pass_inc', 'pass_yd', 'pass_td', 'pass_int', 'pass_sack', 'pass_fd',
              'rush_att', 'rush_yd', 'rush_td', 'rush_fd', 'rec', 'rec_tgt', 'rec_yd', 'rec_td', 'rec_fd', 'fum_lost']
IDP_FIELDS = ['solo', 'ast', 'sack', 'int', 'pd', 'tfl', 'ff', 'fr', 'def_td']
IDP_MAP = {'solo': 'idp_tkl_solo', 'ast': 'idp_tkl_ast', 'sack': 'idp_sack', 'int': 'idp_int', 'pd': 'idp_pass_def',
           'tfl': 'idp_tkl_loss', 'ff': 'idp_ff', 'fr': 'idp_fum_rec', 'def_td': 'idp_def_td'}
STAT_FIELDS = ['gp', 'gs', 'off_snp', 'tm_off_snp', 'pass_att', 'pass_cmp', 'pass_yd', 'pass_td', 'pass_int', 'pass_sack',
               'rush_att', 'rush_yd', 'rush_td', 'rec', 'rec_tgt', 'rec_yd', 'rec_td', 'rec_air_yd', 'rec_rz_tgt',
               'fum_lost', 'pass_2pt', 'rush_2pt', 'rec_2pt', 'rec_fd', 'rush_fd', 'pass_fd',
               'fgm', 'fga', 'xpm', 'xpa', 'fgm_0_19', 'fgm_20_29', 'fgm_30_39', 'fgm_40_49', 'fgm_50p',
               'pts_allow', 'sack', 'int', 'fum_rec', 'def_td', 'safe', 'blk_kick', 'pts_ppr', 'pts_std']

def g(st, k):
    v = st.get(k)
    return '' if v is None else v

def main():
    if len(sys.argv) < 2: raise SystemExit(__doc__)
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    season = sys.argv[sys.argv.index('--season') + 1] if '--season' in sys.argv else '2026'
    week = int(sys.argv[sys.argv.index('--week') + 1]) if '--week' in sys.argv else nfl_week()
    # ---- projections
    off_rows, idp_rows = [], []
    for pos in OFF + IDP:
        objs = get(f'/projections/nfl/{season}/{week}', season_type='regular', **{'position[]': pos, 'order_by': 'pts_ppr'})
        for o in objs:
            st = o.get('stats') or {}
            if not st: continue
            base = dict(player=name_of(o), team=o.get('team') or '', pos=(o.get('player') or {}).get('position') or pos,
                        opp=o.get('opponent') or '')
            if pos in OFF:
                off_rows.append({**base, 'pts_ppr': g(st, 'pts_ppr'), **{f: g(st, f) for f in OFF_FIELDS},
                                 'pts_allow': g(st, 'pts_allow'), 'fgm': g(st, 'fgm'), 'xpm': g(st, 'xpm'),
                                 'sack': g(st, 'sack'), 'int': g(st, 'int'), 'fum_rec': g(st, 'fum_rec'), 'def_td': g(st, 'def_td')})
            else:
                idp_rows.append({**base, **{f: g(st, IDP_MAP[f]) for f in IDP_FIELDS}})
        time.sleep(0.2)
    with open(f'{out}/sleeper_off_wk{week}.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['player', 'team', 'pos', 'opp', 'pts_ppr'] + OFF_FIELDS + ['pts_allow', 'fgm', 'xpm', 'sack', 'int', 'fum_rec', 'def_td'])
        w.writeheader(); w.writerows(off_rows)
    with open(f'{out}/sleeper_idp_wk{week}.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['player', 'team', 'pos', 'opp'] + IDP_FIELDS); w.writeheader(); w.writerows(idp_rows)
    # ---- stats (usage + actuals), one file per position
    n_stats = 0
    for pos in OFF:
        objs = get(f'/stats/nfl/{season}/{week}', season_type='regular', **{'position[]': pos, 'order_by': 'pts_ppr'})
        rows = []
        for o in objs:
            st = o.get('stats') or {}
            if not st: continue
            p = o.get('player') or {}
            rows.append(dict(player_id=o.get('player_id', ''), first_name=p.get('first_name', ''), last_name=p.get('last_name', ''),
                             team=o.get('team') or '', pos=p.get('position') or pos, **{f: g(st, f) for f in STAT_FIELDS}))
        with open(f'{out}/stats_wk{week}_{pos}.csv', 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['player_id', 'first_name', 'last_name', 'team', 'pos'] + STAT_FIELDS)
            w.writeheader(); w.writerows(rows)
        n_stats += len(rows); time.sleep(0.2)
    # ---- trending
    tr = []
    for kind in ('add', 'drop'):
        for e in get(f'/players/nfl/trending/{kind}', lookback_hours=48, limit=40):
            pid = str(e.get('player_id', ''))
            p = get(f'/players/nfl/{pid}') if not pid.isalpha() else {}
            tr.append(dict(player_id=pid, count=e.get('count', ''), first_name=(p or {}).get('first_name', ''),
                           last_name=(p or {}).get('last_name', pid if pid.isalpha() else ''),
                           team=(p or {}).get('team', pid if pid.isalpha() else ''), pos=(p or {}).get('position', 'DEF' if pid.isalpha() else ''), kind=kind))
            time.sleep(0.1)
    with open(f'{out}/trending.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=['player_id', 'count', 'first_name', 'last_name', 'team', 'pos', 'kind']); w.writeheader(); w.writerows(tr)
    print(f'week {week}: {len(off_rows)} offense proj, {len(idp_rows)} IDP proj, {n_stats} stat rows, {len(tr)} trending -> {out}')
    if len(off_rows) < 100: print('PARTIAL — fewer than 100 offense projections'); sys.exit(2)

if __name__ == '__main__':
    main()
