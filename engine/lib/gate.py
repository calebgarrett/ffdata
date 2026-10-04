"""The gate. Nothing reaches Caleb without passing this, and its output is
printed verbatim rather than summarised.

Each gate encodes a REAL failure that already cost something:

 G1 OWNERSHIP   "Kenneth Gainwell" recommended as the best FA running back in the
                league. He is Kenny Gainwell, on Rick's bench. (2026-09-15)
 G2 DESIGNATION Jordyn Tyson recommended as the top WR add. He is on IR,
                designated to return, ~2 months. The derived FA pool carries no
                injury field, so an IR player looks like a free agent. Twice now.
 G3 ROLE        "Drop Ray Davis for Ty Johnson." Ray Davis is the Bills RB2
                directly behind James Cook -- the Cook handcuff. Ty Johnson is
                RB3. A low projection on a handcuff is the DEFINITION of a
                handcuff, not a reason to drop him.
 G4 HORIZON     "Drop the 49ers" off a SEASON projection, in a week where the
                market had them 3rd of 32 and the Lions -- his actual starter --
                31st of 32. DEF and K in an uncapped league are matchup slots.
 G5 SOURCES     Yahoo and Sleeper called "two sources". They are both Rotowire.
 G6 MAGNITUDE   DeJean returned as "2,058". Yahoo's roster points column with
                stat1=S_PS_2026 is a RANKING, not points (Jacobs 739).
 G7 READINESS   Answering a Sunday start/sit question on Tuesday, when no player
                market exists for the Sunday slate yet. This is the gate that
                stops an answer from changing later for no reason other than
                that the data finally arrived.
 G8 FRESHNESS   Replacement level is only valid the day it was pulled.
 G9 REVERSAL    Six reversals inside one session, each discovered by Caleb.
 G10 MECHANICS  Planned a start-then-drop inside one scoring week.
"""
from . import paths as _paths
import json, os, datetime as dt
from .names import key, audit_phantoms
from . import scoring as S

BLOCK, WARN, OK = 'BLOCK', 'WARN', 'PASS'
FAMILIES = {'kalshi':'market','vegas':'market','props':'market',
            'sleeper':'rotowire','yahoo':'rotowire','rotowire':'rotowire',
            'fftoday':'fftoday','espn_model':'espn','espn_injury':'espn',
            'depth_chart':'depthchart','pct_rostered':'crowd',
            # REALIZED usage -- snap counts, route counts, target share from a
            # box score or a team snap-count report. This is its own family and
            # not 'rotowire' even when Rotowire published it, because it is an
            # OBSERVATION of what happened, not a projection of what might. It
            # is the class of evidence that would have stopped the Germie
            # Bernard add (115 projected points, 3 offensive snaps).
            'usage':'usage','snapcount':'usage','beat':'usage'}

# Verified role registry, loaded once. See data/roles.json.
# One loader (lib/rules.py): add_yes entries older than 14 days are demoted to
# _demoted_add_yes. A parse error returns {} here so the import never crashes; the
# input contract (C16) has already refused the run before any decision reads it.
ROLES_PATH = _paths.data('roles.json')
def _roles():
    from . import rules as _RU
    return _RU.load_roles(ROLES_PATH)
ROLES = _roles()

LOG = _paths.data('decisions.json')

class Result:
    def __init__(self, kind, subject):
        self.kind, self.subject, self.checks = kind, subject, []
    def add(self, gate, status, msg):
        self.checks.append((gate, status, msg))
    @property
    def verdict(self):
        if any(s == BLOCK for _, s, _ in self.checks): return BLOCK
        if any(s == WARN for _, s, _ in self.checks): return WARN
        return OK
    def render(self, indent='   '):
        out = [f'{indent}{self.verdict}  {self.kind.upper()}: {self.subject}']
        for g, s, m in self.checks:
            mark = {'PASS':'ok ', 'WARN':'!! ', 'BLOCK':'XX '}[s]
            out.append(f'{indent}  {mark}{g:<12} {m}')
        return '\n'.join(out)



def check(kind, subject, *, player=None, designation='__UNREAD__', sources=(),
          pos=None, value=None, horizon=None, market_ready=None,
          role=None, handcuff_for=None, pool_keys=None, roster_keys=None, pool_meta=None,
          pulled=None, mechanics_ok=True, note=None, floor_is_zero=False, league='BSB',
          state=None, usage=None):
    """kind: add | drop | start | sit | trade | hold"""
    r = Result(kind, subject)

    # ---- G1 ownership (adds only)
    if kind == 'add':
        if roster_keys is None or player is None:
            r.add('G1-owner', BLOCK, 'roster set not supplied — cannot verify he is unrostered')
        elif key(player) in roster_keys:
            r.add('G1-owner', BLOCK, f'ALREADY ROSTERED — {player} is on a roster in this league')
        else:
            msg = 'unrostered, checked against every roster in the league'
            if pool_keys is not None:
                ph, _near = audit_phantoms(pool_keys, roster_keys, meta=pool_meta)
                if ph:
                    r.add('G1-owner', BLOCK,
                          f'pool contaminated: {len(ph)} phantom(s), e.g. {ph[0][0]} == rostered {ph[0][1]}')
                    msg = None
            if msg: r.add('G1-owner', OK, msg)
        # the roster set is only as current as the LEAGUE read behind it. In a
        # waiver league, a read older than the last waiver run cannot say who is
        # free (Fields 09-23). In a free-agent league, an old read is a warning.
        if state is not None and getattr(state, 'others_pulled', None):
            from . import clock as _C, ts as _T, rules as _RU
            op = _T.parse_ts(state.others_pulled, 'state')
            age = _C.age_hours(state.others_pulled) or 0
            # the run's ACTUAL time is on the transactions log (09-30: it ran at 4:12
            # am, the 4:57 am pull was after it, and the 6:00 assumption blocked
            # every add all morning); the assumed 6:00 is the fallback — rules.waiver_run_at
            wr = _RU.waiver_run_at()
            if league == 'BSB' and op < wr <= _C.now():
                r.add('G1-owner', BLOCK, f'league rosters last read {op:%a %m-%d %-I:%M %p} ET, BEFORE the waiver run at {wr:%a %-I:%M %p} — who is free is UNVERIFIED; read every roster (or the transactions page) first')
            elif age > 24:
                r.add('G1-owner', WARN, f'league rosters last read {op:%a %m-%d %-I:%M %p} ET ({age:.0f}h ago) — availability is as of then; confirm on Yahoo before adding')

    # ---- G2 designation
    if kind in ('add', 'start', 'trade'):
        if designation == '__UNREAD__':
            r.add('G2-desig', BLOCK, 'designation NOT READ — unread is not the same as clear')
        elif designation in S.UNUSABLE:
            ir = 'and this league has NO IR slot' if league=='BSB' else 'but this league has 3 IR slots — stash, do not drop'
            r.add('G2-desig', BLOCK, f'designation {designation} — cannot be started, {ir}')
        elif designation in S.RISKY:
            r.add('G2-desig', WARN, f'designation {designation} — needs a named contingency')
        else:
            r.add('G2-desig', OK, 'designation read, clear')

    # ---- G3 role / handcuff (drops only)
    if kind == 'drop':
        if pos in ('DEF', 'K'):
            r.add('G3-role', OK, f'{pos} — a depth-chart role does not apply; judged on matchup (G4)')
        elif handcuff_for:
            r.add('G3-role', BLOCK, f'HANDCUFF to {handcuff_for} — a low projection on a handcuff is the point of one')
        elif role is None:
            r.add('G3-role', BLOCK, 'NFL depth-chart role not checked')
        else:
            starter = any(w in role.lower() for w in ('rb1','wr1','wr2','te1','qb1','starter'))
            r.add('G3-role', WARN if starter else OK, f'role: {role}')

    # ---- G4 horizon
    if horizon is None:
        r.add('G4-horizon', BLOCK, 'no horizon declared')
    else:
        want = None
        if kind in ('start', 'sit'):
            want = 'weekly'
        elif kind in ('add', 'drop'):
            want = 'weekly' if pos in ('DEF', 'K') else 'season'
        if want and horizon != want:
            why = ('DEF and K are matchup slots — the season spread is 2-3 pts/wk, '
                   'the weekly spread is far larger'
                   if pos in ('DEF','K') else 'add/drop is a season decision')
            r.add('G4-horizon', BLOCK, f'horizon={horizon} but this needs {want}: {why}')
        else:
            r.add('G4-horizon', OK, f'horizon={horizon}, correct for a {kind} at {pos}')

    # ---- G5 source independence
    fams = sorted({FAMILIES.get(s, s) for s in sources})
    real = [f for f in fams if f != 'crowd']
    if not sources:
        r.add('G5-sources', BLOCK, 'no sources named')
    elif len(real) < 2:
        # EXCEPTION, deliberate and narrow: when the thing being replaced is a
        # VERIFIED zero -- an unusable designation in a league with no IR slot --
        # the downside of a single-source add is bounded at zero. Requiring two
        # sources there would enforce keeping a player worth nothing. The status
        # still has to be said out loud, which is what WARN means here.
        sev = WARN if (kind in ('start','sit') or floor_is_zero) else BLOCK
        extra = ' — allowed only because it replaces a verified dead spot worth 0' if floor_is_zero else ''
        r.add('G5-sources', sev,
              f'SINGLE SOURCE: {real or fams} ({sorted(set(sources))}){extra}')
    else:
        r.add('G5-sources', OK, f'{len(real)} independent families: {real}  ({sorted(set(sources))})')

    # ---- G6 magnitude
    if value is not None and pos:
        lo, hi = (S.WEEK_BOUNDS if horizon == 'weekly' else S.SEASON_BOUNDS).get(pos, (-1e9, 1e9))
        if value > hi:
            r.add('G6-magnitude', BLOCK, f'{value} above {pos} {horizon} bounds [{lo},{hi}] — bad read (a ranking or a total), not a bold number')
        elif value < lo and kind == 'add' and usage:
            # a backup's preseason season number is small because he was a
            # backup when it was written; the usage pull says he is not one now
            # (Wentz 09-17: 15.65 season pts, 83% of the snaps). Not a bad read
            # -- a stale expectation, which is what a breakout looks like.
            r.add('G6-magnitude', WARN, f'{value} below {pos} {horizon} bounds [{lo},{hi}] — preseason number for a backup; usage says otherwise, judge on usage')
        elif value < lo:
            r.add('G6-magnitude', BLOCK, f'{value} below {pos} {horizon} bounds [{lo},{hi}] — bad read, not a bold number')
        else:
            r.add('G6-magnitude', OK, f'{value} within {pos} {horizon} bounds')

    # ---- G7 market readiness
    if horizon == 'weekly':
        if market_ready is None:
            r.add('G7-ready', WARN, 'market coverage for this game not established')
        elif not market_ready:
            r.add('G7-ready', WARN, 'NO player market posted for this game yet — call is PROVISIONAL, re-run when lines post')
        else:
            r.add('G7-ready', OK, 'player market is posted for this game')

    # ---- G8 freshness
    # Inside ff.build() the input contract has run and the manifest carries the real
    # as-of of every input (content stamps, not the caller's date — every caller used
    # to pass today's date, which made this a tautology). Outside a run (the gate
    # regression, ad-hoc calls) the caller's `pulled` date is all there is.
    from . import contract as _CT
    _cr = _CT.RESULT
    if _cr is not None and kind in ('add', 'drop', 'start', 'sit', 'trade', 'hold'):
        if kind in ('add', 'drop'):
            why = _cr.add_drop_reason(league)
            r.add('G8-fresh', BLOCK if why else OK, (f'add/drop inputs DEGRADED — {why}' if why else f'inputs per the manifest: {_cr.ages_txt()}'))
        elif kind in ('start', 'sit'):
            why = _cr.lineup_reason()
            r.add('G8-fresh', WARN if why else OK, (f'lineup inputs DEGRADED — {why}; call is PROVISIONAL' if why else f'inputs per the manifest: {_cr.ages_txt()}'))
        else:
            r.add('G8-fresh', OK, f'inputs per the manifest: {_cr.ages_txt()}')
    elif pulled:
        from . import clock as _C
        # ET, not the container's UTC: at 8 pm ET on the 30th the inputs are not a day old (09-30)
        from . import ts as _T
        age = (_C.today() - _T.parse_ts(pulled[:10], 'date').date()).days
        r.add('G8-fresh', OK if age == 0 else (WARN if age <= 1 else BLOCK),
              f'inputs pulled {pulled[:10]} ({age}d old)')
    else:
        r.add('G8-fresh', WARN, 'pull date not recorded')

    # ---- G9 reversal against the ledger (one log, both leagues)
    from . import ledger as LG
    prior = LG.prior(league, kind, player or subject)
    if prior and prior.get('call') and note and note != prior['call'] \
            and prior['status'] not in ('superseded', 'expired'):
        r.add('G9-reversal', WARN,
              f"REVERSES {prior['ts'][:10]}: \"{prior['call']}\" — must be stated out loud")
    elif prior and prior['status'] == 'declined':
        r.add('G9-reversal', BLOCK,
              f"Caleb DECLINED this on {prior.get('status_ts', prior['ts'])[:10]} — do not re-raise without new evidence")
    else:
        r.add('G9-reversal', OK, 'no conflicting prior call on record')

    # ---- G12 state: is this already true?  (2026-09-16, "swap in the 49ers")
    if state is not None and player:
        already = ((kind == 'start' and state.is_starting(player)) or
                   (kind == 'sit' and state.slot_of(player) in ('BN', 'IR')) or
                   (kind == 'add' and state.owner_of(player) == state.me) or
                   (kind == 'drop' and state.owner_of(player) not in (state.me,)))
        if already:
            r.add('G12-state', WARN, f'ALREADY TRUE in live state ({state.pulled[:16]}) — not an action, a confirmation')
        else:
            st, why = state.stale_for('add_drop' if kind in ('add','drop') else 'lineup')
            r.add('G12-state', BLOCK if (st and kind in ('add','drop')) else (WARN if st else OK),
                  f'checked against live state: {why}')
    elif kind in ('add', 'drop', 'start', 'sit'):
        r.add('G12-state', WARN, 'no live state supplied — cannot confirm this is not already done')

    # ---- G10 league mechanics
    r.add('G10-mech', OK if mechanics_ok else BLOCK,
          f'legal under {league} rules' if mechanics_ok else f'ILLEGAL under {league} rules')

    # ---- G11 verified role registry
    #
    # THE FAILURE THIS PREVENTS (2026-09-15/16): the season model ranked Germie
    # Bernard the best available WR in BSB at 115 projected points and Ty Johnson
    # the best available RB at 81. Bernard played THREE offensive snaps in week 1
    # to Roman Wilson's 37. Ty Johnson is Buffalo's RB3, behind the very player
    # the model wanted to drop, and was inactive with a hamstring. Both were one
    # claim away from being submitted.
    #
    # A projection is a forecast of production. It is not evidence that a player
    # is on the field. Where a snap count exists, the snap count decides.
    pk = key(player) if player else None
    if pk and ROLES:
        if pk in ROLES.get('add_no', {}) and kind == 'add':
            r.add('G11-role-registry', BLOCK,
                  f'VERIFIED NOT PLAYING — {ROLES["add_no"][pk]}')
        elif pk in ROLES.get('unavailable', {}) and kind == 'add':
            r.add('G11-role-registry', BLOCK,
                  f'VERIFIED UNAVAILABLE — {ROLES["unavailable"][pk]}')
        elif pk in ROLES.get('hold', {}) and kind == 'drop':
            h = ROLES['hold'][pk]
            r.add('G11-role-registry', BLOCK, f'HOLD ON RECORD — {h["call"]}')
        elif pk in ROLES.get('add_yes', {}):
            a = ROLES['add_yes'][pk]
            r.add('G11-role-registry', OK, f'usage verified — {a["usage_wk1"]}')
        elif pk in ROLES.get('drop_ok', {}):
            d = ROLES['drop_ok'][pk]
            sev = OK if kind == 'drop' else WARN
            r.add('G11-role-registry', sev, f'{d["call"]}')
        elif pos in ('DEF', 'K'):
            # A team defense has no snap count and a kicker's is meaningless.
            # Warning here would downgrade every legitimate DEF/K call to WARN
            # and train the reader to ignore this gate, which is worse than not
            # having it.
            r.add('G11-role-registry', OK, f'{pos} — snap count does not apply')
        else:
            # For an ADD or a DROP the absence of a snap count is a real gap: it
            # is exactly the state the Bernard and Ty Johnson claims were in. For
            # a start/sit on a player already rostered it is informational, so it
            # is said out loud without downgrading the verdict.
            if usage:
                # the weekly usage pull (lib/usage.py) IS a snap count: verified
                # 2-of-3 against Sleeper's stats feed, not beat reporting, but an
                # observation of the field all the same.
                r.add('G11-role-registry', OK, f'snap count observed (week pull) — {usage}')
            elif pk in ROLES.get('_demoted_add_yes', {}):
                # verified once, but long enough ago that it is history, not a role
                # (rules.demote_add_yes: 14 days). Said out loud, not counted.
                d = ROLES['_demoted_add_yes'][pk]
                sev = WARN if kind in ('add', 'drop') else OK
                r.add('G11-role-registry', sev,
                      f"registry usage verified {d.get('as_of')} ({d.get('demoted')}) — DEMOTED after {14} days; re-verify before counting it")
            else:
                sev = WARN if kind in ('add', 'drop') else OK
                r.add('G11-role-registry', sev,
                      'no verified snap count on record — projection is the only evidence he plays')
    return r


def record(kind, subject, call, verdict, note='', league='BSB', state=None, **kw):
    """Kept for the older scripts. Writes to the ledger."""
    from . import ledger as LG
    return LG.propose(league, kind, subject, call, detail=note, verdict=verdict, state=state, **kw)
