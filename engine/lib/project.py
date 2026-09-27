"""ONE PROJECTION LAYER — stat lines with provenance, market first.

The unifying idea: markets and projections describe STAT LINES (receptions,
yards, touchdowns, tackles). Leagues turn stat lines into points. So one layer
builds the best available stat line for every player, says where each field came
from, and both leagues score the same line under their own rules. A Kalshi ladder
that says LaPorta catches 4.24 balls is 4.24 points in BSB and 3.82 in HH -- one
number, one source, two scorers, no divergence.

Source priority, fixed (Caleb: "leaning towards Vegas or market odds"):
  1. Kalshi strike ladders  -- price is probability; a ladder is a distribution
  2. Vegas game lines       -- implied team totals; the only DEF/K signal that matters
  3. DraftKings props       -- line only, no price; median->mean corrected
  4. Sleeper (Rotowire)     -- the projection tail, and the ONLY IDP source

What this layer refuses to do:
  - return 0.00 for a player nobody covers. It returns unknown=True. (Ridley, 09-15)
  - mix a market number into a projection without saying so in `prov`.
  - pretend a Sunday market exists on a Tuesday. `market_ready` is per game.
"""
import csv, os
from collections import defaultdict
from . import market as M, clock as C
from .names import key, team

D = '/home/claude/bsb2/data/'

def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

class Projections:
    def __init__(self, week):
        self.week = week
        W = str(week)
        # ---- offense stat lines (the richer pull, with pass_att/cmp/sack)
        self.off = {}
        for fn in (f'sleeper_off_wk{W}.csv', f'sleeper_wk{W}.csv'):
            p = D + fn
            if not os.path.exists(p): continue
            for r in csv.DictReader(open(p)):
                k = key(r['player'])
                if k in self.off and fn.startswith('sleeper_wk'): continue   # richer file wins
                self.off[k] = r
        # ---- IDP
        self.idp = {}
        p = D + f'sleeper_idp_wk{W}.csv'
        if os.path.exists(p):
            for r in csv.DictReader(open(p)): self.idp[key(r['player'])] = r
        # ---- markets
        self.games = M.load_games(D + 'espn_games.csv') if os.path.exists(D + 'espn_games.csv') else []
        self.ctx = M.team_context(self.games) if self.games else {}
        self.kal = M.load_kalshi(D + 'kalshi.csv') if os.path.exists(D + 'kalshi.csv') else {}
        self.props = M.load_props(D + 'espn_props.csv') if os.path.exists(D + 'espn_props.csv') else {}
        # ---- WEEK GUARD: a ladder or a game line from another week is never
        # applied to this one (week-2 tickers on disk on a week-3 Wednesday would
        # otherwise price Sunday's players off last Sunday's markets).
        w0, w1 = C.week_start(week), C.week_start(week + 1)
        self.games = {kk: g for kk, g in self.games.items()
                      if (lambda t: t is not None and w0 <= t < w1)(C.parse_kick(g.get('kickoff')))}
        self.ctx = M.team_context(self.games) if self.games else {}
        in_week, in_week_events = set(), set()
        if os.path.exists(D + 'kalshi.csv'):
            import datetime as _dt
            for r in csv.DictReader(open(D + 'kalshi.csv')):
                try:
                    d = _dt.datetime.strptime(r['event'].split('-', 1)[1][:7], '%y%b%d').replace(tzinfo=w0.tzinfo)
                except Exception: continue
                if w0 <= d + _dt.timedelta(hours=12) < w1 + _dt.timedelta(hours=12):
                    nm = r['title'].split(':', 1)[0].strip() if ':' in r['title'] else ''
                    in_week.add((key(nm), r['series'])); in_week_events.add(r['event'])
        self.kal_dropped = len([1 for kk in self.kal if kk not in in_week])
        self.kal = {kk: v for kk, v in self.kal.items() if kk in in_week}
        self.in_week_events = in_week_events
        # ---- game lines FROM KALSHI (spread + total ladders, 09-24): same pull as the
        # props, every game, a distribution not a number. They override the
        # ESPN/look-ahead figures; the schedule (kickoffs) still comes from those.
        from .names import DST_FULL as _DF
        self.kal_games = {}
        if os.path.exists(D + 'kalshi.csv'):
            kg = M.load_kalshi_games(D + 'kalshi.csv', set(_DF))
            tails = {e.split('-', 1)[1] for e in in_week_events}
            for (a, h), g in kg.items():
                if g['tail'] not in tails: continue               # not this week's game
                self.kal_games[(a, h)] = g
                if (a, h) in self.games:
                    self.games[(a, h)].update(total=g['total'], spread=g['spread'], fav=g['fav'], implied=g['implied'], src='kalshi')
                else:
                    self.games[(a, h)] = dict(g, kickoff=None, event_id='')
            self.ctx = M.team_context(self.games) if self.games else {}
        # DraftKings/ESPN props carry no date: the file is this week's only if it
        # was written after the week began.
        if self.props and os.path.getmtime(D + 'espn_props.csv') < w0.timestamp(): self.props = {}
        # ---- Yahoo projections copied off the matchup page: a points-only,
        # league-scored, single-source fallback for players no market or Sleeper
        # line covers this week. Labelled 'yahoo'; the gate treats it as one family.
        self.yahoo = {}
        for lg in ('BSB', 'HH'):
            p = D + f'yahoo_{lg}_wk{W}.csv'
            if not os.path.exists(p): continue
            for r in csv.DictReader(open(p)):
                try: self.yahoo.setdefault(key(r['player']), {})[lg] = float(r['pts'])
                except (TypeError, ValueError): pass
        # ---- kickoffs and market readiness per team
        self.kick = {}
        for (a, h), g in self.games.items():
            k = C.parse_kick(g.get('kickoff'))
            self.kick[a] = k; self.kick[h] = k
        # Kalshi event tickers look like KXNFLREC-26SEP17DETBUF: series, then a
        # date, then the two team codes run together. A game is market-READY when
        # it carries the full prop suite (>=4 series), not just anytime-TD.
        game_series = defaultdict(set)
        if os.path.exists(D + 'kalshi.csv'):
            for r in csv.DictReader(open(D + 'kalshi.csv')):
                if r['event'] not in self.in_week_events: continue   # week guard
                if r['series'] in ('KXNFLSPREAD', 'KXNFLTOTAL', 'KXNFLGAME', 'KXNFLTEAMPTS'): continue   # readiness = PLAYER props
                tail = r['event'].split('-', 1)[1]          # 26SEP17DETBUF
                game_series[tail[7:]].add(r['series'])      # DETBUF
        from .names import DST_FULL
        ABBR = set(DST_FULL)
        self.ready = set()
        for code, ss in game_series.items():
            if len(ss) < 4: continue
            for i in (2, 3):
                a, b = team(code[:i]), team(code[i:])
                if a in ABBR and b in ABBR: self.ready |= {a, b}; break
        # ---- LIVE GUARD (09-27): once a game kicks off, Kalshi's ladders are in-game
        # markets — they track what has already happened (Treadwell 135 rec yds at
        # 2:20 pm, LaPorta 'cut 20%'). They are not projections and never feed a
        # line, a tier or a line-movement flag. The pregame Sleeper number stands
        # for the unplayed share until Yahoo's final replaces it.
        now = C.now()
        kicked_codes = set()
        for code in game_series:
            for i in (2, 3):
                a, b = team(code[:i]), team(code[i:])
                if a in ABBR and b in ABBR:
                    k = self.kick.get(a) or self.kick.get(b)
                    if k and k <= now: kicked_codes.add(code)
                    break
        self.live_events = set()
        if kicked_codes and os.path.exists(D + 'kalshi.csv'):
            live_keys = set()
            for r in csv.DictReader(open(D + 'kalshi.csv')):
                if r['event'] not in self.in_week_events: continue
                if r['event'].split('-', 1)[1][7:] in kicked_codes:
                    self.live_events.add(r['event'])
                    t = r['title']
                    if ':' in t: live_keys.add((key(t.split(':', 1)[0].strip()), r['series']))
            self.kal_live_dropped = len([1 for kk in self.kal if kk in live_keys])
            self.kal = {kk: v for kk, v in self.kal.items() if kk not in live_keys}
            self.in_week_events = self.in_week_events - self.live_events
            # a game in progress is neither ready nor unready: its players are locked
            for code in kicked_codes:
                for i in (2, 3):
                    a, b = team(code[:i]), team(code[i:])
                    if a in ABBR and b in ABBR: self.ready -= {a, b}; break
        else:
            self.kal_live_dropped = 0

    # ------------------------------------------------------------ per player
    def market_ready(self, tm):
        return team(tm) in self.ready

    def kickoff(self, tm):
        return self.kick.get(team(tm))

    def line(self, k, pos, tm, market=True):
        """Best stat line for player key `k`. -> dict(stat, sources, prov, unknown, fam)
        market=False: the Sleeper-only line (no Kalshi/props overrides) — used by the
        calibration log to score each source against the actual (09-26)."""
        k = key(k); pos = (pos or '').upper(); tm = team(tm)
        src, prov, stat = [], {}, {}

        if pos == 'DEF':
            s = self.off.get(k, {})
            c = self.ctx.get(tm)
            av, asl = (c['allows'] if c else None), (_f(s.get('pts_allow')) or None)
            if av and asl:
                allows = (av + asl) / 2; src += ['vegas', 'sleeper']
                lab = 'kalshi lines' if (c or {}).get('src') == 'kalshi' else 'vegas'
                prov['pts_allow'] = f'{lab} {av:.2f} / sleeper {asl:.2f} -> {allows:.2f}'
            elif av or asl:
                allows = av or asl; src.append('vegas' if av else 'sleeper')
                prov['pts_allow'] = f'{allows:.2f} (single source)'
            else:
                return self._yahoo_line(k, 'DEF') or self._unknown('DEF')
            stat = dict(pts_allow=allows, sack=_f(s.get('sack')), int=_f(s.get('int')),
                        fum_rec=_f(s.get('fum_rec')), def_td=_f(s.get('def_td')))
            if s: src.append('sleeper')
            return dict(stat=stat, sources=sorted(set(src)), prov=prov, unknown=False, fam='DEF')

        if pos == 'K':
            s = self.off.get(k)
            if not s: return self._yahoo_line(k, 'K') or self._unknown('K')
            stat = dict(fgm=_f(s.get('fgm')), xpm=_f(s.get('xpm')))
            prov['fg'] = f'{stat["fgm"]:.2f} made (sleeper volume; fgm_yds field is broken, not used)'
            return dict(stat=stat, sources=['sleeper'], prov=prov, unknown=False, fam='K')

        fam = {'DE':'DL','DT':'DL','NT':'DL','DL':'DL','LB':'LB','OLB':'LB','ILB':'LB','MLB':'LB',
               'CB':'DB','S':'DB','FS':'DB','SS':'DB','DB':'DB'}.get(pos.split(',')[0].strip())
        if fam:
            s = self.idp.get(k)
            if not s: return self._yahoo_line(k, fam) or self._unknown(fam)
            stat = {f: _f(s.get(f)) for f in ('solo','ast','sack','int','pd','tfl','ff','fr','def_td')}
            prov['idp'] = f'sleeper: {stat["solo"]:.2f} solo / {stat["ast"]:.2f} ast / {stat["sack"]:.2f} sk / {stat["pd"]:.2f} pd'
            return dict(stat=stat, sources=['sleeper'], prov=prov, unknown=False, fam=fam)

        # ---- skill positions: Sleeper base, Kalshi/props override field by field
        s = self.off.get(k, {})
        g = lambda f: _f(s.get(f))
        stat = dict(pass_att=g('pass_att'), pass_cmp=g('pass_cmp'), pass_inc=g('pass_inc'),
                    pass_yd=g('pass_yd'), pass_td=g('pass_td'), pass_int=g('pass_int'),
                    pass_sack=g('pass_sack'),
                    rush_att=g('rush_att'), rush_yd=g('rush_yd'), rush_td=g('rush_td'),
                    rec=g('rec'), rec_tgt=g('rec_tgt'), rec_yd=g('rec_yd'), rec_td=g('rec_td'),
                    fum_lost=g('fum_lost'))
        if s: src.append('sleeper')
        if not market:
            if not src: return self._yahoo_line(k, pos) or self._unknown(pos)
            return dict(stat=stat, sources=['sleeper'], prov={}, unknown=False, fam=pos, partial=False, understated=False)
        for field, series in (('rec','KXNFLREC'), ('rec_yd','KXNFLRECYDS'), ('rush_yd','KXNFLRSHYDS'),
                              ('pass_yd','KXNFLPASSYDS'), ('pass_td','KXNFLPASSTDS')):
            f = self.kal.get((k, series))
            if f and f['sse'] < 0.05:
                prov[field] = f"KALSHI {f['mean']:.2f} (n={f['n']}, sse {f['sse']:.4f}) vs sleeper {stat[field]:.2f}"
                stat[field] = f['mean']; src.append('kalshi')
        td = self.kal.get((k, 'KXNFLTD'))
        partial = False
        if td:
            tot = stat['rush_td'] + stat['rec_td']
            prov['td'] = f"KALSHI P(anytime TD)={td['mean']:.2f} vs sleeper E[TD]={tot:.2f}"
            if tot > 0:
                sc = td['mean'] / tot; stat['rush_td'] *= sc; stat['rec_td'] *= sc
            else:
                # No base line to scale. A TD price with nothing else is a THIN
                # signal, not a projection: score the touchdown, flag the line,
                # and let the lineup treat it as provisional. (Ridley, 09-16:
                # 8% anytime TD, no yardage ladder while teammates had one --
                # the absence is itself the read.)
                stat['rec_td' if pos in ('WR', 'TE') else 'rush_td'] = td['mean']
                partial = True
            src.append('kalshi')
        pr = self.props.get(k)
        if pr and not any(x in prov for x in ('rec','rec_yd','rush_yd','pass_yd')):
            for f, v in pr.items():
                if f in stat: prov[f] = f'DK line {v} (line-only, med->mean corrected)'; stat[f] = v
            src.append('props')
        if not src: return self._yahoo_line(k, pos) or self._unknown(pos)
        # partial = no base line AND the only market field is the TD price.
        # A yardage or reception ladder makes it a real (if incomplete) line.
        has_ladder = any(f in prov for f in ('rec', 'rec_yd', 'rush_yd', 'pass_yd'))
        partial = partial and 'sleeper' not in src and not has_ladder
        if partial:
            prov['!'] = 'THIN MARKET — anytime-TD price only, no yardage ladder while teammates have one. Not a full projection.'
        elif 'sleeper' not in src and 'rec' not in prov and pos in ('WR', 'TE', 'RB'):
            prov['~'] = 'no reception ladder or base line — PPR reception points not counted; understated'
        return dict(stat=stat, sources=sorted(set(src)), prov=prov, unknown=False, fam=pos,
                    partial=partial, understated=('~' in prov))

    @staticmethod
    def _unknown(fam):
        return dict(stat={}, sources=[], prov={'!': 'NO SOURCE COVERS THIS PLAYER — unknown, not zero'},
                    unknown=True, fam=fam)

    def _yahoo_line(self, k, fam):
        y = self.yahoo.get(key(k))
        if not y: return None
        return dict(stat={}, sources=['yahoo'], prov={'pts': 'Yahoo projection off the matchup page — single source, no market posted'},
                    unknown=False, fam=fam, pts_override=y)
