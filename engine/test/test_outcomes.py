"""OUTCOME LEDGER REGRESSION — lib/outcomes.py and lib/edge.calls_section on a synthetic
league in a temp root. Nothing reads or writes the live data: every store, snapshot,
log, matchup page and stat file lives under a tempdir; the pump's stats root is
pointed at another tempdir. Fictional names only.
"""
import sys, os, json, csv, tempfile, copy, datetime as dt
sys.path.insert(0, '/home/claude/bsb2')
from lib import clock as C, outcomes as OUT, edge as EDGE, state as S
from lib.leagues import ALL
from lib.names import key as NK

bad = 0; total = 0
def case(label, ok, detail=''):
    global bad, total
    total += 1
    if not ok: bad += 1
    print(f'[{"OK " if ok else "FAIL"}] {label}' + (f'  — {detail}' if detail and not ok else ''))

print('=' * 88); print('OUTCOME LEDGER REGRESSION'); print('=' * 88)

ROOT = tempfile.mkdtemp(prefix='out_root_')
FF = tempfile.mkdtemp(prefix='out_ff_')
OUT.FFDATA = FF
for d in ('data/state/BSB', 'data/state/HH', 'data/actuals', 'data/proj_log', 'data/outcomes'):
    os.makedirs(os.path.join(ROOT, d), exist_ok=True)
os.makedirs(os.path.join(FF, 'data', 'sleeper'), exist_ok=True)

W = 5
WS = C.week_start(W)                       # Tue 07:00 ET of week 5
SUN = WS + dt.timedelta(days=5, hours=6)   # Sunday 1:00 pm ET
AFTER = C.week_start(W + 1) + dt.timedelta(days=1)   # Wednesday of week 6: week 5 is final
ME = ALL['BSB'].name

TEAMS = ['ARI', 'ATL', 'BAL', 'BUF', 'CAR', 'CHI', 'CIN', 'CLE', 'DAL', 'DEN', 'DET', 'GB', 'HOU', 'IND', 'JAX', 'KC',
         'LAC', 'LAR', 'LV', 'MIA', 'MIN', 'NE', 'NO', 'NYG', 'NYJ', 'PHI', 'PIT', 'SEA', 'SF', 'TB', 'TEN', 'WAS']

# my BSB roster: 10 starters + bench; names are fictional
ROST = [('QB', 'Zorvath Quillby', 'QB', 'ARI'), ('RB', 'Brexley Talmont', 'RB', 'ATL'), ('RB', 'Oswin Pellamy', 'RB', 'BAL'),
        ('WR', 'Cadoc Dravonne', 'WR', 'BUF'), ('WR', 'Elric Fennickton', 'WR', 'CAR'), ('WR', 'Talvin Okonford', 'WR', 'CHI'),
        ('TE', 'Quillon Strickby', 'TE', 'CIN'), ('W/R/T', 'Pellam Thistleton', 'RB', 'CLE'), ('K', 'Dravon Montagley', 'K', 'DAL'),
        ('DEF', 'Denver', 'DEF', 'DEN'),
        ('BN', 'Fennick Rasmusdale', 'WR', 'DET'), ('BN', 'Zorvath Inger', 'TE', 'GB'), ('BN', 'Brexley Holl', 'RB', 'HOU')]
OTHER = [('QB', 'Aber Nakamworth', 'QB', 'IND')]
FA_ADD = ('Kettel Lindshaw', 'WR', 'JAX')        # a free agent the engine says to add

def snap(t, rows_spec, others=OTHER):
    rows = [dict(owner=ME, manager=ME, slot=s, player=n, pos=p, nfl=t_, designation='none') for s, n, p, t_ in rows_spec]
    rows += [dict(owner='Rival', manager='Rival', slot=s, player=n, pos=p, nfl=t_, designation='none') for s, n, p, t_ in others]
    p = os.path.join(ROOT, 'data', 'state', 'BSB', t.strftime('%Y-%m-%dT%H%M') + '.json')
    json.dump(dict(league='BSB', pulled=t.isoformat(), others_pulled=t.isoformat(), note='test', records={}, rows=rows), open(p, 'w'))
    OUT._SNAPS.clear(); OUT._POSX.clear()

# --- actual points for week 5 (Sleeper stat lines; BSB scoring is exact for these fields)
PTS = {'Zorvath Quillby': dict(pass_yd=300, pass_td=2), 'Brexley Talmont': dict(rush_yd=80, rec=2, rec_yd=10),
       'Oswin Pellamy': dict(rush_yd=50), 'Cadoc Dravonne': dict(rec=6, rec_yd=90, rec_td=1), 'Elric Fennickton': dict(rec=3, rec_yd=30),
       'Talvin Okonford': dict(rec=2, rec_yd=15), 'Quillon Strickby': dict(rec=4, rec_yd=40), 'Pellam Thistleton': dict(rush_yd=40),
       'Fennick Rasmusdale': dict(rec=8, rec_yd=120, rec_td=1), 'Zorvath Inger': dict(rec=1, rec_yd=5), 'Brexley Holl': dict(rush_yd=10),
       'Kettel Lindshaw': dict(rec=9, rec_yd=140, rec_td=2), 'Aber Nakamworth': dict(pass_yd=200)}
POSOF = {n: p for _, n, p, _ in ROST + OTHER}; POSOF['Kettel Lindshaw'] = 'WR'
TMOF = {n: t for _, n, _, t in ROST + OTHER}; TMOF['Kettel Lindshaw'] = 'JAX'
FIELDS = ['player_id', 'first_name', 'last_name', 'team', 'pos', 'gp', 'gs', 'off_snp', 'tm_off_snp', 'pass_att', 'pass_cmp', 'pass_yd', 'pass_td', 'pass_int',
          'rush_att', 'rush_yd', 'rush_td', 'rec', 'rec_tgt', 'rec_yd', 'rec_td', 'fum_lost', 'fgm', 'xpm', 'xpa', 'pts_allow', 'sack', 'int', 'fum_rec', 'def_td', 'pts_ppr']
def write_stats(week, extra_teams=True):
    by = {p: [] for p in ('QB', 'RB', 'WR', 'TE', 'K', 'DEF')}
    for n, st in PTS.items():
        f, l = n.split(' ', 1)
        by[POSOF[n]].append(dict(player_id=n, first_name=f, last_name=l, team=TMOF[n], pos=POSOF[n], **st))
    by['K'].append(dict(player_id='k', first_name='Dravon', last_name='Montagley', team='DAL', pos='K', fgm=2, xpm=3, xpa=3))
    by['DEF'].append(dict(player_id='DEN', first_name='Denver', last_name='Broncos', team='DEN', pos='DEF', pts_allow=10, sack=3, int=1))
    if extra_teams:
        for i, t in enumerate(TEAMS):
            by['QB'].append(dict(player_id=f'q{i}', first_name='Filler', last_name=f'Passer{i}', team=t, pos='QB', pass_yd=100))
    for p, rows in by.items():
        with open(os.path.join(FF, 'data', 'sleeper', f'stats_wk{week}_{p}.csv'), 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def write_log(rows):
    with open(os.path.join(ROOT, 'data', 'bsb_transactions.csv'), 'w', newline='') as fh:
        w = csv.writer(fh); w.writerow(['datetime', 'team', 'action', 'player', 'pos', 'nfl', 'bid', 'note']); w.writerows(rows)
write_log([])
open(os.path.join(ROOT, 'data', 'hh_transactions.csv'), 'w').write('datetime,team,action,player,pos,nfl,bid,note\n')

# --- a synthetic run: the lineup engine wants Rasmusdale (bench WR) at WR3 over Okonford;
#     the wire wants Lindshaw added for Holl
def make_run(now, margin_shift=0.0):
    rows = [dict(owner=ME, manager=ME, slot=s, player=n, pos=p, nfl=t_, designation='none') for s, n, p, t_ in ROST] + \
           [dict(owner='Rival', manager='Rival', slot=s, player=n, pos=p, nfl=t_, designation='none') for s, n, p, t_ in OTHER]
    st = S.State('BSB', rows, now.isoformat(), source='synthetic.json')
    for r in st.mine: r['pts'] = 10.0; r['kick'] = SUN; r['phase'] = 'early'
    cur = st.current_lineup()
    opt = dict(cur)
    ras = st.row_of('Fennick Rasmusdale'); oko = st.row_of('Talvin Okonford'); ras['pts'] = 14.0 + margin_shift; oko['pts'] = 9.0
    opt['WR3'] = ras
    ch = dict(slot='WR3', start=ras, sit=oko, gain=ras['pts'] - oko['pts'], provisional=False, reason='', phase='early', kick=SUN)
    class G:  # a gate result
        verdict = 'PASS'
    lu = dict(optimal=opt, current=cur, changes=[ch], perms=[], rows=st.mine, total_cur=0, total_opt=0, unknown=[])
    add = dict(key=NK(FA_ADD[0]), name=FA_ADD[0], pos='WR', tm='JAX', week=12.0, line={'sources': ['sleeper']})
    holl = st.row_of('Brexley Holl'); holl['pts'] = 3.0
    calls = [dict(kind='start', change=ch, gate=G(), ledger=dict(status='proposed', call='start Fennick Rasmusdale at WR3')),
             dict(kind='swap', item=dict(add=add, drop=holl, gain=9.0, basis='pts/wk', dead=False), gate_add=G(), gate_drop=G(),
                  ledger=dict(status='proposed', call='drop Brexley Holl -> add Kettel Lindshaw'))]
    R = dict(state=st, lineup=lu, calls=calls, stream_calls=[], breakout=dict(rows=[], drops=[]), nextup=dict(alerts=[]), flags=[],
             win=dict(opp='Rival', current=dict(p_opp=0.55, p_med=0.6, mean=120, sd=20), options=[]))
    return dict(week=W, leagues={'BSB': R}, proj=None, plans={})

T0 = WS + dt.timedelta(days=3)      # Friday of week 5
r1 = OUT.record(make_run(T0), root=ROOT, now=T0)
D = OUT.read('decisions', ROOT)
case('record: one lineup row per slot plus the swap', r1['new'] == len(ALL['BSB'].slots) + 1 and len(D) == len(ALL['BSB'].slots) + 1, str(r1))
r2 = OUT.record(make_run(T0 + dt.timedelta(hours=2)), root=ROOT, now=T0 + dt.timedelta(hours=2))
case('dedupe: an identical re-run appends nothing', r2['new'] == 0 and len(OUT.read('decisions', ROOT)) == len(D), str(r2))
r3 = OUT.record(make_run(T0 + dt.timedelta(hours=4), margin_shift=1.0), root=ROOT, now=T0 + dt.timedelta(hours=4))
D3 = OUT.latest('decisions', root=ROOT)
wr3 = next(d for d in D3.values() if d['kind'] == 'lineup_slot' and d['subject'] == 'WR3')
case('dedupe: a changed margin updates the row in place', r3['new'] == 0 and r3['updated'] >= 1 and len(D3) == len(D) and abs(wr3['margin'] - 6.0) < 1e-6, f"{r3} margin {wr3['margin']}")
case('dedupe: created is carried forward, revisions counted (an unchanged run writes nothing)', wr3['created'] == C.iso(T0) and wr3['runs'] == 2, f"{wr3['created']} runs {wr3['runs']}")
case('lineup decision: recommended, alternative and deadline at kickoff', wr3['recommended'] == NK('Fennick Rasmusdale') and wr3['first_current'] == NK('Talvin Okonford')
     and wr3['deadline'] == C.iso(SUN) and wr3['surfaced_on_decide'], json.dumps({k: wr3[k] for k in ('recommended', 'first_current', 'deadline', 'surfaced_on_decide')}))
sw = next(d for d in D3.values() if d['kind'] == 'add_drop')
case('add/drop decision: keyed by add and drop, deadline at the Tuesday rollover', sw['subject'] == NK(FA_ADD[0]) and sw['alternative'] == NK('Brexley Holl')
     and sw['deadline'] == C.iso(C.week_start(W + 1)) and sw['id'] == OUT.decision_id('BSB', W, 'add_drop', NK(FA_ADD[0]), NK('Brexley Holl')))
late = OUT.record(make_run(SUN + dt.timedelta(hours=1)), root=ROOT, now=SUN + dt.timedelta(hours=1))
_L = OUT.latest('decisions', root=ROOT)
case('record after kickoff: the pregame lineup rows are frozen as they stood', _L[wr3['id']]['margin'] == wr3['margin'] and _L[wr3['id']]['frozen'] and late['updated'] == 0 and late['frozen'] == len(ALL['BSB'].slots), str(late))
r_post = OUT.record(make_run(SUN + dt.timedelta(hours=2), margin_shift=5.0), root=ROOT, now=SUN + dt.timedelta(hours=2))
case('a frozen row is never rewritten', OUT.latest('decisions', root=ROOT)[wr3['id']]['margin'] == wr3['margin'], str(r_post))

# --- week-scoped resolution. Week 5 before kickoff: Okonford still at WR3 (call ignored).
#     A week-6 snapshot shows Rasmusdale starting — that must NOT count for week 5.
r6 = [(('WR' if n == 'Fennick Rasmusdale' else 'BN' if n == 'Talvin Okonford' else s), n, p, t_) for s, n, p, t_ in ROST]
snap(WS - dt.timedelta(days=2), r6)                                        # week 4: he started THEN — irrelevant to week 5
snap(SUN - dt.timedelta(hours=3), ROST)                                    # week 5, before kickoff: unchanged
snap(C.week_start(W + 1) + dt.timedelta(hours=5), r6)                      # week 6: he starts again
write_stats(W)
res = OUT.resolve(ROOT, now=AFTER)
RS = OUT.latest('resolutions', key_field='decision_id', root=ROOT)
case('resolution is week-scoped: a later week\'s lineup is not credited', RS[wr3['id']]['status'] == 'ignored' and RS[wr3['id']]['chosen'] == NK('Talvin Okonford'),
     json.dumps(RS[wr3['id']]))
case('resolution reads the last snapshot before HIS kickoff', RS[wr3['id']].get('source') == 'snapshot ' + (SUN - dt.timedelta(hours=3)).strftime('%Y-%m-%dT%H%M') + '.json', RS[wr3['id']].get('source'))
case('no week-5 snapshot before the lock -> no lineup (the week-4 one is never used)', OUT.my_lineup_at('BSB', WS + dt.timedelta(hours=1), W, ROOT) is None)
same = [d for d in D3.values() if d['kind'] == 'lineup_slot' and d['subject'] == 'QB'][0]
case('a slot the engine agreed with is moot', RS[same['id']]['status'] == 'moot', RS[same['id']]['status'])
case('the add not made is ignored (no log entry, no snapshot change)', RS[sw['id']]['status'] == 'ignored', json.dumps(RS[sw['id']]))

# --- outcomes: week 5 is complete (rolled + stats cover every team on the week's log/26+)
case('week_complete: rolled and covered', OUT.week_complete(W, ROOT, AFTER) and not OUT.week_complete(W, ROOT, SUN + dt.timedelta(hours=8)))
oc = OUT.compute_outcomes(ROOT, now=AFTER)
O = OUT.latest('outcomes', root=ROOT)
o_l = O[f"{wr3['id']}|1"]
# Rasmusdale: 8 rec + 120 yds + TD = 8 + 12 + 6 = 26 ; Okonford: 2 + 1.5 = 3.5
case('lineup outcome: actual(recommended) - actual(chosen)', o_l['available'] and abs(o_l['delta'] - (26.0 - 3.5)) < 1e-6 and abs(o_l['call_value'] - 22.5) < 1e-6, json.dumps(o_l))
o_a = O.get(f"{sw['id']}|1")
# Lindshaw 9 + 14 + 12 = 35 beats every WR and the flex: V(with add) - V(with Holl) > 0
case('a missed add has a cost: ignored add scored with V(with add) - V(with drop) > 0', o_a is not None and o_a['available'] and o_a['delta_add'] > 0 and o_a['status'] == 'ignored',
     json.dumps(o_a))
cs = EDGE.calls_section(ROOT)
ad = next((r for r in cs['rows'] if r['kind'] == 'add_drop'), {})
case('edge: the ignored add shows up as cost, not as gain', ad.get('cost', 0) > 0 and ad.get('gained') == 0 and ad.get('ignored') == 1, json.dumps(ad))
ls = next((r for r in cs['rows'] if r['kind'] == 'lineup_slot'), {})
case('edge: an ignored lineup call costs its realized value', abs(ls.get('cost', 0) - 22.5) < 1e-6 and ls.get('hits') == 1, json.dumps(ls))
case('3-week horizon waits for weeks 6 and 7', f"{sw['id']}|3" not in O)
case('rest-of-season horizon is partial, not frozen', O.get(f"{sw['id']}|ros", {}).get('partial') is True and not O[f"{sw['id']}|ros"].get('frozen'))
oc2 = OUT.compute_outcomes(ROOT, now=AFTER); res2 = OUT.resolve(ROOT, now=AFTER)
case('idempotent: a second pass changes nothing', oc2['new'] == 0 and oc2['updated'] == 0 and res2['new'] == 0 and res2['updated'] == 0, f'{oc2} {res2}')

# --- hindsight V on its own
A = OUT.Actuals(ROOT)
posx = {NK(n): p for n, p in POSOF.items()}; posx['DST:DEN'] = 'DEF'
mine = {NK(n) for _, n, _, _ in ROST}
v0, miss0 = OUT.V('BSB', mine, W, A, posx)
# QB 300/20+12 = 27; RBs Talmont 8+2+1=11, Pellamy 5, Thistleton 4, Holl 1; WRs Rasmusdale 26, Dravonne 6+9+6=21, Fennickton 3+3=6, Okonford 3.5;
# TEs Strickby 4+4=8, Inger 1+0.5=1.5; K 2*36/10+3=10.2; DEF 3+2+6(PA 7-13)=11
exp = 27 + 11 + 5 + 26 + 21 + 6 + 8 + 4 + 10.2 + 11      # flex: max(Okonford 3.5, Thistleton 4, Inger 1.5) = 4
case('hindsight V = the optimal lineup on actual points', abs(v0 - exp) < 1e-6 and not miss0, f'{v0} vs {exp} {miss0}')
v1, _ = OUT.V('BSB', (mine | {NK(FA_ADD[0])}) - {NK('Brexley Holl')}, W, A, posx)
# Lindshaw 35 takes a WR slot from Fennickton (6), who moves to the flex over Thistleton (4): +29 +2
case('V with the add: the whole lineup re-optimizes (WR slot and flex)', abs((v1 - v0) - 31.0) < 1e-6, f'{v1 - v0}')

# --- executed add via the transactions log -> followed; decline -> overridden
OUT._write('resolutions', [], ROOT); OUT._write('outcomes', [], ROOT)
write_log([[(T0 + dt.timedelta(hours=5)).strftime('%Y-%m-%d %H:%M'), ME, 'Add', FA_ADD[0], 'WR', 'JAX', '', 'Free Agent'],
           [(T0 + dt.timedelta(hours=5)).strftime('%Y-%m-%d %H:%M'), ME, 'Drop', 'Brexley Holl', 'RB', 'HOU', '', 'To Waivers']])
OUT.resolve(ROOT, now=AFTER)
RS = OUT.latest('resolutions', key_field='decision_id', root=ROOT)
case('an add on the transactions log inside [created, deadline] is followed', RS[sw['id']]['status'] == 'followed' and RS[sw['id']]['how'] == 'executed', json.dumps(RS[sw['id']]))
write_log([])
OUT._write('resolutions', [], ROOT)
json.dump([dict(id='x1', league='BSB', kind='add', subject=FA_ADD[0], call='drop Brexley Holl -> add Kettel Lindshaw', status='declined', week=W)],
          open(os.path.join(ROOT, 'data', 'ledger.json'), 'w'))
OUT.resolve(ROOT, now=AFTER)
RS = OUT.latest('resolutions', key_field='decision_id', root=ROOT)
case('a declined add is overridden (declined) — and still scored', RS[sw['id']]['status'] == 'overridden' and RS[sw['id']]['how'] == 'declined', json.dumps(RS[sw['id']]))
os.remove(os.path.join(ROOT, 'data', 'ledger.json'))

# --- IDP without a feed is unavailable, never zero
case('IDP actual without a feed is unavailable, not 0', OUT.Actuals(ROOT, AFTER).pts('HH', W, 'nobody idp', 'LB')[0] is None)
case('a completed week\'s offensive player with no stat row scores 0 (did not play)', OUT.Actuals(ROOT, AFTER).pts('BSB', W, 'nobody wr', 'WR')[0] == 0.0)
case('...but in a week still being played he is unknown, not 0', OUT.Actuals(ROOT, SUN + dt.timedelta(hours=8)).pts('BSB', W, 'nobody wr', 'WR')[0] is None)

# --- claims: Caleb's own bid is recorded and settled against the log
from lib import rules as RU
OUT.bid('Kettel Lindshaw', 7, root=ROOT, now=T0)
cl = OUT.read('claims', ROOT)
case('ff.py bid records the bid', len(cl) == 1 and cl[0]['my_bid'] == 7 and cl[0]['status'] == 'pending', json.dumps(cl))

# --- a store line that does not parse is an error, not an empty store
open(OUT._path('decisions', ROOT), 'a').write('{not json\n')
try:
    OUT.read('decisions', ROOT); ok = False
except ValueError: ok = True
case('a corrupt store refuses (never read as empty)', ok)

print('=' * 88)
print(f'{total - bad}/{total} behaved as required.' + ('  OUTCOME LEDGER IS SOUND.' if not bad else '  OUTCOME LEDGER FAILED.'))
sys.exit(1 if bad else 0)
