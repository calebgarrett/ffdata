#!/usr/bin/env python3
"""Back-fill the calibration log's PREGAME numbers for a past week from the pump's git
history (10-04). The live log for week 3 is unusable: before the 10-04 fix a row was
recomputed by the first run after its kickoff, with the ladders already stripped by the
live guard (222 of 227 BSB rows logged after kickoff), so 'engine' == 'sleeper' there.

How it is reconstructed, faithfully and without inventing a number:
  1. The kickoff of every rostered player's game comes from the week's live log ('kick').
  2. For each distinct kickoff K, the LAST pump commit pulled before K is the input set
     the engine would have had at lock: data/kalshi.csv, data/sleeper/sleeper_off_wk{W}.csv,
     data/sleeper/sleeper_idp_wk{W}.csv, data/espn_games.csv, and Yahoo's own projection
     for every rostered player off data/yahoo/{LG}_rosters.csv (proj_pts).
  3. Those files are installed into this engine's data/ (THROWAWAY: run it only inside the
     private mount namespace on a scratch copy — it overwrites week files), the clock is
     pinned to that commit's pull time, and today's Projections() builds the line exactly as
     the live run does (week guard, live guard). Each player gets engine (market-first),
     sleeper (market=False) and yahoo under each league's scoring.
  4. Output: data/proj_log/{LG}_wk{W}.backfill.csv (same columns as the live log plus
     'commit' and 'pulled'), read by calib.load_log() for any player whose live row is not
     pregame. The live log is never touched.

What it is NOT: the engine code of that week (it is today's code on that week's inputs —
the λ = -ln(1-P) anytime-TD conversion included), and not week 2 (the pump's first commit
is 09-23; week 2's inputs exist only as Tuesday/Wednesday files, not at lock).

  python3 calib_backfill.py 3 [out_dir]
"""
import sys, os, csv, subprocess, datetime as dt, shutil
sys.path.insert(0, '/home/claude/bsb2')
from lib import clock as C, ts as T, score as SC
from lib.names import key, team

D = '/home/claude/bsb2/data/'
FF = os.environ.get('FFDATA_ROOT', '/home/claude/ffdata_repo')
FIELDS = ['key', 'player', 'owner', 'pos', 'tm', 'slot', 'engine', 'sleeper', 'yahoo', 'kalshi_fields', 'kick', 'locked', 'post', 'logged', 'commit', 'pulled']

def git(*a):
    return subprocess.run(['git', '-C', FF] + list(a), capture_output=True, text=True, check=True).stdout

def commits():
    out = []
    for line in git('log', '--format=%H %s %cI').splitlines():
        parts = line.split()
        h, ci = parts[0], parts[-1]
        pulled = None
        if len(parts) >= 3 and parts[1] == 'pull': pulled = T.try_ts(parts[2], 'pump')
        t = pulled or T.try_ts(ci, 'pump')
        out.append((t, h))
    out.sort()
    return out

def show(h, path):
    try: return git('show', f'{h}:{path}')
    except subprocess.CalledProcessError: return None

def main(week, out_dir=None):
    out_dir = out_dir or D + 'proj_log/'
    live = {}
    for lg in ('BSB', 'HH'):
        p = D + f'proj_log/{lg}_wk{week}.csv'
        if os.path.exists(p): live[lg] = list(csv.DictReader(open(p)))
    kicks = sorted({T.try_ts(r['kick'], 'legacy') for rs in live.values() for r in rs if r.get('kick')})
    cs = commits()
    res = {lg: [] for lg in live}
    for K in kicks:
        cand = [(t, h) for t, h in cs if t < K and show(h, f'data/sleeper/sleeper_off_wk{week}.csv') is not None]
        if not cand:
            print(f'  {K}: no pump commit before kickoff with week-{week} files — not back-filled'); continue
        t, h = cand[-1]
        files = {'kalshi.csv': 'data/kalshi.csv', f'sleeper_off_wk{week}.csv': f'data/sleeper/sleeper_off_wk{week}.csv',
                 f'sleeper_idp_wk{week}.csv': f'data/sleeper/sleeper_idp_wk{week}.csv', 'espn_games.csv': 'data/espn_games.csv'}
        for dst, src in files.items():
            body = show(h, src)
            if body is None:
                if os.path.exists(D + dst) and dst != 'espn_games.csv': os.remove(D + dst)
                continue
            open(D + dst, 'w').write(body)
        for f in ('kalshi.csv.fits.pkl', 'espn_props.csv'):
            if os.path.exists(D + f): os.remove(D + f)
        for lg in ('BSB', 'HH'):
            body = show(h, f'data/yahoo/{lg}_rosters.csv')
            rows = list(csv.DictReader(body.splitlines())) if body else []
            with open(D + f'yahoo_{lg}_wk{week}.csv', 'w', newline='') as fh:
                w = csv.writer(fh); w.writerow(['player', 'tm', 'pos', 'pts'])
                for r in rows:
                    try: float(r['proj_pts'])
                    except (TypeError, ValueError): continue
                    w.writerow([r['player'], r['nfl'], r['pos'], r['proj_pts']])
        # pin the clock to the pull, so the week guard and the live guard see what the live run saw
        pin = t + dt.timedelta(minutes=5)
        C.now = lambda pin=pin: pin
        from lib import project as PJ
        import importlib; importlib.reload(PJ)
        P = PJ.Projections(week)
        n = 0
        for lg, rs in live.items():
            for r in rs:
                if T.try_ts(r.get('kick'), 'legacy') != K: continue
                L = P.line(r['key'], r['pos'], r['tm']); Ls = P.line(r['key'], r['pos'], r['tm'], market=False)
                eng = SC.points(L, lg) if not L.get('unknown') else None
                slp = SC.points(Ls, lg) if not Ls.get('unknown') and 'sleeper' in Ls['sources'] else None
                yh = (P.yahoo.get(r['key']) or {}).get(lg)
                kf = ','.join(f for f in ('rec', 'rec_yd', 'rush_yd', 'pass_yd', 'pass_td', 'td') if f in (L.get('prov') or {}))
                res[lg].append(dict(key=r['key'], player=r['player'], owner=r['owner'], pos=r['pos'], tm=r['tm'], slot=r['slot'],
                                    engine='' if eng is None else f'{eng:.2f}', sleeper='' if slp is None else f'{slp:.2f}',
                                    yahoo='' if yh is None else f'{yh:.2f}', kalshi_fields=kf, kick=r['kick'], locked='1', post='0',
                                    logged=C.iso(pin), commit=h[:10], pulled=C.iso(t)))
                n += 1
        print(f'  kickoff {C.stamp(K)}: commit {h[:10]} pulled {C.stamp(t)} — {n} rows · {len(P.kal)} ladders this week · ready {len(P.ready)} teams · props {"on" if P.props else "off"}')
    os.makedirs(out_dir, exist_ok=True)
    for lg, rows in res.items():
        p = os.path.join(out_dir, f'{lg}_wk{week}.backfill.csv')
        with open(p, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
        print(f'  wrote {p}: {len(rows)} rows ({sum(1 for r in rows if r["kalshi_fields"])} with a Kalshi field, {sum(1 for r in rows if r["yahoo"])} with a Yahoo number)')

if __name__ == '__main__':
    main(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None)
