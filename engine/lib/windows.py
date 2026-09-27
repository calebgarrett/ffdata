"""Market-priced schedule windows from posted look-ahead lines.

Implied team total = (over/under +/- spread) / 2, favourite takes the plus.
Three windows: near (3-9), qualifying (10-14), playoff (15-17). For IDP the
number that matters is the OPPONENT's implied total (a tackle needs an opposing
play), so both are returned. Look-ahead lines are real prices posted at low
limits: use the ORDERING, never a one-point gap.
"""
import csv, os
from collections import defaultdict
import numpy as np
from .names import team

D = '/home/claude/bsb2/data/'
NEAR, QUAL, PLAY = tuple(range(3, 10)), tuple(range(10, 15)), (15, 16, 17)

def load():
    own = defaultdict(dict); opp = defaultdict(dict)
    for fn in ('lines_wk3_9.csv', 'lines_wk10_18.csv'):
        p = D + fn
        if not os.path.exists(p): continue
        for r in csv.DictReader(open(p)):
            try: tot = float(r['over_under']); sp = float(r['spread'] or 0)
            except ValueError: continue
            w = int(r['week']); a, h = team(r['away']), team(r['home']); fav = team(r['favorite'])
            ih, ia = ((tot + sp) / 2, (tot - sp) / 2) if fav == h else ((tot - sp) / 2, (tot + sp) / 2)
            own[w][a] = ia; own[w][h] = ih; opp[w][a] = ih; opp[w][h] = ia
    return own, opp

class Windows:
    def __init__(self):
        self.own, self.opp = load()
        self.teams = sorted({t for w in self.own for t in self.own[w]})
        self.weeks = sorted(self.own)
    def _avg(self, table, weeks, t):
        v = [table[w][t] for w in weeks if w in table and t in table[w]]
        return float(np.mean(v)) if v else None
    def env(self, t, weeks=PLAY, idp=False):
        return self._avg(self.opp if idp else self.own, weeks, team(t))
    def rank(self, t, weeks=PLAY, idp=False):
        table = self.opp if idp else self.own
        vals = {x: self._avg(table, weeks, x) for x in self.teams}
        vals = {x: v for x, v in vals.items() if v is not None}
        order = sorted(vals, key=lambda x: -vals[x])
        return (order.index(team(t)) + 1) if team(t) in vals else None, len(vals)
    def bye(self, t):
        return [w for w in self.weeks if team(t) not in self.own.get(w, {})]
    def byes(self, w):
        return sorted(set(self.teams) - set(self.own.get(w, {})))
    def have(self, w): return w in self.own
