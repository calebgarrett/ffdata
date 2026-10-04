"""ONE CLOCK.

Every date and time in this system comes from here, in US Eastern, and nowhere
else. The container runs on UTC; on 2026-09-10 TZ=America/Indianapolis silently
returned UTC and produced a four-hour error, and on 2026-09-16 the container date
was already Wednesday while Caleb was still on Tuesday night with waivers pending.
A system that cannot say what day it is cannot say what locks tonight.
"""
import datetime as dt
dt_ = dt
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')

# 2026 regular season: week 1 opened Wednesday 2026-09-09 (NE @ SEA). Week N
# starts on the Tuesday 07:00 ET after week N-1's Monday game -- Tuesday is when
# Yahoo rolls the week and when waiver claims for the new week become live.
WEEK1_TUESDAY = dt.datetime(2026, 9, 8, 7, 0, tzinfo=ET)

def now():
    """Now, in ET. FF_NOW (env, ISO; naive = ET) pins the clock — the scenario
    harness uses it so a fixture decides as of its own moment, not the container's."""
    import os
    pin = os.environ.get('FF_NOW')
    if pin:
        from . import ts as T          # one parser; 'legacy' = any ISO, naive = ET
        return T.parse_ts(pin, 'legacy', now=dt.datetime.now(ET)).astimezone(ET)
    return dt.datetime.now(ET)

def today():
    return now().date()

def nfl_week(t=None):
    t = t or now()
    if t < WEEK1_TUESDAY: return 0
    return 1 + (t - WEEK1_TUESDAY).days // 7

def data_week():
    """The NFL week the engine should RUN for: the calendar week once its Sleeper
    projections are on disk, else the previous week (Tuesday morning, 09-29: the
    calendar rolled to week 4 at 7 am, the pump had pulled at 2:49 am with week-3
    files, and every projection test failed on files that did not exist yet).
    The card then keeps showing the finished week's finals until week N's data lands."""
    import os
    w = nfl_week()
    from . import paths as _paths
    D = _paths.data('')
    if os.path.exists(D + f'sleeper_off_wk{w}.csv'): return w
    if w > 1 and os.path.exists(D + f'sleeper_off_wk{w - 1}.csv'): return w - 1
    return w

def week_start(w):
    return WEEK1_TUESDAY + dt.timedelta(weeks=w - 1)

def stamp(t=None):
    """Human stamp for cards and logs: 'Tue Sep 15, 9:45 pm ET'."""
    t = t or now()
    return t.strftime('%a %b %-d, %-I:%M %p ET').replace('AM', 'am').replace('PM', 'pm')

def iso(t=None):
    return (t or now()).isoformat(timespec='minutes')

def parse_kick(s):
    """ESPN/Sleeper kickoffs arrive as ISO UTC ('2026-09-18T00:15Z'). -> aware ET."""
    if not s: return None
    from . import ts as T          # one parser (lib/ts.py); a kickoff must carry its zone
    return T.try_ts(s, 'espn')

def hours_until(kick):
    if kick is None: return None
    return (kick - now()).total_seconds() / 3600

# Caleb, 2026-09-15: "Don't worry about lineup changes unless it's at least 1 day
# before the game. In terms of warning me about it. The focus earlier in the week
# is roster construction for the coming weeks and season."
LINEUP_HORIZON_H = 36     # a lineup call is worth surfacing inside this window
ALERT_HORIZON_H  = 24     # and worth a warning inside this one

def lineup_phase(kick):
    """'locked' | 'alert' | 'decide' | 'early' for a game at `kick`."""
    h = hours_until(kick)
    if h is None: return 'unknown'
    if h <= 0: return 'locked'
    if h <= ALERT_HORIZON_H: return 'alert'
    if h <= LINEUP_HORIZON_H: return 'decide'
    return 'early'

def bsb_waiver_deadline(w=None):
    """BSB waivers process Wednesday morning; claims must be in by Tuesday night.
    Returns the Wednesday 06:00 ET of the given (or current) week."""
    w = w or nfl_week()
    return week_start(w) + dt.timedelta(days=1, hours=-1)   # Wed 06:00

def age_hours(iso_s):
    """Age of an ISO timestamp (any zone) in hours, or None."""
    if not iso_s: return None
    from . import ts as T          # one parser; 'legacy' keeps this function's naive-is-ET contract
    t = T.try_ts(iso_s, 'legacy')
    if t is None: return None
    return (now() - t).total_seconds() / 3600
