"""BREAKOUT SCANNER — find the 3-4 undrafted players who change a season.

Caleb (09-16): "Typically there are 3-4 undrafted players who get added this
first 1-3 weeks that change seasons or even win the league. How can we
identify them and find them?"

What those players have in common, every year, is a ROLE that arrived before
the PRICE did. Nacua (Kupp out), Kyren Williams (Akers benched), Achane, Bucky
Irving, Chase Brown, Jauan Jennings: in each case the snap and route share
said 'starter' one to two weeks before the projections and the room agreed.
Box-score points are the LAGGING signal; by the time they show up the crowd is
bidding too. So the scanner ranks the available pool on four observations,
none of which is a projection:

  USAGE     snap share, target/air-yard share (WR/TE), touch share (RB), from
            the verified weekly pull. A role is a fact.
  MARKET    the Kalshi ladder / DK line for NEXT week vs the Sleeper
            projection. Kalshi pricing a yardage ladder where Sleeper has
            little or nothing is the earliest public confirmation that money
            sees a starter ('absence of a market is a signal' cuts both ways).
  EXPECTED  where the preseason season-blend ranked him. Undrafted means
            outside the drafted range at his position; a starter's usage on an
            undrafted expectation is the whole thesis.
  CROWD     Sleeper's 48-hour trending adds. High = the box score already told
            everyone; in BSB (Wednesday waivers) that is a FAB fight, in HH
            (free agents now) it is a race that is already being run.

Tiers, in order of what to do:
  A  usage says starter AND the market already agrees   -> claim; this is the one
  B  usage says starter, market has not caught up yet   -> claim BEFORE the market
                                                            does; cheapest window
  C  crowd is chasing a box score the usage does not back -> let them
  W  usage rising but below starter thresholds, OR usage says starter but the
     posted market prices him well under the projection -> watch list, next pull

Not a projection, not a composite score. Every number printed is an observed
share, a market price, a preseason rank or a trending count, and each tier
names the rule that placed the player in it.

GAP, stated: 'the starter ahead of him is out' (the Higgins -> Hutchinson
pattern) is the strongest single signal and is NOT yet a feed. It lives in the
role registry (data/roles.json) as verified beat reporting. Pull the injury
report on request and write it there.
"""
import csv, os
from collections import defaultdict
from . import score as SC, usage as U, state as ST, clock as C
from .names import key, team
from .wire import Wire, _fam, TAGGED as WR_TAGGED

D = '/home/claude/bsb2/data/'

# one-game starter thresholds (share of team). Deliberately demanding: a
# season-changer is on the field for most of the game, not a red-zone cameo.
TH = {
    'WR': dict(start=dict(snap=0.70, tgt=0.18, air=0.25), watch=dict(snap=0.55, tgt=0.12, air=0.18)),
    'TE': dict(start=dict(snap=0.70, tgt=0.14, air=0.15), watch=dict(snap=0.60, tgt=0.10, air=0.10)),
    'RB': dict(start=dict(snap=0.50, touch=0.45, min_touch=0.20), watch=dict(snap=0.35, touch=0.30, min_touch=0.12)),
    'QB': dict(start=dict(gs=1),                            watch=dict(snap=0.30)),
}
# 'drafted range' per position for a 12-team, 18-spot league (BSB) and a
# 10-team superflex, 23-spot league (HH). Outside this = undrafted expectation.
DRAFTED = {'BSB': dict(QB=18, RB=40, WR=50, TE=16), 'HH': dict(QB=26, RB=36, WR=44, TE=14)}

def _usage_tier(r):
    """-> 'start' | 'watch' | None, and the rule text that fired."""
    p = r['pos']; t = TH.get(p)
    if not t: return None, ''
    if p == 'QB':
        # every NFL starter starts: gs=1 says nothing about a QB's fantasy role
        # (Maye 09-26). A QB on the wire is WATCH at most from usage alone; only
        # the market re-rating him (ratio ahead of the projection) lifts him.
        if r['gs'] >= 1: return 'watch', f"started (gs=1), {r['snap_share']:.0%} snaps — a QB starting is not a role change"
        return None, ''
    if p == 'RB':
        for lvl in ('start', 'watch'):
            th = t[lvl]
            # a fullback plays half the snaps and touches nothing (Juszczyk,
            # Ricard 09-17): snaps alone never make an RB a starter here
            if (r['snap_share'] >= th['snap'] and r['touch_share'] >= th['min_touch']) or r['touch_share'] >= th['touch']:
                return lvl, f"{r['snap_share']:.0%} snaps, {r['touch_share']:.0%} of RB touches"
        return None, ''
    for lvl in ('start', 'watch'):
        th = t[lvl]
        if r['snap_share'] >= th['snap'] and (r['tgt_share'] >= th['tgt'] or r['air_share'] >= th['air']):
            return lvl, f"{r['snap_share']:.0%} snaps, {r['tgt_share']:.0%} targets, {r['air_share']:.0%} air yds"
    return None, ''

def _market(proj, k, pos):
    """Market vs projection for next week. -> dict(ladder, ratio, text, ahead)"""
    field, series = {'WR': ('rec_yd', 'KXNFLRECYDS'), 'TE': ('rec_yd', 'KXNFLRECYDS'),
                     'RB': ('rush_yd', 'KXNFLRSHYDS'), 'QB': ('pass_yd', 'KXNFLPASSYDS')}[pos]
    f = proj.kal.get((k, series))
    s = proj.off.get(k, {})
    label = {'rec_yd': 'receiving yds', 'rush_yd': 'rushing yds', 'pass_yd': 'passing yds'}[field]
    try: sv = float(s.get(field) or 0)
    except ValueError: sv = 0.0
    dk = (proj.props.get(k) or {}).get(field)
    if f and f['sse'] < 0.05:
        if sv <= 0:
            return dict(ladder=True, ratio=None, ahead=True,
                        text=f"Kalshi {label} {f['mean']:.0f} — no Sleeper line at all (the market sees a starter the projections do not)")
        ratio = f['mean'] / sv
        return dict(ladder=True, ratio=ratio, ahead=ratio >= 1.15,
                    text=f"Kalshi {label} {f['mean']:.0f} vs Sleeper {sv:.0f} ({(ratio-1):+.0%})")
    if dk:
        ratio = (dk / sv) if sv > 0 else None
        return dict(ladder=True, ratio=ratio, ahead=(ratio or 9) >= 1.15,
                    text=f"DK {label} line {dk:.1f} vs Sleeper {sv:.0f}" + ('' if sv > 0 else ' (no Sleeper line)'))
    return dict(ladder=False, ratio=None, ahead=False,
                text='no market line yet' + (f' (Sleeper {label} {sv:.0f})' if sv > 0 else ', and no Sleeper line either'))

def _trending():
    p = D + 'trending_adds.csv'
    if not os.path.exists(p): return {}, {}
    add, drop = {}, {}
    for r in csv.DictReader(open(p)):
        nm = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
        k = key(nm) if r.get('pos') != 'DEF' else 'DST:' + team(r['team'])
        (add if r['kind'] == 'add' else drop)[k] = int(float(r['count']))
    return add, drop

def _usage_role(r, use):
    """One-line depth-chart observation for a rostered player from the pull, or None."""
    u = use.get(r['key'])
    if not u: return None
    lvl, rule = _usage_tier(u)
    tag = {'start': 'STARTER-level', 'watch': 'part-time'}.get(lvl, 'bench-level')
    detail = rule or f"{u['snap_share']:.0%} of snaps"
    return f"{tag} — {detail}", lvl

def _drop_candidates(state, lineup, w, use):
    """Bench players a breakout could take the spot of, cheapest first: dead spots
    (IR/exempt with no IR slot), then registry drop_ok, then a spare DEF/K, then
    the lowest-valued bench player. Anything the drop gate BLOCKs (holds,
    handcuffs) is left out, so a move is never proposed over Jacobs or Davis."""
    rows = lineup['rows'] if lineup else state.mine
    fams = defaultdict(int)
    for r in rows:
        if r['slot'] != 'IR': fams[_fam(r['pos'])] += 1
    # two DEFs (or Ks): the spare is the one worth less on the SEASON, whether he is
    # starting or benched (Vikings 09-24: #5 season DEF on the bench behind the #21
    # 49ers in the slot — the 49ers are the spare, and the Vikings start)
    spare = {}
    for fam in ('DEF', 'K'):
        pair = [r for r in rows if _fam(r['pos']) == fam and r['slot'] != 'IR' and r['key'] not in w.hold]
        if len(pair) >= 2:
            pair.sort(key=lambda r: (w.season.get(r['key'], {}).get('pts') or 0, r.get('pts') or 0))
            spare[fam] = pair[0]['key']
    out = []
    for r in rows:
        fam = _fam(r['pos'])
        if r['key'] in w.hold: continue
        if fam in ('DEF', 'K'):
            if spare.get(fam) != r['key']: continue
        elif r['slot'] != 'BN': continue
        ur = _usage_role(r, use)
        usage_txt, ulvl = (ur if ur else (None, None))
        dead = w.dead_spot(r)
        tagged = r['designation'] in WR_TAGGED and not dead      # a tag with no verified reason counts for nothing (Jennings 09-21):
                                                                 # he is ranked on season value exactly as if healthy
        # a bench player who himself showed starter-level usage is not the spot
        if ulvl == 'start' and not dead and r['key'] not in w.drop_ok: continue
        g = w.gate_drop(r, usage=usage_txt, horizon='weekly' if fam in ('DEF', 'K') else 'season')
        if g.verdict == 'BLOCK': continue
        tier = 0 if dead else 1 if r['key'] in w.drop_ok else 2 if fam in ('DEF', 'K') else 3
        # rank on SEASON value in both leagues (the blend is PPR-scored; the ordering
        # within a position holds in HH). Week points would let an injury tag pick
        # the drop through a zeroed projection (Pierce 09-23).
        val = w.season.get(r['key'], {}).get('pts') or r.get('pts') or 0.0
        why = ('dead spot — verified in the registry' if dead else
               (f'cheapest clean drop on season value; {r["designation"]} tag not counted' + (f' ({usage_txt.split(" — ")[0].lower()} usage last week)' if usage_txt else '')) if tagged and r['key'] not in w.drop_ok and fam not in ('DEF', 'K') else w.drop_ok[r['key']]['call'][:60] if r['key'] in w.drop_ok
               else (f'spare {fam} — the lower season value of your two ({w.season.get(r["key"], {}).get("pts") or 0:.0f} vs {max((w.season.get(x["key"], {}).get("pts") or 0) for x in rows if _fam(x["pos"]) == fam and x["key"] != r["key"]):.0f})' + (' — he is in the slot now, so the other one starts' if r['slot'] != 'BN' else '')) if fam in ('DEF', 'K')
               else ('lowest-valued bench player' + (f' ({usage_txt.split(" — ")[0].lower()} usage last week)' if usage_txt else ', no usage row')))
        out.append(dict(row=r, tier=tier, val=val, why=why, gate=g))
    out.sort(key=lambda x: (x['tier'], x['val']))
    return out

def _mechanics(league, tier=None):
    if league == 'HH':
        return 'free agent — immediate, counts 1 of 7 weekly acquisitions'
    txt = 'free agent until his game kicks off; after that a waiver claim, in by Tue night (runs Wed ~5am)'
    if tier in ('A', 'B'):
        from . import fab as F
        m = F.model()
        b = (m.get('bands') or {}).get(tier)
        if b: txt += f" — bid ${b['bid']} ({b['why']})"
    return txt

def _bid_txt(league, tier, x, prof):
    """BSB: the bid against the likely field (rivals model), else the flat band."""
    if league != 'BSB': return ''
    if prof is not None:
        try:
            from . import rivals as RV
            b = RV.bid_for(prof, _fam(x['pos']), tier)
            return f" — bid ${b['bid']}: {b['why']}"
        except Exception: pass
    from . import fab as F
    b = (F.model().get('bands') or {}).get(tier)
    return f" — bid ${b['bid']} ({b['why']})" if b else ''

def _mech(league, tier, x, waived, prof=None):
    if waived and x['key'] in waived:
        return f'ON WAIVERS (dropped {waived[x["key"]]}) — a claim, not a free-agent add: in by Tue night, runs Wed ~5am; he cannot play for you this week' + _bid_txt(league, tier, x, prof)
    if league == 'HH': return _mechanics(league, tier)
    return 'free agent until his game kicks off; after that a waiver claim, in by Tue night (runs Wed ~5am)' + _bid_txt(league, tier, x, prof)

def _depth(state, lineup, fam):
    """(rostered count in this family, slots this family can fill, weakest rostered week pts, his name)"""
    rows = [r for r in (lineup['rows'] if lineup else state.mine)
            if r['slot'] != 'IR' and _fam(r['pos']) == fam and r['designation'] not in ('IR','IR-R','O','NA','PUP','PUP-R','SUSP','CEL')]
    # dedicated slots only: a flex is not a reason to carry a third TE (Otton 09-23)
    dedicated = [sl for sl in state.cfg.fam_slots.get(fam, ()) if sl not in ('W/R/T', 'W/R')]
    slots = len(dedicated) or len(state.cfg.fam_slots.get(fam, ()))
    weak = min(rows, key=lambda r: r.get('pts') or 0) if rows else None
    return len(rows), slots, (weak.get('pts') if weak else None), (weak['player'] if weak else None)

def _on_waivers(league, path='/home/claude/bsb2/data/bsb_transactions.csv'):
    """BSB: players dropped 'To Waivers' since the last Wednesday run -> {key: 'Sat 4:05 am'}.
    A dropped player sits on waivers until the Wednesday run (Fields: dropped Fri 09-18,
    claimed Wed 09-23 for $3), so he is a CLAIM this week, never a free-agent add."""
    if league != 'BSB': return {}
    import csv as _csv, os as _os
    p = path
    if not _os.path.exists(p): return {}
    last_run = C.bsb_waiver_deadline()
    if last_run > C.now(): last_run -= C.dt.timedelta(days=7)
    out = {}
    for r in _csv.DictReader(open(p)):
        if r.get('action') != 'Drop' or 'waiver' not in (r.get('note') or '').lower(): continue
        try: t = C.dt.datetime.strptime(r['datetime'], '%Y-%m-%d %H:%M').replace(tzinfo=C.ET)
        except Exception: continue
        if t >= last_run: out[key(r['player'])] = f'{t:%a %-I:%M %p}'
    return out

def _move(x, league, drops, kick, depth, dropped=None, dropped_where=None, waived=None, prof=None):
    """The if-and-when. -> dict(verb, when, drop, why). verb: ADD | ADD-DEAD | WAIT | NONE | BLOCKED"""
    g = x['gate']
    if dropped and x['key'] in dropped:
        where = (dropped_where or {}).get(x['key'], league)
        return dict(verb='NONE', when='no move — you dropped him', drop=None,
                    why=f'you dropped him in {where} on {dropped[x["key"]]}; the usage behind this row predates that and is not re-proposed until a newer usage pull says otherwise')
    lock = f' — locks {kick:%a %-I:%M %p} ET' if kick else ''
    d = drops[0] if drops else None
    dn = d['row']['player'] if d else None
    if g is not None and g.verdict == 'BLOCK':
        return dict(verb='BLOCKED', when='no move', drop=None,
                    why='gate: ' + '; '.join(m for _, s_, m in g.checks if s_ == 'BLOCK')[:120])
    n, slots, wpts, wname = depth
    # a real role on the wire is still not a move if he would sit behind
    # everyone you already have at the position (Wentz 09-17: HH already
    # carries Dak, Goff and Stafford for two QB-eligible slots; a fourth QB
    # projected at 13 is a trade chip, not a season-changer for this roster)
    if x['tier'] in ('A', 'B') and n >= slots + 1 and x['week_pts'] is not None and wpts is not None and x['week_pts'] < wpts:
        return dict(verb='NONE', when='no move for this roster', drop=None,
                    why=f'you already carry {n} {x["pos"]}s for {slots} slot(s) and he projects below your weakest ({wname} {wpts:.1f} vs {x["week_pts"]:.1f}). Only a trade chip.')
    if x['tier'] == 'A':
        if not x['in_pool']:
            return dict(verb='WAIT', when='until a projection or market prices him', drop=None,
                        why='usage and crowd only — no source gives him a number yet, so the gate cannot judge the add')
        if d is None:
            return dict(verb='WAIT', when='no clean drop left', drop=None,
                        why='the rest of the bench is a hold, a handcuff, starter-level usage in its own right, or has no depth-chart check on record — adding him means cutting one of those')
        dwk = d['row'].get('pts')
        cmp = (f' He projects {x["week_pts"]:.1f} this week vs {dn} {dwk:.1f} — the add is for the role, not this week.'
               if x['week_pts'] is not None and dwk and x['week_pts'] < dwk else '')
        agree = 'the market agrees' if x.get('ahead') else 'the role is verified in the registry (beat reporting), the market has not priced him yet'
        return dict(verb='ADD', when=_mech(league, 'A', x, waived, prof) + lock, drop=dn,
                    why=f'usage says starter and {agree}. {dn} is the spot: {d["why"]}.{cmp}')
    if x['tier'] == 'B':
        if d is not None and d['tier'] == 0:
            return dict(verb='ADD-DEAD', when=_mech(league, 'B', x, waived, prof) + lock, drop=dn,
                        why=f'costs nothing: {dn} is a dead spot. Usage says starter; the market has not priced him yet, which is the cheap window')
        # the WAIT was 'add then if the snaps hold'. With two pulls on disk the
        # snaps either held or they did not (09-23): two straight weeks of
        # starter usage is the confirmation the market has not priced yet.
        if x.get('held'):
            # a second DEF in BSB is worth ~1.2 pts/week over the single best DEF and
            # ~0.5 over streaming (09-24, weeks 3-9 on posted lines), so it is not a
            # free spot: only a Tier-A add (market-confirmed) may take it
            if d is not None and d['tier'] == 2:
                return dict(verb='WAIT', when='no drop worth less than him', drop=None,
                            why=f'two straight weeks of starter usage ({x["held"]}), but the only clean spot is the second {_fam(d["row"]["pos"])} ({dn}), which is worth about a point a week on its own — a market-confirmed (Tier A) add can take it, an unpriced one cannot')
            # a B add is for a role the market has not priced; it still must beat the
            # man it cuts on THIS week's number (Hurst 5.8 over Lemon 6.3 was not a move)
            if d is not None and d['tier'] == 3 and x['week_pts'] is not None and (d['row'].get('pts') or 0) >= x['week_pts']:
                return dict(verb='WAIT', when='no drop worth less than him', drop=None,
                            why=f'two straight weeks of starter usage ({x["held"]}), but the cheapest clean drop ({dn}, {d["row"].get("pts") or 0:.1f} this week) projects at or above him ({x["week_pts"]:.1f})')
            if d is None:
                return dict(verb='WAIT', when='no clean drop left', drop=None,
                            why=f'two straight weeks of starter usage ({x["held"]}), but the rest of the bench is a hold, a handcuff, starter-level usage in its own right, or has no depth-chart check on record')
            return dict(verb='ADD', when=_mech(league, 'B', x, waived, prof) + lock, drop=dn,
                        why=f'starter usage two weeks running ({x["held"]}) and the market has not priced him yet — the cheap window. {dn} is the spot: {d["why"]}')
        return dict(verb='WAIT', when='next usage pull (Tuesday) — add then if the snaps hold or the market moves toward him', drop=None,
                    why='one game of starter usage; no market confirmation yet and the spot would cost a real player')
    if x['tier'] == 'C':
        return dict(verb='NONE', when='no move', drop=None,
                    why='the crowd is chasing a box score the snap count does not back')
    return dict(verb='NONE', when='watch next pull', drop=None, why=x['usage'])

def scan(state, proj, season=None, week_usage=None, lineup=None):
    """-> dict(rows=[...ranked...], pulled=usage pull time, week=usage week, notes=[...],
               summary=str, drops=[...])"""
    league = state.league
    wk = week_usage or (proj.week - 1)
    use = U.load(wk); notes = []
    if not use:
        # fall back to the newest usage on disk, and SAY how stale it is; a scan on
        # two-week-old snaps is still a scan, a blank panel is not (09-23)
        for w_ in range(wk - 1, 0, -1):
            use = U.load(w_)
            if use:
                notes.append(f'no usage pull for week {wk} yet — this scan runs on the WEEK {w_} pull ({wk - w_} week(s) older than it should be)')
                wk = w_; break
    if not use: return dict(rows=[], pulled=None, week=wk, notes=[f'no usage pull on disk for week {wk}'])
    prev = U.load(wk - 1) if wk > 1 else {}
    if wk > 1 and not prev: notes.append(f'no week-{wk - 1} usage on disk — two-week confirmation unavailable')
    w = Wire(state, proj, season=season)
    season = season or {}
    add_tr, drop_tr = _trending()
    # preseason rank by position from the season blend
    rank = {}
    byp = defaultdict(list)
    for k, v in season.items(): byp[(v.get('pos') or '').upper()].append((v.get('pts') or 0, k))
    for p, L in byp.items():
        for i, (_, k) in enumerate(sorted(L, reverse=True), 1): rank[k] = i
    drafted = DRAFTED[league]

    out = []
    for k, r in use.items():
        if k in state.roster_keys: continue                  # someone in this league has him
        if k in w.blocked: continue                          # registry add_no / unavailable
        if any(k == a for a, *_ in w.phantoms): continue     # name audit says he IS rostered
        lvl, rule = _usage_tier(r)
        if not lvl: continue
        # one-QB league: a starting QB on the wire is a streamer, not a season-
        # changer, unless the market prices him like a QB1 (>=240 pass yds).
        if league == 'BSB' and r['pos'] == 'QB':
            f = proj.kal.get((k, 'KXNFLPASSYDS'))
            if not (f and f['mean'] >= 240): continue
        mk = _market(proj, k, r['pos'])
        L = proj.line(k, r['pos'], r['tm'])
        pts = SC.points(L, league) if not L.get('unknown') else None
        boom = SC.boom(L, league) if not L.get('unknown') else None
        prank = rank.get(k)
        undrafted = (prank is None) or (prank > drafted.get(r['pos'], 999))
        crowd = add_tr.get(k, 0)
        # market first: a posted ladder well UNDER the projection is the market
        # disagreeing, not lagging (Boston 09-17: 92% snaps, Kalshi 24 rec yds vs
        # Sleeper 38). That is a watch, whatever the snap count says.
        market_no = mk['ladder'] and mk['ratio'] is not None and mk['ratio'] < 0.85
        verified = k in w.verified
        # the registry's add_yes is verified beat reporting (a route share, an
        # injury to the man ahead) -- as good as a market confirmation
        if lvl == 'start' and (mk['ahead'] or verified): tier = 'A'
        elif lvl == 'start' and not market_no:  tier = 'B'
        elif lvl == 'start':                    tier = 'W'; rule += ' — but the market prices him BELOW the projection'
        elif crowd:                             tier = 'C'
        else:                                   tier = 'W'
        cand = w.pool.get(k)
        gate = w.gate_add(cand, usage=f"wk{wk} {rule}") if cand else None
        pr = prev.get(k)
        held = ''
        if pr and lvl == 'start':
            ptier, prule = _usage_tier(pr)
            if ptier == 'start': held = f'wk{wk - 1}: {prule}'
        out.append(dict(key=k, name=r['name'], tm=r['tm'], pos=r['pos'], tier=tier, usage=rule, held=held,
                        snap=r['snap_share'], tgt=r['tgt_share'], air=r['air_share'], touch=r['touch_share'],
                        rz=r['rec_rz_tgt'], pts_wk1=r['pts_ppr'], market=mk['text'], ladder=mk['ladder'], ratio=mk['ratio'],
                        ahead=mk['ahead'], prank=prank, undrafted=undrafted, crowd=crowd,
                        week_pts=pts, boom=boom, season=(season.get(k) or {}).get('pts'),
                        gate=gate, in_pool=bool(cand), ready=proj.market_ready(r['tm']),
                        verified=verified, registry=w.verified.get(k, {}).get('why', '')))
    order = {'A': 0, 'B': 1, 'C': 2, 'W': 3}
    out.sort(key=lambda x: (order[x['tier']], not x['undrafted'], -(x['snap'] + x['tgt'] + x['air'] + x['touch'])))
    drops = _drop_candidates(state, lineup, w, use)
    # a claim plan, not a cross product: each ADD consumes its drop, so two
    # Tier-A rows never point at the same bench player (Black/Wentz 09-17)
    added = ST.recently_added(league)
    drops = [d for d in drops if d['row']['key'] not in added]   # a player he added this week is his decision, not the spot
    remaining = list(drops)
    dropped = {k: d for k, (lg_, d) in ST.recently_dropped_anywhere().items()}
    dropped_where = {k: lg_ for k, (lg_, d) in ST.recently_dropped_anywhere().items()}
    waived = _on_waivers(league)
    prof = None
    if league == 'BSB':
        try:
            from . import rivals as RV
            prof = RV.profiles(state, proj)
        except Exception: prof = None
    for x in out:
        x['move'] = _move(x, league, remaining, proj.kickoff(x['tm']), _depth(state, lineup, x['pos']), dropped, dropped_where, waived, prof)
        if x['move']['verb'] in ('ADD', 'ADD-DEAD') and remaining: remaining.pop(0)
    acts = [x for x in out if x['move']['verb'] in ('ADD', 'ADD-DEAD')]
    if acts:
        summary = (f"{len(acts)} to act on: " + '; '.join(f"{x['name']} over {x['move']['drop']}" for x in acts)
                   + f". {_mechanics(league)}.")
    elif any(x['tier'] in ('A', 'B') for x in out):
        summary = ("No move this week. Starter-level usage exists on the wire but nothing clears both the add gate "
                   "and a clean drop; re-check after the next usage pull.")
    else:
        summary = "No move. Nothing on the wire shows starter-level usage."
    notes = list(notes)
    if not add_tr: notes.append('no trending pull on disk — CROWD column empty')
    notes.append("'starter ahead is out' is not a feed yet: verified injuries live in roles.json add_yes/why")
    return dict(rows=out, pulled=U.pulled_at(wk), week=wk, notes=notes, summary=summary, drops=drops)

def fmt(res, league, top=14):
    rows = res['rows']
    L = [f"BREAKOUT SCAN — {league} — week {res['week']} usage" +
         (f" pulled {res['pulled']:%a %m-%d %H:%M} ET" if res['pulled'] else '')]
    if not rows:
        L.append('  ' + '; '.join(res['notes'])); return '\n'.join(L)
    L.append(f"  {'T':1} {'player':22}{'pos':4}{'tm':4} {'snap':>5} {'tgt':>5} {'air':>5} {'tch':>5} {'wk1':>5}  {'pre':>4} {'crowd':>6}  {'nxt':>5} {'boom':>4}  market")
    for x in rows[:top]:
        nxt = f"{x['week_pts']:5.1f}" if x['week_pts'] is not None else '  n/a'
        bm = f"{x['boom']:4.0%}" if x['boom'] is not None else ' n/a'
        pre = str(x['prank']) if x['prank'] else 'und'
        tch = x['touch'] if x['pos'] == 'RB' else 0.0
        L.append(f"  {x['tier']} {x['name'][:22]:22}{x['pos']:4}{x['tm']:4} {x['snap']:5.0%} {x['tgt']:5.0%} {x['air']:5.0%} "
                 f"{tch:5.0%} {x['pts_wk1']:5.1f}  {pre:>4} {(x['crowd'] or 0):6d}  {nxt} {bm}  {x['market']}")
        m = x['move']
        L.append(f"      -> {m['verb']}: {m['when']}" + (f"; drop {m['drop']}" if m['drop'] else '') + f"  [{m['why'][:110]}]")
        g = x['gate']
        if g is not None and g.verdict != 'PASS':
            L.append(f"      gate {g.verdict}: " + '; '.join(f'{gg} {m}' for gg, s_, m in g.checks if s_ != 'PASS')[:160])
        elif g is None:
            L.append('      gate: not in the projection pool (usage only — no source prices him next week)')
        if x['registry']: L.append(f"      registry: {x['registry'][:110]}")
    tiers = defaultdict(int)
    for x in rows: tiers[x['tier']] += 1
    L.append(f"  SUMMARY: {res['summary']}")
    L.append(f"  tiers: A={tiers['A']} B={tiers['B']} C={tiers['C']} W={tiers['W']}   pre=preseason rank at position ('und' = not in the season blend)")
    for n in res['notes']: L.append('  note: ' + n)
    return '\n'.join(L)
