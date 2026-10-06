#!/usr/bin/env python3
"""Parse the logged-out Yahoo Fantasy pages the pump fetches into CSVs.
Standard library only (regex over a whitespace-collapsed page; the only nested
tables are inside data-tooltip attributes, which are stripped first).

  parse_team(html)         -> (owner, record, rank, [row...])   row: slot,player,pid,nfl,pos,status,game,bye,fan_pts,proj_pts
  parse_matchup(html)      -> [dict(side, owner, team_id, record, total, proj, rows=[...])]
  parse_transactions(html) -> [dict(ts, team, team_id, player, pid, nfl, pos, status, kind, action)]

v6 (10-06): points columns are read by their HEADER label when the table has one
(in-game pages change what the cells hold, not where they are); a percentage, a
live 'Q3 12.3' or an em dash is never a points value; matchup totals tolerate the
in-game markup; team defenses in the transactions log (they link to the NFL team
page, not a player id) are rows like any other. Every new path falls back to the
v5 read when the markup is not what it expects.
"""
import re, html as H

NUM = re.compile(r'-?\d+(\.\d+)?|[–—-]')        # a points/bye cell: a number or a dash (en, em, hyphen)

def _clean(h):
    h = re.sub(r'data-tooltip="[^"]*"', '', h)
    return re.sub(r'\s+', ' ', h)

def _text(s):
    return H.unescape(re.sub(r'<[^>]+>', ' ', s)).replace('\xa0', ' ').strip()

def _num(c):
    """A stats cell's text -> itself when it is a clean number or dash, else ''."""
    c = re.sub(r'\s+', ' ', (c or '')).strip()
    return c if NUM.fullmatch(c) else ''

def _header_map(table):
    """Column label -> cell index from the table's <thead> (its last header row),
    or {} when there is no usable header. Yahoo stacks a group row over the
    column row; the column row is the last one. 'n' is the header cell count,
    used to confirm the body rows line up with it."""
    m = re.search(r'<thead.*?</thead>', table)
    if not m: return {}
    hrows = re.findall(r'<tr[^>]*>.*?</tr>', m.group(0)) or [m.group(0)]
    ths = re.findall(r'<th[^>]*>(.*?)</th>', hrows[-1])
    out = dict(n=len(ths))
    for i, t in enumerate(ths):
        l = re.sub(r'\s+', ' ', _text(t)).lower()
        if l == 'bye': out['bye'] = i
        elif l.startswith('fan pts'): out['fan_pts'] = i
        elif l.startswith('proj pts') or l == 'proj': out['proj_pts'] = i
    return out if ('fan_pts' in out or 'proj_pts' in out) else {}

def _rows(table):
    body = table[table.find('<tbody'):] if '<tbody' in table else table
    return re.findall(r'<tr[^>]*>.*?</tr>', body)

def _player_row(r):
    """One roster/matchup row -> dict or None (skips empty slots and footers)."""
    slot = re.search(r'data-pos="([^"]+)"', r)
    name = re.search(r'class="Nowrap name F-link playernote"[^>]*title="([^"]+)"', r)
    if not slot: return None
    if not name:
        return dict(slot=slot.group(1), player='', pid='', nfl='', pos='', status='', game='', bye='', fan_pts='', proj_pts='')
    pid = re.search(r'data-ys-playerid="(\d+)"', r)
    tp = re.search(r'<span class="Fz-xxs">([A-Za-z]{2,3}) - ([A-Z,]+)</span>', r)
    st = re.search(r'class="ysf-player-status[^"]*"><span[^>]*>([A-Za-z\-]+)</span>', r)
    gm = re.search(r'class="ysf-game-status[^"]*">(.*?)</span>\s*<span class="tooltip|class="ysf-game-status[^"]*">(.*?)</div>', r)
    game = _text(gm.group(1) or gm.group(2)) if gm else ''
    game = re.sub(r'\s+', ' ', game).strip()
    # cells after the player cell: bye, fan pts, proj pts (matchup rows have no bye)
    cells = [_text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', r)]
    nums = [c for c in cells if NUM.fullmatch(c)]                  # a percentage is not a number here
    return dict(slot=slot.group(1), player=H.unescape(name.group(1)), pid=pid.group(1) if pid else '',
                nfl=tp.group(1).upper() if tp else '', pos=tp.group(2) if tp else '',
                status=st.group(1) if st else '', game=game, _nums=nums, _cells=cells)

def _fill_points(p, hm):
    """bye / fan_pts / proj_pts for a parsed row: by header label when the row lines
    up with the header, else the v5 positional read (bye, fan pts, proj pts)."""
    nums = p.pop('_nums', []); cells = p.pop('_cells', [])
    if hm and hm.get('n') == len(cells):
        p['bye'] = _num(cells[hm['bye']]) if 'bye' in hm else (nums[0] if nums else '')
        p['fan_pts'] = _num(cells[hm['fan_pts']]) if 'fan_pts' in hm else ''
        p['proj_pts'] = _num(cells[hm['proj_pts']]) if 'proj_pts' in hm else ''
        p['_by'] = 'header'
    else:
        p['bye'] = nums[0] if nums else ''
        p['fan_pts'] = nums[1] if len(nums) > 1 else ''
        p['proj_pts'] = nums[2] if len(nums) > 2 else ''
        p['_by'] = 'position'
    return p

def parse_team(h):
    h = _clean(h)
    owner = re.search(r'<title>[^<]*? - (.*?) \| Fantasy Football', h)
    owner = H.unescape(owner.group(1)).strip() if owner else ''
    rec = re.search(r'<span class="Fw-b Fz-xxl">(\d+-\d+-\d+)</span><em[^>]*>(\d+)<sup>', h)
    record = rec.group(1) if rec else ''
    rank = rec.group(2) if rec else ''
    pf = re.search(r'Place</em></div><div><span class="Fw-b Fz-xxl">([\d.]+)</span>', h)
    record = record + (f' PF {pf.group(1)}' if pf else '')
    out = []
    for tid in ('statTable0', 'statTable1', 'statTable2', 'statTable3', 'statTable4'):
        i = h.find(f'id="{tid}"')
        if i < 0: continue
        j = h.find('</table>', i)
        table = h[i:j]
        hm = _header_map(table)
        for r in _rows(table):
            p = _player_row(r)
            if not p: continue
            if '_cells' in p: p = _fill_points(p, hm)
            p.pop('_by', None)
            out.append(p)
    return owner, record, rank, out

def _player_block(seg):
    """Fields for one player from the segment of a row that belongs to him."""
    pid = re.search(r'data-ys-playerid="(\d+)"', seg)
    tp = re.search(r'<span class="Fz-xxs">([A-Za-z]{2,3}) - ([A-Z,]+)</span>', seg)
    st = re.search(r'class="ysf-player-status[^"]*"><span[^>]*>([A-Za-z\-]+)</span>', seg)
    gm = re.search(r'class="ysf-game-status[^"]*">(.*?)</div>', seg)
    game = re.sub(r'\s+', ' ', _text(gm.group(1))).strip() if gm else ''
    return dict(pid=pid.group(1) if pid else '', nfl=tp.group(1).upper() if tp else '', pos=tp.group(2) if tp else '',
                status=st.group(1) if st else '', game=game)

def _cells_by_class(h, must):
    """Clean numbers from every <td> whose class attribute (either quote style)
    carries all the `must` tokens; nested tags inside the cell are fine."""
    out = []
    for m in re.finditer(r'<td[^>]*class=(["\'])(.*?)\1[^>]*>(.*?)</td>', h):
        cls = m.group(2)
        if all(t in cls for t in must):
            v = re.sub(r'\s+', '', _text(m.group(3)))
            if re.fullmatch(r'\d+(\.\d+)?', v): out.append(v)
    return out

def parse_matchup(h):
    """The matchup page lists both lineups side by side: each starter row is
    [my player | proj | fan | slot | slot | slot | fan | proj | their player]."""
    h = _clean(h)
    teams = []
    for m in re.finditer(r'<a class="F-link" href="https://football\.fantasysports\.yahoo\.com/f1/\d+/(\d+)">([^<]+)</a>.*?<div>(\d+-\d+-\d+) \| (\d+)(?:st|nd|rd|th)</div>', h):
        teams.append(dict(team_id=m.group(1), owner=H.unescape(m.group(2)), record=m.group(3), rank=m.group(4), rows=[]))
    if len(teams) < 2:
        # in-game header: the record/rank div may be split by live markup — take the team links alone
        for m in re.finditer(r'<a class="F-link" href="https://football\.fantasysports\.yahoo\.com/f1/\d+/(\d+)">([^<]+)</a>', h):
            if m.group(1) in [t['team_id'] for t in teams]: continue
            rr = re.search(r'(\d+-\d+-\d+)\s*\|\s*(\d+)(?:st|nd|rd|th)', h[m.end():m.end() + 600])
            teams.append(dict(team_id=m.group(1), owner=H.unescape(m.group(2)), record=rr.group(1) if rr else '', rank=rr.group(2) if rr else '', rows=[]))
            if len(teams) == 2: break
    if len(teams) < 2: return teams
    scores = re.findall(r"<td class='Fz-xxl Ta-(?:end|start) P(?:end|start)-lg'>([\d.]+)</td>", h)
    projs = re.findall(r"<td class='F-shade Ta-(?:end|start) P(?:end|start)-lg Fz-med Ptop-med'>([\d.]+)</td>", h)
    if len(scores) < 2: scores = _cells_by_class(h, ('Fz-xxl',))                       # live totals, in-game markup
    if len(projs) < 2: projs = _cells_by_class(h, ('F-shade', 'Ptop-med'))
    for k, t in enumerate(teams[:2]):
        t['side'] = 'me' if k == 0 else 'opp'
        t['total'] = scores[k] if len(scores) > k else ''
        t['proj'] = projs[k] if len(projs) > k else ''
    for tid in ('statTable1', 'statTable2', 'statTable3'):
        i = h.find(f'id="{tid}"')
        if i < 0: continue
        j = h.find('</table>', i)
        for r in _rows(h[i:j]):
            slots = re.findall(r'data-pos="([^"]+)"', r)
            if not slots: continue
            slot = slots[0]
            names = [(m.start(), H.unescape(m.group(1))) for m in re.finditer(r'class="Nowrap name F-link playernote"[^>]*title="([^"]+)"', r)]
            cells = [_text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', r)]
            nums = [c for c in cells if NUM.fullmatch(c)]
            # which side each name is on: before or after the middle slot cell
            mid = r.find('data-pos="', r.find('data-pos="') + 1)
            for pos_, nm in names:
                side = 0 if pos_ < mid else 1
                nxt = min([p for p, _ in names if p > pos_] + [len(r)])
                blk = _player_block(r[pos_:nxt])
                if side == 0: proj, fan = (nums[0] if nums else ''), (nums[1] if len(nums) > 1 else '')
                else:         fan, proj = (nums[-2] if len(nums) > 1 else ''), (nums[-1] if nums else '')
                teams[side]['rows'].append(dict(slot=slot, player=nm, fan_pts=fan, proj_pts=proj, bye='', **blk))
    return teams[:2]

def parse_transactions(h):
    h = _clean(h)
    out = []
    for r in re.findall(r'<tr[^>]*>.*?</tr>', h):
        if 'Tst-team-name' not in r: continue
        team = re.search(r'class="Tst-team-name" href="[^"]*/f1/\d+/(\d+)">([^<]+)</a>', r)
        ts = re.search(r'class="Block F-timestamp[^"]*">([^<]+)</span>', r)
        if not team: continue
        for blk in re.findall(r'<div class="Pbot-xs">(.*?)</div>', r):
            pid, pname = '', ''
            nm = re.search(r'players/(\d+)"[^>]*target="sports">([^<]+)</a>', blk)
            if nm: pid, pname = nm.group(1), nm.group(2)
            else:
                # a team defense links to the NFL team page (…/nfl/teams/min/), not a player id;
                # any other sports.yahoo.com link keeps the name with no id
                nm = re.search(r'href="https://sports\.yahoo\.com/nfl/teams/([a-z]{2,3})/?"[^>]*target="sports">([^<]+)</a>', blk) \
                     or re.search(r'href="https://sports\.yahoo\.com/[^"]*"[^>]*target="sports">()([^<]+)</a>', blk)
                if nm: pid, pname = nm.group(1).upper(), nm.group(2)
            tp = re.search(r'class="F-position Fz-xxs">([A-Za-z]{2,3}) - ([A-Z,]+)</span>', blk)
            st = re.search(r'class="F-injury[^"]*"[^>]*>([A-Za-z\-]+)</span>', blk)
            kind = re.search(r'<h6[^>]*>([^<]*)</h6>', blk)
            if not pname: continue
            kind = _text(kind.group(1)) if kind else ''
            action = 'drop' if kind.lower().startswith('to ') else 'add' if kind else ''
            out.append(dict(ts=_text(ts.group(1)) if ts else '', team=H.unescape(team.group(2)), team_id=team.group(1),
                            player=H.unescape(pname).strip(), pid=pid, nfl=tp.group(1).upper() if tp else '',
                            pos=tp.group(2) if tp else '', status=st.group(1) if st else '', kind=kind, action=action))
    return out

def suspicious(rows):
    """Rows whose points columns hold something other than a number or dash — the
    pump saves that page's HTML so the parser can be fixed against real markup."""
    bad = []
    for r in rows:
        for c in ('fan_pts', 'proj_pts'):
            v = (r.get(c) or '').strip()
            if v and not NUM.fullmatch(v): bad.append((r.get('player'), c, v))
    return bad

if __name__ == '__main__':
    import sys, json
    kind, path = sys.argv[1], sys.argv[2]
    h = open(path).read()
    res = {'team': parse_team, 'matchup': parse_matchup, 'transactions': parse_transactions}[kind](h)
    print(json.dumps(res, indent=1)[:6000])
