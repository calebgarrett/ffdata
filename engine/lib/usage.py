"""ONE USAGE LAYER — what actually happened on the field, by share of team.

A projection forecasts production; a snap count observes whether a player is
on the field. Where they disagree, the snap count wins. This module loads the
verified weekly usage pull (data/usage_wk{W}_{POS}.csv, Sleeper stats, pulled
in verified chunks — see RUNBOOK 'usage pull') and turns raw counts into
SHARES of the team, which is the only form that compares across offenses.

  snap_share  = off_snp / tm_off_snp
  tgt_share   = rec_tgt / team pass attempts (QB pass_att, the cleanest denominator)
  air_share   = rec_air_yd / team air yards (sum over the file; approximate)
  touch_share = (rush_att + rec_tgt) / team RB (rush_att + rec_tgt)   (RB only)

Doctrine (Caleb, 09-16): "Don't over value certain offenses. Individual points
matter." A share is per-player. Nothing here haircuts a player for his team.
"""
import csv, os
from collections import defaultdict
from .names import key, team

D = '/home/claude/bsb2/data/'
POS = ('QB', 'RB', 'WR', 'TE')

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

def load(week):
    """-> dict key -> row(name, tm, pos, pid, gs, off_snp, tm_off_snp, rec_tgt, rec, rec_yd,
       rec_td, rec_air_yd, rec_rz_tgt, rush_att, rush_yd, rush_td, pass_att, pts_ppr,
       snap_share, tgt_share, air_share, touch_share) ; empty dict when no pull on disk."""
    rows = {}
    files = [D + f'usage_wk{week}_{p}.csv' for p in POS]
    if not any(os.path.exists(f) for f in files): return {}
    for p, f in zip(POS, files):
        if not os.path.exists(f): continue
        for r in csv.DictReader(open(f)):
            name = f"{r['first_name']} {r['last_name']}".strip()
            k = key(name)
            row = dict(name=name, tm=team(r['team']), pos=p, pid=r.get('player_id', ''),
                       gs=_f(r.get('gs')), off_snp=_f(r.get('off_snp')), tm_off_snp=_f(r.get('tm_off_snp')),
                       rec_tgt=_f(r.get('rec_tgt')), rec=_f(r.get('rec')), rec_yd=_f(r.get('rec_yd')),
                       rec_td=_f(r.get('rec_td')), rec_air_yd=_f(r.get('rec_air_yd')),
                       rec_rz_tgt=_f(r.get('rec_rz_tgt')), rush_att=_f(r.get('rush_att')),
                       rush_yd=_f(r.get('rush_yd')), rush_td=_f(r.get('rush_td')),
                       pass_att=_f(r.get('pass_att')), pts_ppr=_f(r.get('pts_ppr')), week=week)
            rows[k] = row
    # team denominators
    T = defaultdict(lambda: dict(pass_att=0.0, air=0.0, rb_touch=0.0, tgt=0.0, snp=0.0))
    for r in rows.values():
        t = T[r['tm']]
        t['pass_att'] += r['pass_att']
        t['air'] += max(r['rec_air_yd'], 0.0)
        t['tgt'] += r['rec_tgt']
        t['snp'] = max(t['snp'], r['tm_off_snp'])
        if r['pos'] == 'RB': t['rb_touch'] += r['rush_att'] + r['rec_tgt']
    for r in rows.values():
        t = T[r['tm']]
        den_tgt = t['pass_att'] or t['tgt'] or 0.0
        r['snap_share'] = r['off_snp'] / r['tm_off_snp'] if r['tm_off_snp'] else 0.0
        r['tgt_share'] = r['rec_tgt'] / den_tgt if den_tgt else 0.0
        r['air_share'] = max(r['rec_air_yd'], 0.0) / t['air'] if t['air'] else 0.0
        r['touch_share'] = ((r['rush_att'] + r['rec_tgt']) / t['rb_touch']) if (r['pos'] == 'RB' and t['rb_touch']) else 0.0
        r['team_den'] = dict(T[r['tm']])
    return rows

def pulled_at(week):
    """Newest mtime among the position files, as a datetime in ET, or None."""
    from . import clock as C
    import datetime as dt
    ts = [os.path.getmtime(D + f'usage_wk{week}_{p}.csv') for p in POS if os.path.exists(D + f'usage_wk{week}_{p}.csv')]
    if not ts: return None
    return dt.datetime.fromtimestamp(max(ts), tz=dt.timezone.utc).astimezone(C.ET)
