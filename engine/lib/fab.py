"""FAB MODEL — what a waiver claim actually costs in BSB, from the league's own log.

BSB: $100 FAB, no acquisition cap, claims process Wednesday ~05:08 ET. Yahoo's
transactions page shows the winning bid on every processed claim, so the
league's bidding behaviour is observable. Twelve managers, several of them
running the same AI, converge on the same names; the price of a name is set by
the one manager who wants it most, not by the crowd. So the model is simple and
literal: the ladder of winning bids so far, who paid them, and what is left.

Nothing here predicts a bid. It reports the ladder and names the bands a bid
has to clear, and it says how many claims the ladder rests on.
"""
from . import paths as _paths
import csv, os
from collections import defaultdict
from statistics import median

D = _paths.data('')
BUDGET = 100

def load():
    p = D + 'bsb_transactions.csv'
    if not os.path.exists(p): return []
    return list(csv.DictReader(open(p)))

def model():
    rows = load()
    claims = [r for r in rows if r['note'].strip().lower() == 'waiver' and r['bid'] != '']
    bids = sorted(int(r['bid']) for r in claims)
    by_mgr = defaultdict(list)
    for r in claims: by_mgr[r['team']].append(int(r['bid']))
    spent = {m: sum(v) for m, v in by_mgr.items()}
    runs = sorted({r['datetime'][:10] for r in claims})
    out = dict(n=len(bids), bids=bids, runs=runs, by_mgr=dict(by_mgr), spent=spent,
               remaining={m: BUDGET - s for m, s in spent.items()})
    if not bids:
        out.update(floor=None, typical=None, whale=None, bands={}); return out
    # bands: what a bid has to clear
    #   floor    -- wins any uncontested claim ($0 has won; $1 beats every $0)
    #   typical  -- beats every winning bid so far except the single largest
    #   whale    -- the largest winning bid and who paid it
    top = bids[-1]
    rest = bids[:-1]
    whale_mgr = next(r['team'] for r in claims if int(r['bid']) == top)
    out.update(floor=1, typical=(max(rest) + 1) if rest else 1, whale=top, whale_mgr=whale_mgr,
               med=median(bids))
    out['bands'] = {
        'B': dict(bid=out['floor'], why='usage the market has not priced; nobody else\'s model is looking yet'),
        'A': dict(bid=out['typical'], why=f'beats every winning bid on the log except {whale_mgr}\'s ${top}'),
        'contested': dict(bid=top + 1, why=f'only if the crowd column says the room already knows; {whale_mgr} has paid ${top} once'),
    }
    return out

def fmt(m):
    if not m['n']: return 'FAB: no processed claims on the log yet'
    L = [f"FAB LADDER — {m['n']} winning bids across {len(m['runs'])} run(s): " + ', '.join(f'${b}' for b in m['bids'])]
    L.append(f"  bands: Tier B ${m['bands']['B']['bid']} · Tier A ${m['bands']['A']['bid']} · contested ${m['bands']['contested']['bid']}   (median winning bid ${m['med']:.0f}; whale {m['whale_mgr']} ${m['whale']})")
    L.append('  spent / remaining: ' + ', '.join(f"{k} ${v}/{m['remaining'][k]}" for k, v in sorted(m['spent'].items(), key=lambda kv: -kv[1])))
    return '\n'.join(L)
