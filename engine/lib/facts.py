"""FACTS — one per-player table per league. Evidence only.

The planner (lib/plan.py) decides; this module only says what is true about each
player the decision could touch: my roster, and every free agent a candidate
producer asks about. Nothing here picks a drop, a spot or a verdict, and nothing
here writes anything (no ledger, no registry, no files) — `Facts.build` reads the
run that ff.build() already assembled; `Facts.from_parts` takes the same pieces
directly so the tests can build a league by hand.

Per player (a `Fact`, a dict with attribute access):

  designation     Yahoo's tag (rules vocabulary); a player whose Kalshi markets were
                  withdrawn before kickoff (steam 'gone') reads 'O' with the reason
  owner / slot    'me' | another manager | None (free agent)
  locked          rules.locked(row): final, live, past kickoff, Yahoo game text, or the
                  week-lock. Yahoo's week-lock: a player whose game has started cannot
                  be dropped, moved or IR'd before the week rolls, so `locked_until` is
                  clock.week_start(W+1). `lock_at` is his kickoff while it is ahead.
  on_waivers      BSB: dropped To Waivers since the last run, or unrostered with his
                  game kicked off this week, or the Tue->Wed claims window — a CLAIM
                  until rules.waiver_run_at(). HH: dropped To Waivers in the last 24h
                  (the league's '1-day' waiver; duration UNVERIFIED).
  recently_added  Caleb added him within 7 days (state.recently_added; this league)
  recently_dropped  Caleb dropped him within 7 days in EITHER league
  registry        hold / handcuff / drop_ok / ir / add_no / add_yes / unavailable / dead
  usage_now/prev  breakout._usage_tier on the scan's usage week and the week before
  pts_w           week W points (the lineup's number: actual/live blend for my players)
  pts_w1, w1_src  week W+1: Sleeper W+1 projection if on disk; DEF re-scored on the W+1
                  opponent implied total; K scaled by own implied total W+1/W; else the
                  rest-of-season per-week value; byes zeroed; a long-term tag zeroes it
  ros_pw, ros_src rest-of-season per-week value: BSB season blend / 17; HH the same
                  rescaled per position by the median HH/BSB score ratio on this week's
                  identical stat lines (APPROXIMATION, labelled); usage-adjusted up to the
                  W projection when this week's usage says starter (a backup's preseason
                  number is stale — gate G6); no season number -> W projection; a tag that
                  zeroed the projection -> the league's positional median (the tag counts
                  for nothing, either direction); a verified dead spot -> 0
  boom            share of points from touchdowns / big plays (score.boom)
  sources, market_ready
"""
import csv, os, json, statistics
from . import clock as C, score as SC, rules as RU
from .names import key as NK, team as NT

REG_END = 17                       # last week the rest-of-season sum runs to (fantasy playoffs incl.)
IR_TAGS = frozenset({'IR', 'IR-R', 'PUP', 'PUP-R'})   # firm IR-slot eligibility; 'O' is ASK (unverified)
HH_WAIVER_H = 24.0                 # HH '1-day' waiver on a dropped player — UNVERIFIED


def _fam(pos):
    from .wire import _fam as F
    return F(pos)


class Fact(dict):
    """A player's facts. Attribute access for reading; it is still a plain dict."""
    __getattr__ = dict.get


class Facts:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, run, league):
        """From the run ff.build() assembled. Reads files the engine already reads; writes nothing."""
        from . import state as ST, usage as U, breakout as BK, fab as F
        R = run['leagues'][league]
        st, P, w, lu = R['state'], run['proj'], R['wire'], R['lineup']
        D = os.path.join(RU.ROOT, 'data') + '/'
        season = json.load(open(D + 'season_blend.json')) if os.path.exists(D + 'season_blend.json') else {}
        bk = R.get('breakout') or {}
        uw = bk.get('week')
        use_now = U.load(uw) if uw else {}
        use_prev = U.load(uw - 1) if uw and uw > 1 else {}
        proj_next = None
        if os.path.exists(D + f'sleeper_off_wk{run["week"] + 1}.csv'):
            try:
                from .project import Projections
                proj_next = Projections(run['week'] + 1)
            except Exception:
                proj_next = None
        fab_left = None
        if league == 'BSB':
            m = F.model()
            fab_left = F.BUDGET - (m.get('spent') or {}).get(st.me, 0)
        gone = {g['key'] for g in (run.get('steam') or {}).get('gone', [])}
        return cls.from_parts(league, st, P, run['week'], C.now(), w, lu, windows=run.get('windows'),
                              season=season, usage_now=use_now, usage_prev=use_prev,
                              recently_added=ST.recently_added(league),
                              recently_dropped=ST.recently_dropped_anywhere(),
                              waived=BK._on_waivers(league) if league == 'BSB' else None,
                              log_rows=_log_rows(league), fab_left=fab_left, proj_next=proj_next,
                              steam_gone=gone, rivals=R.get('rivals'), usage_week=uw)

    @classmethod
    def from_parts(cls, league, state, proj, week, now, wire, lineup, windows=None, season=None,
                   usage_now=None, usage_prev=None, recently_added=None, recently_dropped=None,
                   waived=None, log_rows=None, fab_left=None, proj_next=None, steam_gone=(),
                   rivals=None, usage_week=None):
        f = cls(league=league, state=state, cfg=state.cfg, proj=proj, week=week, now=now, wire=wire,
                lineup=lineup, windows=windows, season=season or {}, usage_now=usage_now or {},
                usage_prev=usage_prev or {}, recently_added_map=dict(recently_added or {}),
                recently_dropped_map=dict(recently_dropped or {}), waived=dict(waived or {}),
                log_rows=list(log_rows or []), fab_left=fab_left, proj_next=proj_next,
                steam_gone=set(steam_gone or ()), rivals=rivals, usage_week=usage_week,
                notes=[], _pool_cache={})
        f._prep()
        return f

    # ------------------------------------------------------------------ internals
    def _prep(self):
        st, cfg = self.state, self.cfg
        w = self.wire
        self.hold = dict(getattr(w, 'hold', {}) or {})
        self.drop_ok = dict(getattr(w, 'drop_ok', {}) or {})
        self.add_yes = dict(getattr(w, 'verified', {}) or {})
        self.blocked = set(getattr(w, 'blocked', set()) or set())
        # byes per week from the posted look-ahead lines (a team with no line that week)
        self.byes = {}
        WN = self.windows
        for t in range(self.week, REG_END + 1):
            self.byes[t] = set(WN.byes(t)) if (WN is not None and WN.have(t)) else set()
        self.rest_weeks = list(range(self.week + 2, REG_END + 1))
        # positional median of every rostered player's W projection in the league
        # (the 'as if healthy' value for a tagged player nobody else prices)
        by = {}
        ratio_pairs = {}
        for r in st.rows:
            fam = _fam(r.get('pos'))
            L = self.proj.line(r['key'], r.get('pos'), r['tm'])
            p = SC.points(L, self.league) if not L.get('unknown') else None
            if p and p > 0 and r.get('designation') not in RU.UNUSABLE:
                by.setdefault(fam, []).append(p)
            if self.league == 'HH' and not L.get('unknown') and L.get('pts_override') is None:
                pb, ph = SC.points(L, 'BSB'), SC.points(L, 'HH')
                if pb and ph and pb > 1.0: ratio_pairs.setdefault(fam, []).append(ph / pb)
        self.posmed = {k: float(statistics.median(v)) for k, v in by.items() if v}
        # HH rest-of-season: the season blend is BSB-scored; rescale per position by the
        # median HH/BSB ratio on identical stat lines this week (APPROXIMATION)
        self.hh_ratio = {k: float(statistics.median(v)) for k, v in ratio_pairs.items() if len(v) >= 3}
        self.week_start_next = C.week_start(self.week + 1)
        # W lineup rows (lineup.solve already attached pts / actual blend)
        lrows = {r['key']: r for r in (self.lineup or {}).get('rows', [])}
        self.mine = {}
        for r in st.mine:
            lr = lrows.get(r['key'], r)
            self.mine[r['key']] = self._fact_from_row(r, lr)
        self.mine_keys = [r['key'] for r in st.mine]
        # league mechanics inputs
        self.ir_used = sum(1 for r in st.mine if r['slot'] == 'IR')
        self.ir_free = max(0, cfg.ir_slots - self.ir_used)
        self.size = len(cfg.slots) + cfg.bench
        self.active = sum(1 for r in st.mine if r['slot'] != 'IR')
        self.open_spots = max(0, self.size - self.active)
        self.week_start_next = C.week_start(self.week + 1)
        # HH: acquisitions used since the most recent Tuesday 07:00 ET (the reset day is
        # NOT documented by Yahoo for this league — UNVERIFIED)
        self.acq_reset = C.week_start(C.nfl_week(self.now)) if C.nfl_week(self.now) >= 1 else C.week_start(1)
        self.acq_used = 0
        from . import ts as T
        for x in self.log_rows:
            if x.get('team') != cfg.name or x.get('action') != 'Add': continue
            t = T.try_ts(x.get('datetime'), 'yahoo_log')
            if t is not None and t >= self.acq_reset: self.acq_used += 1
        self.acq_cap = cfg.acq_cap
        self.acq_left = None if cfg.acq_cap is None else max(0, cfg.acq_cap - self.acq_used)
        # HH '1-day' waiver: dropped To Waivers in the last 24h (duration UNVERIFIED)
        self.hh_waived = {}
        if self.league == 'HH':
            for x in self.log_rows:
                if x.get('action') != 'Drop' or 'waiver' not in (x.get('note') or '').lower(): continue
                t = T.try_ts(x.get('datetime'), 'yahoo_log')
                if t is None: continue
                until = t + C.dt.timedelta(hours=HH_WAIVER_H)
                if until > self.now: self.hh_waived[NK(x['player'])] = until

    def _usage(self, k, which):
        u = (self.usage_now if which == 'now' else self.usage_prev).get(k)
        if not u: return (None, '')
        from .breakout import _usage_tier
        return _usage_tier(u)

    def _registry(self, k, designation):
        h = self.hold.get(k); d = self.drop_ok.get(k)
        dead = bool(d) and designation in RU.LONG_TERM
        return Fact(hold=bool(h), handcuff=(h or {}).get('handcuff_for'), drop_ok=bool(d),
                    ir=str((d or {}).get('ir', '')).lower() in ('true', '1', 'yes'),
                    add_no=(k in self.blocked), add_yes=(self.add_yes.get(k) or {}).get('priority') if k in self.add_yes else None,
                    dead=dead, why=((d or h or {}).get('why') or '')[:160], call=((d or h or {}).get('call') or '')[:160])

    def _ros(self, k, fam, tm, proj_w, designation, dead, usage_now):
        if dead: return 0.0, 'verified dead spot (registry) — 0'
        sb = (self.season.get(k) or {}).get('pts')
        base, src = None, ''
        if sb:
            base = sb / 17.0; src = 'season blend / 17'
            if self.league == 'HH':
                r = self.hh_ratio.get(fam)
                if r: base *= r; src += f' x HH/BSB {fam} ratio {r:.2f} (approximation)'
                else: src += ' (BSB-scored; no HH ratio for the position — approximation)'
        if usage_now == 'start' and proj_w and (base is None or proj_w > base):
            return float(proj_w), f'W projection {proj_w:.1f} (usage says starter; the preseason number is stale)'
        if base is not None: return float(base), src
        if proj_w and proj_w > 0: return float(proj_w), 'W projection (no season number)'
        if designation in RU.TAGGED and fam in self.posmed:
            return self.posmed[fam], f'positional median {self.posmed[fam]:.1f} — tagged {designation}, valued as if healthy'
        return 0.0, 'no number from any source'

    def _w1(self, k, fam, tm, line_w, proj_w, ros, designation, dead, pos=None):
        W1 = self.week + 1
        if tm in self.byes.get(W1, set()): return 0.0, f'bye in week {W1}'
        if dead or designation in RU.LONG_TERM: return 0.0, f'{designation} — long-term designation'
        if self.proj_next is not None:
            L = self.proj_next.line(k, pos or fam, tm)
            if not L.get('unknown'):
                p = SC.points(L, self.league)
                if p is not None: return float(p), f'week-{W1} projection on disk'
        WN = self.windows
        if fam == 'DEF' and line_w and not line_w.get('unknown') and line_w.get('stat') and WN is not None:
            opp = (WN.opp.get(W1) or {}).get(tm)
            if opp is not None:
                L = dict(line_w, stat=dict(line_w['stat'], pts_allow=opp))
                p = SC.points(L, self.league)
                if p is not None: return float(p), f'W line re-scored on the week-{W1} opponent implied total {opp:.1f}'
        if fam == 'K' and proj_w and WN is not None:
            a, b = (WN.own.get(self.week) or {}).get(tm), (WN.own.get(W1) or {}).get(tm)
            if a and b: return float(proj_w * b / a), f'W projection x own implied total {b:.1f}/{a:.1f}'
        return float(ros or 0.0), 'rest-of-season per-week (no week-%d projection on disk — approximation)' % W1

    def _fact_from_row(self, r, lr):
        k = r['key']; fam = _fam(r.get('pos')); tm = r['tm']
        P = self.proj
        line = lr.get('line') or P.line(k, r.get('pos'), tm)
        desig = r.get('designation') or 'none'
        dsrc = 'yahoo'
        kick = lr.get('kick') if lr.get('kick') is not None else P.kickoff(tm)
        if k in self.steam_gone and not (kick and kick <= self.now) and desig not in RU.UNUSABLE:
            desig, dsrc = 'O', 'Kalshi withdrew his markets before kickoff (treated as OUT until Yahoo says otherwise)'
        proj_w = lr.get('proj_pts', lr.get('pts'))
        if proj_w is None and not line.get('unknown'): proj_w = SC.points(line, self.league)
        pts_w = lr.get('pts') if lr.get('pts') is not None else proj_w
        lockrow = dict(lr, kick=kick)
        locked = RU.locked(lockrow, self.now)
        reg = self._registry(k, desig)
        un, unr = self._usage(k, 'now'); up, upr = self._usage(k, 'prev')
        ros, ros_src = self._ros(k, fam, tm, proj_w, desig, reg.dead, un)
        w1, w1_src = self._w1(k, fam, tm, line, proj_w, ros, desig, reg.dead, pos=r.get('pos'))
        return Fact(key=k, name=r['player'], pos=r.get('pos'), fam=fam, tm=tm, elig=set(r.get('elig') or set()),
                    owner='me', slot=r['slot'], designation=desig, designation_src=dsrc,
                    kick=kick, kicked=bool(kick and kick <= self.now), final=bool(lr.get('final')), live=bool(lr.get('live')),
                    locked=locked, locked_until=(self.week_start_next if locked else None),
                    lock_at=(kick if (kick and kick > self.now) else None),
                    on_waivers=None, recently_added=self.recently_added_map.get(k),
                    recently_dropped=self.recently_dropped_map.get(k),
                    registry=reg, usage_now=un, usage_now_rule=unr, usage_prev=up, usage_prev_rule=upr,
                    pts_w=pts_w, proj_w=proj_w, pts_w1=w1, w1_src=w1_src, ros_pw=ros, ros_src=ros_src,
                    boom=lr.get('boom') if lr.get('boom') is not None else (SC.boom(line, self.league) if not line.get('unknown') else None),
                    sources=list(line.get('sources') or []), market_ready=bool(P.market_ready(tm)),
                    line=line, row=r, actual=lr.get('actual'))

    # ------------------------------------------------------------------ queries
    def fa(self, k):
        """Fact for an unrostered player in this league's pool, or None (owned, blocked
        by the phantom audit, or nobody prices him). Pure and cached."""
        if k in self._pool_cache: return self._pool_cache[k]
        e = (getattr(self.wire, 'pool', {}) or {}).get(k)
        if not e or 'fam' not in e or k in self.state.roster_keys:
            self._pool_cache[k] = None; return None
        fam = e['fam']; tm = e['tm']
        line = e.get('line') or {}
        kick = e.get('kick')
        kicked = bool(kick and kick <= self.now)
        proj_w = e.get('week')
        desig = 'none'
        un, unr = self._usage(k, 'now'); up, upr = self._usage(k, 'prev')
        reg = self._registry(k, desig)
        ros, ros_src = self._ros(k, fam, tm, proj_w, desig, False, un)
        w1, w1_src = self._w1(k, fam, tm, line, proj_w, ros, desig, False, pos=e.get('pos'))
        f = Fact(key=k, name=e['name'], pos=e.get('pos'), fam=fam, tm=tm, elig=_elig(e.get('pos'), self.league),
                 owner=None, slot=None, designation=desig, designation_src='pool (no Yahoo tag on file for free agents)',
                 kick=kick, kicked=kicked, final=False, live=False, locked=False, locked_until=None,
                 lock_at=(kick if (kick and kick > self.now) else None),
                 on_waivers=self._waiver_status(k, kicked),
                 recently_added=None, recently_dropped=self.recently_dropped_map.get(k),
                 registry=reg, usage_now=un, usage_now_rule=unr, usage_prev=up, usage_prev_rule=upr,
                 pts_w=proj_w, proj_w=proj_w, pts_w1=w1, w1_src=w1_src, ros_pw=ros, ros_src=ros_src,
                 boom=e.get('boom'), sources=list(line.get('sources') or []), market_ready=bool(e.get('ready')),
                 line=line, entry=e, season=e.get('season'))
        self._pool_cache[k] = f
        return f

    def _waiver_status(self, k, kicked):
        """-> dict(until, why) when the player is a CLAIM right now, else None."""
        if self.league == 'BSB':
            n = self.now; w_now = C.nfl_week(n)
            run_this = RU.waiver_run_at(w_now)
            nxt = run_this if n < run_this else RU.waiver_run_at(w_now + 1)
            if k in self.waived:
                return dict(until=nxt, why=f'dropped to waivers {self.waived[k]} — a claim until the run')
            if n < run_this and w_now >= 1:
                return dict(until=run_this, why='Tue->Wed claims window: last week\'s games are played and the run has not processed')
            if kicked:
                return dict(until=nxt, why='his game has kicked off this week — Yahoo moves an unrostered player to waivers until the Wednesday run')
            return None
        if k in self.hh_waived:
            return dict(until=self.hh_waived[k], why='dropped to waivers in Heritage House within 24h (1-day waiver — duration UNVERIFIED)')
        return None

    def best_fa(self, fam, t, n=3, accept=None):
        """Top-n free agents at a family by their value in week t (W, W+1, or rest)."""
        out = []
        fams = [fam] if accept is None else sorted(accept)
        seen = set()
        for fm in fams:
            for e in (getattr(self.wire, 'by_fam', {}) or {}).get(fm, []):
                if e['key'] in seen: continue
                seen.add(e['key'])
                if e.get('week') is None and e.get('season') is None: continue
                f = self.fa(e['key'])
                if f is None: continue
                v = self.value(f, t)
                if v is None or v <= 0: continue
                out.append((v, f['key'], f))
        out.sort(key=lambda x: (-x[0], x[1]))
        return [f for _, _, f in out[:n]]

    def value(self, f, t):
        """A player's points in week t: W (the lineup number, None if he cannot start),
        W+1, or a rest week (per-week value, 0 on a bye)."""
        if t == self.week:
            if f.designation in RU.UNUSABLE and not (f.locked and f.slot not in (None, 'BN', 'IR')): return None
            return f.pts_w
        if t == self.week + 1: return f.pts_w1
        if f.tm in self.byes.get(t, set()): return 0.0
        if f.registry and f.registry.dead: return 0.0
        return f.ros_pw

    def all_facts(self):
        return list(self.mine.values()) + [v for v in self._pool_cache.values() if v]

    # ------------------------------------------------------------------ gates (read-only)
    def posted_lines_next(self):
        """Week W+1 look-ahead lines are on disk (the DEF/K matchup evidence: 'vegas')."""
        return self.windows is not None and self.windows.have(self.week + 1)

    def gate_add(self, f, horizon=None, usage=None, extra_sources=()):
        w = self.wire
        if w is None or not hasattr(w, 'gate_add') or f.get('entry') is None: return None
        horizon = horizon or ('weekly' if f.fam in ('DEF', 'K') else 'season')
        return w.gate_add(f['entry'], horizon=horizon, usage=usage, extra_sources=extra_sources)

    def gate_drop(self, f):
        w = self.wire
        if w is None or not hasattr(w, 'gate_drop'): return None
        u = self.usage_now.get(f.key)
        usage_txt = None
        if u:
            from .breakout import _usage_role
            ur = _usage_role(dict(key=f.key), self.usage_now)
            usage_txt = ur[0] if ur else None
        row = dict(f.row, line=f.line, pts=f.pts_w)
        # a DEF/K is a matchup slot (G4): with next week's posted lines on disk the
        # matchup itself is the second evidence family, as the stream calls always said
        extra = ['vegas'] if (f.fam in ('DEF', 'K') and self.posted_lines_next()) else []
        return w.gate_drop(row, usage=usage_txt, horizon='weekly' if f.fam in ('DEF', 'K') else 'season', extra_sources=extra)


def _elig(pos, league):
    from .state import _elig as E
    return E(pos or '', league)


def _log_rows(league):
    p = os.path.join(RU.ROOT, 'data', 'bsb_transactions.csv' if league == 'BSB' else 'hh_transactions.csv')
    if not os.path.exists(p): return []
    try: return list(csv.DictReader(open(p)))
    except Exception: return []
