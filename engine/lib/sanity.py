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
 11. The planner's moves, applied in order to a copy of the roster, keep it legal at every
     step (roster <= slots + bench, IR <= IR slots with an eligible tag, every drop/IR/start
     is on the roster, no add is owned), each spot is used once, the HH acquisition and BSB
     FAB budgets hold, and — with FF_PLANNER=1 — every move has a tile on the card.
"""
import re, html as _html
from . import state as ST, clock as C
from .names import key

from .rules import UNUSABLE, locked as _locked

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
                    if p and _locked(p):
                        bad.append(f'{lg}: decided lineup change involves {p["player"]}, whose game has kicked off')
        # 8. IR move tile for a verified season-ending starter
        w = R.get('wire')
        if w is not None:
            free_ir = st.cfg.ir_slots - len(st.ir())
            for r in st.starters():
                reg = (w.drop_ok.get(r['key']) or {})
                if reg.get('ir') and r['designation'] in ('IR', 'O') and free_ir > 0 and f'move to IR</span><div class="mv">{_html.escape(r["player"])}' not in page:
                    bad.append(f'{lg}: {r["player"]} is verified season-ending with a free IR slot and no IR tile on the card')
    # 10. a proposed DEF add never matches a rostered defense's NFL team (names aside)
    for lg, R in run['leagues'].items():
        st = R['state']
        owned = {r['tm'] for r in st.rows if (r.get('pos') or '').upper() == 'DEF' and r['tm']}
        names = []
        wu = R.get('week_upgrade')
        if wu and wu['call']['item']['fam'] == 'DEF': names.append((wu['call']['item']['add']['name'], wu['call']['item']['add'].get('tm')))
        for c in R.get('stream_calls', []):
            if c['fam'] == 'DEF' and c['ledger']['status'] == 'proposed': names.append((c['add']['name'], c['add'].get('tm')))
        for c in R.get('calls', []):
            if c['kind'] == 'swap' and c['ledger']['status'] == 'proposed' and c['item']['add'].get('fam') == 'DEF': names.append((c['item']['add']['name'], c['item']['add'].get('tm')))
        for nm, tm in names:
            k = key(nm); code = k[4:] if k.startswith('DST:') else (tm or '')
            if code and code in owned: bad.append(f'{lg}: proposes adding the {nm} defense, which is rostered (team {code})')
    # 9. no Decide tile carries a BLOCK verdict without saying so in its label
    i = page.find('class="dcards"'); j = page.find('<div class="decide">', i + 1)
    for t in re.findall(r'<div class="dcard[^"]*">.*?</div></div>', page[i:j] if i >= 0 else '', flags=re.S):
        if 'gate BLOCK' in t or '/BLOCK' in t:
            lab = re.search(r'<span class="lg">(.*?)</span>', t)
            if lab and 'BLOCKED' not in lab.group(1): bad.append(f'Decide tile "{_text(lab.group(1))}" carries a BLOCK verdict but is presented as an action')
    # 7. masthead week
    m = re.search(r'NFL Week (\d+)', page)
    if m and int(m.group(1)) != run['week']: bad.append(f'masthead says week {m.group(1)}, engine week is {run["week"]}')
    # 11. the plan, simulated — it refuses the card only when the plan IS the card
    # (FF_PLANNER=1); in shadow mode ff.shadow_plan reports it in data/plan_diff.txt
    import os
    if os.environ.get('FF_PLANNER') == '1':
        bad += check_plan(run, page)
    return bad

def check_plan(run, page=None):
    """Apply each league's Plan.moves in order to a copy of the state. -> failures."""
    import os
    from . import plan as PL
    from .facts import IR_TAGS
    bad = []
    plans = run.get('plans') or {}
    tiles_on = os.environ.get('FF_PLANNER') == '1' and page is not None
    dec = ''
    if tiles_on:
        i = page.find('<h2>Decide'); j = page.find('<h2>Outlook')
        dec = _html.unescape(page[i:j] if i >= 0 and j > i else '')
        allp = _html.unescape(page)
    for lg, p in plans.items():
        if not isinstance(p, PL.Plan): continue                 # shadow mode: a planner failure is reported in plan_diff
        R = run['leagues'][lg]; st = R['state']; cfg = st.cfg
        active = {r['key']: r for r in st.mine if r['slot'] != 'IR'}
        ir = {r['key']: r for r in st.mine if r['slot'] == 'IR'}
        size = len(cfg.slots) + cfg.bench
        spots, adds_now, adds_next, fab = set(), 0, 0, 0
        for mv in p.moves:
            sid = mv.get('spot_id')
            if sid and mv['kind'] == 'add':
                if sid in spots: bad.append(f'{lg}: plan uses spot {sid} twice')
                spots.add(sid)
            if mv['provisional'] and mv['kind'] == 'ir': continue        # ASK: not applied
            for t in mv['txns']:
                k = t['key']; op = t['op']
                if op == 'ir':
                    if k not in active: bad.append(f'{lg}: plan moves {t["player"]} to IR but he is not on the active roster'); continue
                    if active[k].get('designation') not in IR_TAGS: bad.append(f'{lg}: plan moves {t["player"]} to IR with tag {active[k].get("designation")} (not IR-eligible on the firm plan)')
                    ir[k] = active.pop(k)
                    if len(ir) > cfg.ir_slots: bad.append(f'{lg}: plan puts {len(ir)} players on IR, {cfg.ir_slots} slots')
                elif op == 'drop':
                    if k not in active: bad.append(f'{lg}: plan drops {t["player"]}, who is not on the active roster')
                    active.pop(k, None)
                elif op in ('add', 'claim'):
                    o = st.owner_of(k)
                    if k in active or k in ir: bad.append(f'{lg}: plan adds {t["player"]}, who is already yours')
                    elif o: bad.append(f'{lg}: plan adds {t["player"]}, who is on {o}\'s roster')
                    active[k] = dict(key=k, player=t['player'], designation='none')
                    if mv.get('eff') == 'W+1': adds_next += 1
                    else: adds_now += 1
                    if op == 'claim': fab += t.get('bid') or 0
                elif op in ('start', 'bench'):
                    if k not in active: bad.append(f'{lg}: plan lineup move names {t["player"]}, who is not on the roster after the moves')
            if len(active) > size: bad.append(f'{lg}: after "{mv["id"]}" the active roster is {len(active)} > {size}')
        b = p.budgets or {}
        if lg == 'HH' and b.get('acq_left') is not None and adds_now > b['acq_left']:
            bad.append(f'{lg}: plan makes {adds_now} adds this week, {b["acq_left"]} acquisitions left')
        if lg == 'HH' and cfg.acq_cap is not None and adds_next > cfg.acq_cap:
            bad.append(f'{lg}: plan makes {adds_next} adds next week, cap {cfg.acq_cap}')
        if lg == 'BSB' and b.get('fab_left') is not None and fab > b['fab_left']:
            bad.append(f'{lg}: plan bids ${fab}, ${b["fab_left"]} FAB left')
        if tiles_on:
            for mv in p.moves:
                who = mv.get('add_name') or mv.get('ir_name') or mv.get('start')
                where = allp if mv['provisional'] else dec
                if who and who not in where:
                    bad.append(f'{lg}: plan move "{mv["id"]}" has no tile on the card' + ('' if mv['provisional'] else ' (Decide)'))
    return bad
