"""CALIBRATION REGRESSION — lib/calib.report on synthetic logs in a temp root.

What it pins down (10-04 audit): the report compares PAIRED samples only; a row
written after its kickoff is not a pregame number; the git back-fill stands in for
such a row; the HH week-2 engine-only back-fill is never part of a paired comparison
(it has its own engine-only line); the market subset is the rows where a Kalshi field
moved the engine number by >= 1. Fictional names; nothing live is read or written.
"""
import sys, os, csv, json, tempfile, datetime as dt
sys.path.insert(0, '/home/claude/bsb2')
from lib import calib as CB, outcomes as OUT, clock as C

bad = 0; total = 0
def case(label, ok, detail=''):
    global bad, total
    total += 1
    if not ok: bad += 1
    print(f'[{"OK " if ok else "FAIL"}] {label}' + (f'  — {detail}' if detail and not ok else ''))

print('=' * 88); print('CALIBRATION REGRESSION'); print('=' * 88)
ROOT = tempfile.mkdtemp(prefix='cal_root_'); FF = tempfile.mkdtemp(prefix='cal_ff_')
OUT.FFDATA = FF
os.makedirs(os.path.join(ROOT, 'data', 'proj_log')); os.makedirs(os.path.join(ROOT, 'data', 'actuals'))
os.makedirs(os.path.join(FF, 'data', 'sleeper'))
TEAMS = ['ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN', 'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC',
         'LAC', 'LAR', 'LV', 'MIA', 'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB', 'TEN', 'WAS']
NOW = C.week_start(4) + dt.timedelta(days=1)             # weeks 2 and 3 are final
FIELDS = ['player_id', 'first_name', 'last_name', 'team', 'pos', 'rec', 'rec_yd', 'rec_td', 'rush_yd', 'pass_yd', 'pts_ppr']
PL = {  # name: (team, pos, stats) — BSB points = rec + rec_yd/10 + 6*td
    'Aldous Pemberwick': ('ARI', 'WR', dict(rec=5, rec_yd=60)),        # 11.0
    'Bram Quarterfield': ('ATL', 'WR', dict(rec=2, rec_yd=20)),        # 4.0
    'Cyprian Thistledale': ('BAL', 'RB', dict(rush_yd=100)),           # 10.0
    'Dorian Montagshaw': ('BUF', 'WR', dict(rec=7, rec_yd=90, rec_td=1)),  # 22.0
    'Evander Okonmore': ('CAR', 'TE', dict(rec=3, rec_yd=30)),          # 6.0
}
for w in (2, 3):
    rows = {p: [] for p in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')}
    for n, (t, p, st) in PL.items():
        f, l = n.split(' ', 1); rows[p].append(dict(player_id=n, first_name=f, last_name=l, team=t, pos=p, **st))
    for i, t in enumerate(TEAMS):
        rows['QB'].append(dict(player_id=f'q{i}', first_name='Filler', last_name=f'Arm{i}', team=t, pos='QB', pass_yd=100))
    for p, rs in rows.items():
        with open(os.path.join(FF, 'data', 'sleeper', f'stats_wk{w}_{p}.csv'), 'w', newline='') as fh:
            wr = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore'); wr.writeheader(); wr.writerows(rs)
LF = ['key', 'player', 'owner', 'pos', 'tm', 'slot', 'engine', 'sleeper', 'yahoo', 'kalshi_fields', 'kick', 'locked', 'post', 'logged']
from lib.names import key as NK
K3 = '2026-09-27T13:00-04:00'
def row(n, e, s, y, kf='', logged='2026-09-27T11:00-04:00', post='0'):
    t, p, _ = PL[n]
    return dict(key=NK(n), player=n, owner='X', pos=p, tm=t, slot='BN', engine=e, sleeper=s, yahoo=y, kalshi_fields=kf, kick=K3, locked='1', post=post, logged=logged)
log = [row('Aldous Pemberwick', '12.00', '10.00', '9.00'),                     # all three
       row('Bram Quarterfield', '5.00', '6.00', ''),                            # no Yahoo
       row('Cyprian Thistledale', '9.00', '', ''),                              # engine only
       row('Dorian Montagshaw', '15.00', '12.00', '13.00', logged='2026-09-27T14:30-04:00'),   # written after kickoff
       row('Evander Okonmore', '8.50', '6.00', '7.00', kf='rec,rec_yd')]       # market moved it 2.5
def wlog(path, rows, extra=()):
    with open(path, 'w', newline='') as fh:
        wr = csv.DictWriter(fh, fieldnames=LF + list(extra), extrasaction='ignore'); wr.writeheader(); wr.writerows(rows)
wlog(os.path.join(ROOT, 'data', 'proj_log', 'BSB_wk3.csv'), log)
# HH week 2: no log; the engine-only json back-fill
json.dump({NK(n): dict(name=n, pos=PL[n][1], pts=10.0) for n in PL}, open(os.path.join(ROOT, 'data', 'hh_proj_wk2.json'), 'w'))

rep = CB.report(3, root=ROOT, now=NOW)
pair = lambda a, b, lg: next((p for p in rep['pairs'] if p['a'] == a and p['b'] == b and p['league'] == lg), None)
case('the three-way table uses only rows where all three sources exist (post-kickoff row excluded)', rep['n_total'] == 2, str(rep['n_total']))
es = pair('engine', 'sleeper', 'BSB')
case('engine v sleeper is paired: the engine-only row and the post-kickoff row are out', es is not None and es['n'] == 3, str(es and es['n']))
ey = pair('engine', 'yahoo', 'BSB')
case('engine v yahoo is paired on its own rows', ey is not None and ey['n'] == 2, str(ey and ey['n']))
# engine errors on the e/s pairs: +1 (12-11), +1 (5-4), +2.5 (8.5-6) -> MAE 1.5 ; sleeper: -1, +2, 0 -> MAE 1.0
case('MAE, RMSE and bias computed on the paired rows', abs(es['sa']['mae'] - 1.5) < 1e-9 and abs(es['sb']['mae'] - 1.0) < 1e-9 and abs(es['sa']['bias'] - 1.5) < 1e-9
     and abs(es['sa']['rmse'] - ((1 + 1 + 6.25) / 3) ** 0.5) < 1e-9, json.dumps(es['sa']))
case('the HH week-2 engine-only back-fill is never in a pair', all(p['league'] in ('BSB', 'ALL') for p in rep['pairs']) and ('HH', 2) not in rep['weeks']
     and all(p['n'] == pair(p['a'], p['b'], 'BSB')['n'] for p in rep['pairs'] if p['league'] == 'ALL'), json.dumps(rep['weeks']))
case('...it has its own engine-only line', rep['engine_only']['n'] == len(PL) and rep['engine_only']['weeks'] == [('HH', 2)], json.dumps(rep['engine_only'], default=str))
case('market subset: a Kalshi field and |engine - sleeper| >= 1', rep['market']['n'] == 1, str(rep['market']['n']))
case('per-position rows on the pairs', {b['pos'] for b in rep['by_pos']} == {'WR', 'TE'}, str([b['pos'] for b in rep['by_pos']]))
case('game-bootstrap CI present when two or more games', es['ci'] is not None and es['ci']['games'] == 3 and es['ci']['lo'] <= es['ci']['diff'] <= es['ci']['hi'], json.dumps(es['ci']))
# the git back-fill stands in for the post-kickoff row
bf = [dict(row('Dorian Montagshaw', '20.00', '18.00', '19.00', logged='2026-09-27T12:41-04:00'), commit='abc', pulled='2026-09-27T12:36-04:00')]
wlog(os.path.join(ROOT, 'data', 'proj_log', 'BSB_wk3.backfill.csv'), bf, extra=('commit', 'pulled'))
rep2 = CB.report(3, root=ROOT, now=NOW)
case('the back-fill row replaces a live row written after kickoff', rep2['n_total'] == 3 and any('backfill' in k for k in rep2['origins']), json.dumps(rep2['origins']))
wlog(os.path.join(ROOT, 'data', 'proj_log', 'BSB_wk3.backfill.csv'), [dict(bf[0], player='Aldous Pemberwick', key=NK('Aldous Pemberwick'), engine='99.00')], extra=('commit', 'pulled'))
rep3 = CB.report(3, root=ROOT, now=NOW)
es3 = next(p for p in rep3['pairs'] if p['a'] == 'engine' and p['b'] == 'sleeper' and p['league'] == 'BSB')
case('...but never a live PREGAME row', abs(es3['sa']['mae'] - 1.5) < 1e-9, json.dumps(es3['sa']))
case('a week not yet final is not scored', CB.report(3, root=ROOT, now=C.week_start(3) + dt.timedelta(days=5))['n_samples'] == 0)
txt = CB.fmt(rep2)
case('fmt prints pairs, the market subset and the engine-only line', 'engine v sleeper' in txt and 'market changed' in txt and 'engine-only' in txt)
print('=' * 88)
print(f'{total - bad}/{total} behaved as required.' + ('  CALIBRATION IS SOUND.' if not bad else '  CALIBRATION FAILED.'))
sys.exit(1 if bad else 0)
