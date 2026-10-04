"""ONE TIMESTAMP PARSER.

Every timestamp that enters a decision is parsed here, by `parse_ts(s, source)`,
and comes back as a tz-aware US Eastern datetime. Before this module the system
had a dozen ad-hoc strptime calls, each with its own idea of the zone: the
container runs on UTC, Yahoo prints Eastern without saying so, Kalshi and the pump
stamp UTC with an offset, the snapshot names are Eastern wall-clock, and a naive
string read with the wrong assumption is a four-hour error that nothing flags.

The rule: a timestamp must carry its zone (an offset or 'Z') UNLESS its source is
declared below as a naive-Eastern source. A naive string from any other source is
refused (TsError), never guessed. The contract (C2) refuses a run on any input
timestamp that does not parse.

Declared naive-Eastern sources (and only these):
  yahoo_log    'YYYY-MM-DD HH:MM'   data/*_transactions.csv datetime (written by the loader from Yahoo's page, ET)
  yahoo_page   'Sep 28, 9:44 pm'    Yahoo transactions page; year inferred so the stamp is <= now
  yahoo_game   'Sun 1:00 pm'        Yahoo team/matchup page game text; resolved inside the NFL week (week_start=)
  snapshot     'YYYY-MM-DDTHHMM'    data/state/<LG>/<stamp>.json file names (state.save, C.now() ET)
  card         'Sun Oct 4, 1:00 pm' the card's own stamps (C.stamp), year inferred like yahoo_page
  date         'YYYY-MM-DD'         a calendar date, read as ET midnight (registry dates)
  legacy       any ISO, naive = ET  clock.age_hours' historical contract (callers' strings are offset-bearing; kept
                                     so an old snapshot never crashes `ff.py status`)
Zone-bearing forms accepted from any source:
  ISO 8601 with offset or Z ('2026-10-04T08:21:40+00:00', '2026-10-04T13:30Z', '2026-10-04T04:23-04:00')
  compact archive stamp 'YYYY-MM-DDTHHMMZ' (kalshi_archive file names; UTC)
"""
import re, datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
UTC = dt.timezone.utc

NAIVE_ET = {
    'yahoo_log': "transactions CSV 'YYYY-MM-DD HH:MM' (Yahoo, ET)",
    'yahoo_page': "Yahoo transactions page 'Sep 28, 9:44 pm' (ET, year inferred)",
    'yahoo_game': "Yahoo game text 'Sun 1:00 pm' (ET, inside the NFL week)",
    'snapshot': "state snapshot name 'YYYY-MM-DDTHHMM' (ET)",
    'card': "card stamp 'Sun Oct 4, 1:00 pm' (ET, year inferred)",
    'date': "calendar date 'YYYY-MM-DD' (ET midnight)",
    'legacy': 'clock.age_hours historical contract (naive = ET)',
}

class TsError(ValueError):
    pass

_MON = {m: i for i, m in enumerate(('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}
_DOW = {d: i for i, d in enumerate(('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'))}
_COMPACT_Z = re.compile(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})Z$')
_SNAP = re.compile(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2})(\d{2})$')
_PAGE = re.compile(r'^([A-Z][a-z]{2}) (\d{1,2}), (\d{1,2}):(\d{2}) ?([ap]m)$', re.I)
_CARD = re.compile(r'^([A-Z][a-z]{2}) ([A-Z][a-z]{2}) (\d{1,2}), (\d{1,2}):(\d{2}) ?([ap]m)(?: ET)?$', re.I)
_GAME = re.compile(r'^([A-Z][a-z]{2}) (\d{1,2}):(\d{2}) ?([ap]m)\b', re.I)
_PRIVATE = re.compile('[-]')          # Yahoo appends an icon glyph to game text
YEAR_GRACE = dt.timedelta(minutes=10)              # clock skew allowed before a stamp is called 'last year'

def _h24(h, ampm):
    h = int(h) % 12
    return h + 12 if ampm.lower() == 'pm' else h

def _now(now):
    if now is None:
        from . import clock as _C          # one clock: honours FF_NOW
        now = _C.now()
    return now.astimezone(ET)

def _infer_year(month, day, hh, mm, now):
    """The latest year in which this month/day/time is not after `now` (+grace)."""
    n = _now(now)
    for y in (n.year, n.year - 1):
        try: t = dt.datetime(y, month, day, hh, mm, tzinfo=ET)
        except ValueError: continue
        if t <= n + YEAR_GRACE: return t
    raise TsError(f'no year puts {month}/{day} {hh}:{mm:02d} at or before {n:%Y-%m-%d %H:%M}')

def parse_ts(s, source, now=None, week_start=None):
    """-> tz-aware ET datetime. Raises TsError on anything it cannot read honestly.

    source: where the string came from (see the module docstring). Only declared
    naive-ET sources may hand over a string without a zone.
    now: the reference for year inference (yahoo_page, card); default the real clock.
    week_start: the NFL week's Tuesday 07:00 ET, required for yahoo_game."""
    if isinstance(s, dt.datetime):
        if s.tzinfo is None:
            if source not in NAIVE_ET: raise TsError(f'naive datetime from undeclared source {source!r}')
            s = s.replace(tzinfo=ET)
        return s.astimezone(ET)
    if s is None: raise TsError(f'empty timestamp from {source!r}')
    raw = str(s)
    x = _PRIVATE.sub('', raw).strip()
    if not x: raise TsError(f'empty timestamp from {source!r}')
    m = _COMPACT_Z.match(x)
    if m:
        y, mo, d, hh, mi = map(int, m.groups())
        return dt.datetime(y, mo, d, hh, mi, tzinfo=UTC).astimezone(ET)
    if source == 'yahoo_page':
        m = _PAGE.match(x)
        if not m: raise TsError(f'yahoo_page stamp {raw!r} is not "Mon D, H:MM am"')
        mon, d, hh, mi, ap = m.groups()
        if mon.title() not in _MON: raise TsError(f'unknown month in {raw!r}')
        return _infer_year(_MON[mon.title()], int(d), _h24(hh, ap), int(mi), now)
    if source == 'card':
        m = _CARD.match(x)
        if not m: raise TsError(f'card stamp {raw!r} is not "Dow Mon D, H:MM am"')
        _dow, mon, d, hh, mi, ap = m.groups()
        if mon.title() not in _MON: raise TsError(f'unknown month in {raw!r}')
        # the card's own convention (lib/card.py, before this module): the current year
        n = _now(now)
        try: return dt.datetime(n.year, _MON[mon.title()], int(d), _h24(hh, ap), int(mi), tzinfo=ET)
        except ValueError as e: raise TsError(f'{raw!r}: {e}')
    if source == 'yahoo_game':
        m = _GAME.match(x)
        if not m: raise TsError(f'yahoo_game text {raw!r} carries no kickoff time')
        if week_start is None: raise TsError('yahoo_game needs the NFL week_start to place the weekday')
        dow, hh, mi, ap = m.groups()
        if dow.title() not in _DOW: raise TsError(f'unknown weekday in {raw!r}')
        w0 = week_start.astimezone(ET)
        for k in range(8):
            day = (w0 + dt.timedelta(days=k)).date()
            if day.weekday() == _DOW[dow.title()]:
                t = dt.datetime(day.year, day.month, day.day, _h24(hh, ap), int(mi), tzinfo=ET)
                if t >= w0: return t
        raise TsError(f'{raw!r} does not fall inside the week starting {w0:%Y-%m-%d}')
    m = _SNAP.match(x)
    if m:
        if source not in NAIVE_ET: raise TsError(f'naive stamp {raw!r} from undeclared source {source!r}')
        y, mo, d, hh, mi = map(int, m.groups())
        return dt.datetime(y, mo, d, hh, mi, tzinfo=ET)
    y = x[:-1] + '+00:00' if x.endswith('Z') else x
    try:
        t = dt.datetime.fromisoformat(y)
    except ValueError:
        raise TsError(f'unparseable timestamp {raw!r} from {source!r}')
    if t.tzinfo is None:
        if source not in NAIVE_ET:
            raise TsError(f'naive timestamp {raw!r} from undeclared source {source!r} — a zone is required')
        t = t.replace(tzinfo=ET)
    return t.astimezone(ET)

def try_ts(s, source, **kw):
    """parse_ts, or None when it cannot be read (for display paths that must not crash)."""
    try: return parse_ts(s, source, **kw)
    except TsError: return None

def age_h(t, now=None):
    """Hours from `t` (aware) to now."""
    return (_now(now) - t).total_seconds() / 3600.0

def yahoo_game_state(text):
    """'pre' (a kickoff time is printed), 'live' (Q1-4/Half/OT/End), 'final', or 'none' (bye/blank)."""
    g = _PRIVATE.sub('', text or '').strip()
    if not g: return 'none'
    if g.startswith('Final'): return 'final'
    if re.match(r'^(End\s+)?Q[1-4]\b|^Half\b|^OT\b', g): return 'live'
    if _GAME.match(g): return 'pre'
    return 'none'

_TICKER = re.compile(r'^(\d{2})([A-Z]{3})(\d{2})')

def kalshi_event_date(event):
    """Kalshi event tickers carry the game DATE: 'KXNFLREC-26OCT04ARINYG' -> 2026-10-04
    00:00 ET (a calendar date, not an instant). Raises TsError when there is none."""
    tail = str(event or '').split('-', 1)[1] if '-' in str(event or '') else ''
    m = _TICKER.match(tail)
    if not m or m.group(2).title() not in _MON: raise TsError(f'no date in Kalshi event {event!r}')
    try: return dt.datetime(2000 + int(m.group(1)), _MON[m.group(2).title()], int(m.group(3)), tzinfo=ET)
    except ValueError as e: raise TsError(f'{event!r}: {e}')
