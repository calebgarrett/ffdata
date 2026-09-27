"""RIVALS — how the other managers actually behave, from the league's own logs.

The pump writes every transaction in both leagues (who added whom, when, for how
much) and every roster. From that, per manager:

  activity    adds, waiver claims, free-agent pickups, adds in the last 7 days
  money       BSB: FAB spent, remaining, the bids he has won (max, median)
  habits      positions he adds; whether he streams DEF/K week to week
  need        which position families his roster is thin at right now — the
              weakest starter below the league's median starter at that family,
              or a starter who is out

A bid recommendation follows: the managers likely to be in on a player are the
ones with a need at his position, FAB to spend, and a history of bidding. The
bid to beat is the largest winning bid any of THEM has paid, plus one, floored at
the tier band and capped at the contested band. When nobody with a need has ever
bid, the floor is the number — the flat Tier-A band was overpaying.

Everything here is observed. Nothing infers intent from a name.
"""
import csv, os, datetime as dt
from collections import defaultdict
from statistics import median
from . import clock as C, score as SC, fab as F
from .wire import _fam
from .names import key

D = '/home/claude/bsb2/data/'
UNUSABLE = {'IR', 'IR-R', 'O', 'NA', 'PUP', 'PUP-R', 'SUSP', 'CEL'}

def _log(league):
    p = D + ('bsb_transactions.csv' if league == 'BSB' else 'hh_transactions.csv')
    if not os.path.exists(p): return []
    out = []
    for r in csv.DictReader(open(p)):
        try: t = dt.datetime.strptime(r['datetime'], '%Y-%m-%d %H:%M').replace(tzinfo=C.ET)
        except Exception: continue
        out.append(dict(r, t=t))
    return out

def need_map(state, proj, lineups=None):
    """{owner: {fam: (weakest starter week pts, league median at fam, reason)}} — only fams where the team is thin."""
    lg = state.league
    starters = defaultdict(lambda: defaultdict(list))     # owner -> fam -> [pts]
    outs = defaultdict(set)
    for r in state.rows:
        if r['slot'] in ('BN', 'IR'): continue
        fam = _fam(r['pos'])
        if r['designation'] in UNUSABLE:
            outs[r['owner']].add(fam); continue
        L = proj.line(r['key'], r['pos'], r['tm'])
        pts = SC.points(L, lg) if not L.get('unknown') else None
        if pts is not None: starters[r['owner']][fam].append(pts)
    fams = {f for o in starters for f in starters[o]}
    med = {}
    for f in fams:
        allv = [min(v) for o in starters for fam_, v in starters[o].items() if fam_ == f and v]
        med[f] = median(allv) if allv else None
    need = defaultdict(dict)
    for o in state.by_owner:
        for f in fams:
            v = starters[o].get(f)
            weak = min(v) if v else None
            if f in outs[o]:
                need[o][f] = (weak, med.get(f), 'a starter is out'); continue
            if weak is not None and med.get(f) is not None and weak < 0.8 * med[f]:
                need[o][f] = (weak, med[f], f'weakest starter {weak:.1f} vs league median {med[f]:.1f}')
    return dict(need), med

def profiles(state, proj):
    """-> {owner: dict(adds, claims, fa, recent, spent, remaining, bids, max_bid, med_bid, pos, streams_def, need)}"""
    lg = state.league
    log = _log(lg)
    now = C.now()
    P = {o: dict(owner=o, adds=0, claims=0, fa=0, recent=0, drops=0, bids=[], pos=defaultdict(int), def_adds=0, k_adds=0)
         for o in state.by_owner}
    for r in log:
        o = r['team']
        if o not in P: P[o] = dict(owner=o, adds=0, claims=0, fa=0, recent=0, drops=0, bids=[], pos=defaultdict(int), def_adds=0, k_adds=0)
        p = P[o]
        if r['action'] == 'Add':
            p['adds'] += 1
            if (r.get('note') or '').strip().lower() == 'waiver':
                p['claims'] += 1
                if r.get('bid') not in ('', None): p['bids'].append(int(r['bid']))
            else: p['fa'] += 1
            if (now - r['t']).days < 7: p['recent'] += 1
            p['pos'][r.get('pos') or '?'] += 1
            if r.get('pos') == 'DEF': p['def_adds'] += 1
            if r.get('pos') == 'K': p['k_adds'] += 1
        elif r['action'] == 'Drop': p['drops'] += 1
    fab = F.model() if lg == 'BSB' else None
    need, med = need_map(state, proj)
    for o, p in P.items():
        p['spent'] = (fab or {}).get('spent', {}).get(o, 0) if fab else None
        p['remaining'] = (F.BUDGET - p['spent']) if fab else None
        p['max_bid'] = max(p['bids']) if p['bids'] else None
        p['med_bid'] = median(p['bids']) if p['bids'] else None
        p['streams_def'] = p['def_adds'] >= 2
        p['need'] = need.get(o, {})
        p['pos'] = dict(p['pos'])
        p['me'] = (o == state.me)
    return dict(profiles=P, need_median=med, log_n=len(log), league=lg,
                first=min((r['t'] for r in log), default=None), last=max((r['t'] for r in log), default=None))

def bid_for(prof, fam, tier, fab=None):
    """-> dict(bid, competitors=[owner...], why) for a BSB claim at `fam` of `tier` (A/B/contested).
    The field: managers thin at the position, plus the habitual bidders (two or more
    claims, or a bid of $5+ on the log) who bid on anything good. The bid clears the
    most any of them has paid; bounded by the Tier-B floor and the contested cap."""
    fab = fab or F.model()
    bands = fab.get('bands') or {}
    floor = (bands.get('B') or {}).get('bid', 1)
    cap = (bands.get('contested') or {}).get('bid', 99)
    P = prof['profiles']
    comp = []
    for o, p in P.items():
        if p['me']: continue
        habitual = p['claims'] >= 2 or (p['max_bid'] or 0) >= 5
        if fam not in p['need'] and not habitual: continue
        if (p['remaining'] or 0) < floor: continue
        comp.append(dict(p, why=('thin at ' + fam) if fam in p['need'] else 'bids on anything good'))
    # what each of them would pay: his usual bid (median, two or more claims) or,
    # on one claim, his max if he is thin at the position and 60% of it if he is
    # merely a habitual bidder — one $25 on a player he wanted is not a habit
    paid = []
    for p in comp:
        if not p['bids']: continue
        rep = p['med_bid'] if len(p['bids']) >= 2 else p['max_bid']
        if len(p['bids']) == 1 and fam not in p['need']: rep = round(0.6 * rep)
        p['rep'] = int(rep); paid.append(int(rep))
    # a claim on a Tier-A player is expected to be contested by these managers; a
    # Tier-B (unpriced) player is invisible to them and takes the floor
    if tier == 'B' or not comp:
        return dict(bid=floor, competitors=[p['owner'] for p in comp], floor=floor, cap=cap,
                    why=('an unpriced role nobody else\'s model is looking at yet; the floor is the number' if tier == 'B' else f'nobody thin at {fam} and no habitual bidder with FAB left — the floor is the number'))
    bid = min(max(floor, (max(paid) + 1) if paid else floor), cap)
    top = sorted([p for p in comp if p.get('rep') is not None], key=lambda p: -p['rep'])[:4]
    who = ', '.join(f"{p['owner']} ({p['why']}; ${p['remaining']} left, priced at ${p['rep']}" + (f" from one ${p['max_bid']} claim)" if len(p['bids']) == 1 else f" from {len(p['bids'])} claims)") for p in top)
    return dict(bid=bid, competitors=[p['owner'] for p in comp], floor=floor, cap=cap,
                why=f'clears what the likely field would pay. Field of {len(comp)}, led by {who}')

def fmt(prof):
    P = prof['profiles']; lg = prof['league']
    L = [f"RIVALS — {lg}: {prof['log_n']} logged transactions" + (f" ({prof['first']:%b %-d} → {prof['last']:%b %-d})" if prof['first'] else '')]
    for o, p in sorted(P.items(), key=lambda kv: (-(kv[1]['spent'] or 0), -kv[1]['adds'])):
        money = f"FAB ${p['spent']}/{p['remaining']} left, max ${p['max_bid']}, median ${p['med_bid']:.0f}" if p['spent'] is not None and p['bids'] else (f"FAB ${p['spent']}/{p['remaining']} left" if p['spent'] is not None else '')
        need = ', '.join(f"{f} ({why})" for f, (w_, m_, why) in p['need'].items()) or 'none'
        L.append(f"  {o[:24]:24} adds {p['adds']:2} (claims {p['claims']}, FA {p['fa']}, last 7d {p['recent']})  {money:44}  streams DEF: {'yes' if p['streams_def'] else 'no'}  thin at: {need}")
    return '\n'.join(L)
