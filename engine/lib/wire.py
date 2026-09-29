"""ONE WIRE, both leagues. Pool by subtraction, audited, usage-gated.

The free-agent pool is (every player any source projects) minus (every player on
any roster in the league). That sidesteps Yahoo's broken players page. It also
means two things MUST run before the pool is used, every time:

  1. audit_phantoms  -- catches a rostered player hiding under another spelling
                        (Kenneth/Kenny Gainwell) without eating real free agents
                        (Josh Hines-Allen is not Josh Allen)
  2. the role registry -- a projection is not evidence a player is on the field.
                        Bernard (3 snaps), Ty Johnson (RB3, hurt), Tyson (IR).

Ranking rule: a player with VERIFIED usage sorts ahead of a higher projection
with none. A snap count is an observation; a projection is a forecast.
"""
import json, os
from collections import defaultdict
from . import score as SC, clock as C, gate as G
from .names import key, team, audit_phantoms

D = '/home/claude/bsb2/data/'

def roles():
    try: return json.load(open(D + 'roles.json'))
    except Exception: return {}

def _fam(pos):
    p = (pos or '').upper().split(',')[0].strip()
    return {'DE':'DL','DT':'DL','NT':'DL','DL':'DL','LB':'LB','OLB':'LB','ILB':'LB','MLB':'LB',
            'CB':'DB','S':'DB','FS':'DB','SS':'DB','DB':'DB'}.get(p, p)

TAGGED = {'O','Q','D','IR','IR-R','NA','PUP','PUP-R','SUSP','CEL'}
LONG_TERM = {'IR','IR-R','NA','PUP','PUP-R','SUSP','CEL'}

class Wire:
    def __init__(self, state, proj, season=None):
        """season: optional {key: {'pts','pos','name','tm','n'}} season blend (BSB)."""
        self.state, self.proj, self.league = state, proj, state.league
        R = roles()
        self.blocked = set(R.get('unavailable', {})) | {k for k in R.get('add_no', {}) if not k.startswith('_')}
        self.verified = {k: v for k, v in R.get('add_yes', {}).items() if not k.startswith('_')}
        self.hold = R.get('hold', {})
        self.drop_ok = R.get('drop_ok', {})

        # candidate universe: everyone with a weekly line or a season projection
        cands = {}
        for k, r in proj.off.items():
            cands[k] = dict(name=r['player'], tm=team(r['team']), pos=(r['pos'] or '').upper())
        for k, r in proj.idp.items():
            cands[k] = dict(name=r['player'], tm=team(r['team']), pos=(r['pos'] or '').upper())
        if season:
            for k, v in season.items():
                cands.setdefault(k, dict(name=v['name'], tm=team(v.get('tm', '')), pos=v['pos']))
        self.season = season or {}

        pool = {k: v for k, v in cands.items() if k not in state.roster_keys and k not in self.blocked}
        meta = {k: {'tm': v['tm'], 'pos': v['pos']} for k, v in cands.items()}
        meta.update({r['key']: {'tm': r['tm'], 'pos': r['pos']} for r in state.rows})
        self.phantoms, self.near = audit_phantoms(set(pool), state.roster_keys, meta=meta)
        for a, _, _, _ in self.phantoms: pool.pop(a, None)
        self.pool = pool
        self.meta = meta

        # score every pool player under this league's rules
        self.by_fam = defaultdict(list)
        for k, v in pool.items():
            fam = _fam(v['pos'])
            if self.league == 'BSB' and fam in ('DL','LB','DB'): continue
            L = proj.line(k, v['pos'], v['tm'])
            wk = SC.points(L, self.league)
            sea = self.season.get(k, {}).get('pts')
            v.update(fam=fam, line=L, week=wk, season=sea, boom=SC.boom(L, self.league),
                     verified=(k in self.verified), key=k,
                     kick=proj.kickoff(v['tm']), ready=proj.market_ready(v['tm']))
            self.by_fam[fam].append(v)
        for fam in self.by_fam:
            # verified usage first; then season for skill positions, week for DEF/K
            self.by_fam[fam].sort(key=lambda v: (not v['verified'],
                                                 self.verified.get(v['key'], {}).get('priority', 99) if v['verified'] else 99,
                                                 -(v['season'] or 0) if fam not in ('DEF','K') else -(v['week'] or 0),
                                                 -(v['week'] or 0)))

    def best(self, fam, n=5):
        return self.by_fam.get(fam, [])[:n]

    def replacement(self, fam):
        b = self.best(fam, 1)
        return b[0] if b else None

    # ------------------------------------------------------------ boards
    def upgrade_board(self, lineup):
        """Weekly: best FA vs weakest CURRENT STARTER at each family. DEF/K live here."""
        out = []
        cur = lineup['current']
        for fam, slots in self.state.cfg.fam_slots.items():
            holders = [cur[s] for s in slots if cur.get(s) and cur[s].get('pts') is not None
                       and _fam(cur[s]['pos']) == fam
                       and not (cur[s].get('final') or cur[s].get('live') or cur[s].get('phase') == 'locked')]   # already played: not a slot to fill (Lloyd/Perine 09-26)
            if not holders or not self.by_fam.get(fam): continue
            worst = min(holders, key=lambda x: x['pts'])
            for cand in self.best(fam, 3):
                if cand['week'] is None: continue
                gain = cand['week'] - worst['pts']
                if gain <= 1.5: continue
                out.append(dict(fam=fam, add=cand, over=worst, gain=gain, horizon='weekly'))
        out.sort(key=lambda x: -x['gain'])
        return out

    def bench_board(self, lineup):
        """Roster construction: bench spots worth less than the wire on BOTH mean and
        upside. DEF/K excluded -- they are weekly matchup slots."""
        out = []
        bench = [r for r in lineup['rows'] if r['slot'] == 'BN']
        for r in bench:
            fam = _fam(r['pos'])
            if fam in ('DEF', 'K') or not self.by_fam.get(fam): continue
            if r['key'] in self.hold: continue
            mine_sea = self.season.get(r['key'], {}).get('pts')
            mine_wk = r.get('pts')
            dead = self.dead_spot(r)
            for cand in self.best(fam, 2):
                if not cand['verified'] and not dead: continue     # no usage row, no add
                # compare on season when both have it, else week
                if mine_sea is not None and cand['season'] is not None:
                    gain = cand['season'] - (0.0 if dead else mine_sea); basis = 'season'
                elif cand['week'] is not None and mine_wk is not None:
                    gain = cand['week'] - (0.0 if dead else mine_wk); basis = 'week'
                else: continue
                if gain <= 3 and not dead: continue
                # upside: do not swap a boom dart for a floor
                if (r.get('boom') or 0) > (cand.get('boom') or 0) + 0.15 and not dead: continue
                out.append(dict(fam=fam, add=cand, drop=r, gain=gain, basis=basis, dead=dead))
        out.sort(key=lambda x: (-x['dead'], -x['gain']))
        # A CLAIM PLAN, not a cross product. Drops are ordered dead-first then by
        # value; each takes the best remaining verified add in registry priority.
        # Four (drop, add) combos become the two claims a person would submit.
        plan, used_drop, used_add = [], set(), set()
        for x in out:
            if x['drop']['key'] in used_drop or x['add']['key'] in used_add: continue
            plan.append(x); used_drop.add(x['drop']['key']); used_add.add(x['add']['key'])
        return plan

    # ------------------------------------------------------------ streaming
    def stream_board(self, week, windows):
        """DEF and K for a FUTURE week, priced off posted lines. In an uncapped
        league the unclaimed pool is free and first-come the moment waivers run,
        so the best next-week matchup is worth taking NOW, not on Tuesday.
        DEF is ranked on the OPPONENT's implied total (lower is better);
        K on his OWN team's implied total (higher is better)."""
        own, opp = windows.own.get(week, {}), windows.opp.get(week, {})
        if not own: return None
        out = {}
        for fam, table, better in (('DEF', opp, min), ('K', own, max)):
            mine = [r for r in self.state.mine if _fam(r['pos']) == fam]
            rows = []
            for r in mine:
                v = table.get(r['tm'])
                rows.append(dict(name=r['player'], tm=r['tm'], val=v, mine=True, slot=r['slot'],
                                 bye=(v is None)))
            for c in self.by_fam.get(fam, []):
                v = table.get(c['tm'])
                if v is None: continue
                rows.append(dict(name=c['name'], tm=c['tm'], val=v, mine=False, key=c['key']))
            rows.sort(key=lambda x: (x['val'] is None, x['val'] if fam == 'DEF' else -(x['val'] or 0)))
            best_mine = [x for x in rows if x['mine'] and x['val'] is not None]
            best_mine = best_mine[0] if best_mine else None
            best_fa = next((x for x in rows if not x['mine']), None)
            edge = None
            if best_mine and best_fa:
                edge = (best_mine['val'] - best_fa['val']) if fam == 'DEF' else (best_fa['val'] - best_mine['val'])
            out[fam] = dict(rows=rows[:8], best_mine=best_mine, best_fa=best_fa, edge=edge,
                            byes=[x['name'] for x in rows if x['mine'] and x['val'] is None])
        return out

    # ------------------------------------------------------------ gate
    def gate_add(self, cand, horizon='season', usage=None):
        # value is judged against the horizon's bounds. A player with no season
        # number is NOT a weekly number stretched to a season (Wentz 09-17: 15.65
        # weekly read against [60,600] season bounds -> false G6 block); G6 is
        # simply skipped and G5 still speaks to how many sources priced him.
        v = cand['season'] if horizon == 'season' else cand['week']
        # sources = everything that produced a number for him: the weekly line,
        # the season blend's named feeds, and verified usage. A player below
        # Sleeper's weekly cut but on FFToday's season table is not "no source".
        src = list(cand['line']['sources'])
        sb = self.season.get(cand['key'], {})
        if sb.get('ff') is not None: src.append('fftoday')
        if sb.get('rw') is not None: src.append('sleeper')
        if cand['verified']: src.append('usage')
        # the weekly usage pull is an independent observation of the role (snaps,
        # targets), not a projection: when it is what put him on the scan it is a
        # second source family. Without it every add between the week's last kickoff
        # and Thursday's ladders is 'single source' by construction (Mon 09-28: every
        # Tier-B row BLOCKED with an open roster spot to fill).
        if usage and 'usage' not in src and any(t in usage for t in ('snaps', 'targets', 'touches', 'started')): src.append('usage')
        return G.check('add', f'add {cand["name"]}', player=cand['name'],
                       designation='none' if cand['key'] not in self.blocked else 'IR',
                       sources=src, pos=cand['fam'], value=v, horizon=horizon,
                       market_ready=cand['ready'], roster_keys=self.state.roster_keys,
                       pool_keys=set(self.pool), pool_meta=self.meta,
                       pulled=C.today().isoformat(), league=self.league, state=self.state,
                       usage=usage)

    def gate_drop(self, row, horizon='season', usage=None):
        k = row['key']
        h = self.hold.get(k); d = self.drop_ok.get(k)
        role = (d['why'] if d else (h['why'] if h else None))
        # the weekly usage pull is a depth-chart observation too (G3 wants one):
        # "bench WR, 12% of snaps" is a role, and so is "57% of snaps, 20% of
        # targets" -- the second one makes him a WARN to drop, not a free spot.
        if role is None and usage: role = f'week pull: {usage}'
        dead = self.dead_spot(row)
        if dead: role = role or 'not on an NFL depth chart (IR/exempt), verified in the registry'
        v = (row.get('pts') or 0) if horizon == 'weekly' else self.season.get(k, {}).get('pts', row.get('pts') or 0)
        if dead: v = 0.0
        # sources: whatever actually priced him (the weekly line names its own
        # families -- vegas+sleeper for a DEF), plus the registry if it speaks
        src = list((row.get('line') or {}).get('sources') or ['sleeper'])
        if d or h or usage: src.append('usage')
        g = G.check('drop', f'drop {row["player"]}', player=row['player'],
                    designation=row['designation'], sources=src,
                    pos=_fam(row['pos']), value=v, horizon=horizon, role=role,
                    handcuff_for=(h or {}).get('handcuff_for'),
                    pulled=C.today().isoformat(), league=self.league, state=self.state)
        # Caleb, 2026-09-21: "You are telling me to drop control of players and you
        # have no idea why they missed one week. That's horrible roster management."
        # A tag is a fact about ONE week. Nothing is a drop because of a tag until
        # the registry records what it is and how long (roles.json drop_ok).
        if row['designation'] in TAGGED and not dead:
            # the tag itself is never the reason: value is his SEASON number as if
            # healthy, and the drop must stand on that alone (Pierce 09-23: D-tagged
            # AND the lowest-valued bench player either way).
            g.add('G13-injury', G.WARN, f'tagged {row["designation"]} — why and for how long is NOT on record; the tag counts for nothing here, the drop stands on his season value alone')
        # Caleb, 2026-09-27: "QBs are too valuable in superflex though compared to a
        # flyer WR." In a league with a QB-eligible flex, every QB up to one past the
        # QB-eligible slots is depth that starts on bye weeks and prices in trade;
        # he is never the spot for a non-QB add. A fourth QB is fair game.
        if _fam(row['pos']) == 'QB' and not dead and k not in self.drop_ok:
            qb_slots = self.superflex_qb_slots()
            if qb_slots >= 2:
                n_qb = sum(1 for r in self.state.mine if _fam(r['pos']) == 'QB' and r['slot'] != 'IR' and r['designation'] not in ('IR','IR-R','O','NA','PUP','PUP-R','SUSP','CEL'))
                if n_qb <= qb_slots + 1:
                    g.add('G14-superflex', G.BLOCK, f'superflex: {n_qb} QBs for {qb_slots} QB-eligible slots — QB{n_qb} is bye-week and trade depth, not a spot for a non-QB add (Caleb 09-27)')
        return g

    def superflex_qb_slots(self):
        """Number of slots a QB can fill in this league (2+ means superflex)."""
        cfg = self.state.cfg
        return sum(1 for s_ in cfg.slots if 'QB' in cfg.accepts.get(s_, set()))

    def dead_spot(self, row):
        """A roster spot worth zero: a long-term designation AND a registry entry
        (drop_ok) that says what it is and how long. A tag alone is never enough."""
        return row['designation'] in LONG_TERM and row['key'] in self.drop_ok
