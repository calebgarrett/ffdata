#!/usr/bin/env python3
"""Parse the logged-out Yahoo Fantasy pages the pump fetches into CSVs.
Standard library only (regex over a whitespace-collapsed page; the only nested
tables are inside data-tooltip attributes, which are stripped first).

  parse_team(html)         -> (owner, record, [row...])   row: slot,player,pid,nfl,pos,status,game,bye,fan_pts,proj_pts
  parse_matchup(html)      -> [dict(side, owner, team_id, record, total, proj, rows=[...])]
  parse_transactions(html) -> [dict(ts, team, team_id, player, pid, nfl, pos, status, kind, action)]
"""
import re, html as H

def _clean(h):
    h = re.sub(r'data-tooltip="[^"]*"', '', h)
    return re.sub(r'\s+', ' ', h)

def _text(s):
    return H.unescape(re.sub(r'<[^>]+>', ' ', s)).replace('\xa0', ' ').strip()

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
    nums = []
    for c in cells:
        if re.fullmatch(r'-?\d+(\.\d+)?|–|-|\d+%', c): nums.append(c)
    return dict(slot=slot.group(1), player=H.unescape(name.group(1)), pid=pid.group(1) if pid else '',
                nfl=tp.group(1).upper() if tp else '', pos=tp.group(2) if tp else '',
                status=st.group(1) if st else '', game=game, _nums=nums)

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
        for r in _rows(h[i:j]):
            p = _player_row(r)
            if not p: continue
            nums = p.pop('_nums', [])
            # team page order: bye, fan pts, proj pts, %start, %ros
            p['bye'] = nums[0] if nums else ''
            p['fan_pts'] = nums[1] if len(nums) > 1 else ''
            p['proj_pts'] = nums[2] if len(nums) > 2 else ''
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

def parse_matchup(h):
    """The matchup page lists both lineups side by side: each starter row is
    [my player | proj | fan | slot | slot | slot | fan | proj | their player]."""
    h = _clean(h)
    teams = []
    for m in re.finditer(r'<a class="F-link" href="https://football\.fantasysports\.yahoo\.com/f1/\d+/(\d+)">([^<]+)</a>.*?<div>(\d+-\d+-\d+) \| (\d+)(?:st|nd|rd|th)</div>', h):
        teams.append(dict(team_id=m.group(1), owner=H.unescape(m.group(2)), record=m.group(3), rank=m.group(4), rows=[]))
    if len(teams) < 2: return teams
    scores = re.findall(r"<td class='Fz-xxl Ta-(?:end|start) P(?:end|start)-lg'>([\d.]+)</td>", h)
    projs = re.findall(r"<td class='F-shade Ta-(?:end|start) P(?:end|start)-lg Fz-med Ptop-med'>([\d.]+)</td>", h)
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
            nums = [c for c in cells if re.fullmatch(r'-?\d+(\.\d+)?|–|-', c)]
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
            nm = re.search(r'players/(\d+)" target="sports">([^<]+)</a>', blk)
            tp = re.search(r'class="F-position Fz-xxs">([A-Za-z]{2,3}) - ([A-Z,]+)</span>', blk)
            st = re.search(r'class="F-injury[^"]*"[^>]*>([A-Za-z\-]+)</span>', blk)
            kind = re.search(r'<h6[^>]*>([^<]*)</h6>', blk)
            if not nm: continue
            kind = _text(kind.group(1)) if kind else ''
            action = 'drop' if kind.lower().startswith('to ') else 'add' if kind else ''
            out.append(dict(ts=_text(ts.group(1)) if ts else '', team=H.unescape(team.group(2)), team_id=team.group(1),
                            player=H.unescape(nm.group(2)), pid=nm.group(1), nfl=tp.group(1).upper() if tp else '',
                            pos=tp.group(2) if tp else '', status=st.group(1) if st else '', kind=kind, action=action))
    return out

if __name__ == '__main__':
    import sys, json
    kind, path = sys.argv[1], sys.argv[2]
    h = open(path).read()
    res = {'team': parse_team, 'matchup': parse_matchup, 'transactions': parse_transactions}[kind](h)
    print(json.dumps(res, indent=1)[:6000])
