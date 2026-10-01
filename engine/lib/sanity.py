"""SANITY READ — the card is read back as a manager would read it, before it ships.

The regression suite replays failures that have already happened. This is the
other kind of check: invariants that must hold on EVERY card whatever the
inputs, judged on the run object and on the rendered HTML. Any trip refuses the
card (09-29: a torn ACL sat under a START pill for five hours because no old
failure looked like that one).

  1. No starter Yahoo tags OUT (O/IR/PUP/SUSP/NA/CEL) carries a START pill.
  2. No OUT starter stays in the optimal lineup while a bench player can fill his slot.
  3. No proposed add is already on a roster in that league.
  4. No proposed drop is a player Caleb does not have.
  5. No proposed add is a player Caleb dropped in either league in the last 7 days.
  6. No Decide tile names a lineup change involving a locked or final player.
  7. The masthead week is the engine's data week.
  8. A 'move to IR' tile exists for every starter tagged IR/O with a verified season-ending entry while an IR slot is free.
"""
import re, html as _html
from . import state as ST, clock as C
from .names import key

UNUSABLE = {'IR', 'IR-R', 'O', 'NA', 'PUP', 'PUP-R', 'SUSP', 'CEL'}

def _text(h):
    return _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', h)))

def check(run, page):
    """-> list of failure strings (empty = ship)."""
    bad = []
    # 1. START pill on an OUT starter
    for lg, R in run['leagues'].items():
        st = R['state']
        outs = {r['player'] for r in st.starters() if r['designation'] in UNUSABLE}
        for m in re.finditer(r'<td class="name">([^<]+)<small>[^<]*</small></td><td class="pts">[^<]*</td><td class="st"><span class="pill p-start">START</span>', page):
            if m.group(1) in outs: bad.append(f'{lg}: START pill on {m.group(1)}, who is tagged OUT')
        # 2. OUT starter kept in the optimal lineup with a bench replacement available
        lu = R['lineup']
        opt = {x['key'] for x in lu['optimal'].values() if x}
        for r in st.starters():
            if r['designation'] in UNUSABLE and r['key'] in opt:
                kick = run['proj'].kickoff(r['tm'])
                if kick and kick <= C.now(): continue                    # locked: nothing to do
                if any(b['designation'] not in UNUSABLE and (b['elig'] & r['elig']) for b in st.bench()):
                    bad.append(f'{lg}: {r["player"]} ({r["designation"]}) is still in the optimal lineup with a usable bench player at his position')
        # 3/4/5. adds and drops named on the card
        dropped = ST.recently_dropped_anywhere()
        adds, drops = [], []
        for c in R.get('calls', []):
            if c['kind'] == 'swap' and c['ledger']['status'] == 'proposed':
                adds.append(c['item']['add']['name']); drops.append(c['item']['drop']['player'])
        for c in R.get('stream_calls', []):
            if c['ledger']['status'] == 'proposed':
                adds.append(c['add']['name'])
                if c['drop']: drops.append(c['drop']['player'])
        for x in (R.get('breakout') or {}).get('rows', []):
            if x['move']['verb'] in ('ADD', 'ADD-DEAD'):
                adds.append(x['name'])
                d = x['move'].get('drop')
                if d and not str(d).startswith(('an open', 'the spot')): drops.append(d)
        for a in adds:
            o = st.owner_of(a)
            if o: bad.append(f'{lg}: proposes adding {a}, who is on {o}\'s roster')
            if key(a) in dropped: bad.append(f'{lg}: proposes adding {a}, whom Caleb dropped on {dropped[key(a)][1]} ({dropped[key(a)][0]})')
        for d in drops:
            if not st.row_of(d): bad.append(f'{lg}: proposes dropping {d}, who is not on the roster')
        # 6. decided lineup tiles never involve a locked/final player
        for c in R.get('calls', []):
            if c['kind'] == 'start' and c['ledger']['status'] == 'proposed' and not c['change']['provisional']:
                ch = c['change']
                for p in (ch['start'], ch['sit']):
                    if p and (p.get('final') or p.get('live') or p.get('phase') == 'locked'):
                        bad.append(f'{lg}: decided lineup change involves {p["player"]}, whose game has kicked off')
        # 8. IR move tile for a verified season-ending starter
        w = R.get('wire')
        if w is not None:
            free_ir = st.cfg.ir_slots - len(st.ir())
            for r in st.starters():
                reg = (w.drop_ok.get(r['key']) or {})
                if reg.get('ir') and r['designation'] in ('IR', 'O') and free_ir > 0 and f'move to IR</span><div class="mv">{_html.escape(r["player"])}' not in page:
                    bad.append(f'{lg}: {r["player"]} is verified season-ending with a free IR slot and no IR tile on the card')
    # 9. no Decide tile carries a BLOCK verdict without saying so in its label
    i = page.find('class="dcards"'); j = page.find('<div class="decide">', i + 1)
    for t in re.findall(r'<div class="dcard[^"]*">.*?</div></div>', page[i:j] if i >= 0 else '', flags=re.S):
        if 'gate BLOCK' in t or '/BLOCK' in t:
            lab = re.search(r'<span class="lg">(.*?)</span>', t)
            if lab and 'BLOCKED' not in lab.group(1): bad.append(f'Decide tile "{_text(lab.group(1))}" carries a BLOCK verdict but is presented as an action')
    # 7. masthead week
    m = re.search(r'NFL Week (\d+)', page)
    if m and int(m.group(1)) != run['week']: bad.append(f'masthead says week {m.group(1)}, engine week is {run["week"]}')
    return bad
