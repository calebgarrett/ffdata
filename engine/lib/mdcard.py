"""A Markdown twin of the Lineup Card, for a PRIVATE repo (10-24).

Caleb: "The GitHub repository is listed on my first and last name ... my opponents
will find it pretty easily." A public repo was the price of GitHub Pages; once the repo
is private, Pages is gone (Free plan) and the HTML card has nowhere public to live —
which is the point. GitHub renders Markdown inside a private repo, in the app, to the
owner only. So the engine writes docs/CARD.md next to docs/index.html: the same Decide
calls and Outlook, phone-readable, always as fresh as the last pull.

Decisions first, detail folded (Caleb, 09-25), same as the HTML card.
"""
import json, os
from . import clock as C
from .rules import UNUSABLE

def _rec(st):
    rec = (st.records or {}).get(st.me, {}) if getattr(st, 'records', None) else {}
    recs = (rec.get('record') or '').split(' PF ')
    record = recs[0] if rec and recs[0] else '—'
    pf = f'{float(recs[1]):.0f}' if len(recs) > 1 else '—'
    rank = rec.get('rank') if rec else None
    return record, rank, pf

def _ord(n):
    try: n = int(n)
    except (TypeError, ValueError): return ''
    return 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

def render(run, plan=None):
    """-> Markdown text. `plan` is the dict data/plan.json holds (written by build())."""
    P = run.get('proj')
    L = [f"# Lineup Card — week {run['week']}", '',
         f"_{run.get('stamp') or C.stamp(C.now())}. Decisions first; detail folded below. A PROVISIONAL call waits for the market or a game-status answer._", '']
    # ---- Decide
    L += ['## Decide (next 36 hours)', '']
    n = 0
    for lg, R in run['leagues'].items():
        pl = ((plan or {}).get('leagues') or {}).get(lg, {}).get('planner') or {}
        for m in pl.get('moves') or []:
            kind = m.get('kind')
            if kind == 'add':
                what = f"**Add {m['add']}**" + (f" · drop {m['drop']}" if m.get('drop') else '') + (f" · bid ${m['bid']}" if m.get('bid') else '')
                if m.get('start'): what += f" · start him at {m.get('slot')}" + (f" over {m['sit']}" if m.get('sit') else '')
            elif kind == 'ir':
                what = f"**IR: {m.get('ir') or m.get('drop')}**"
            elif kind == 'lineup':
                what = f"**Start {m.get('start')} at {m.get('slot')}**" + (f" over {m['sit']}" if m.get('sit') else '')
            else:
                what = f"**{kind}: {m.get('add') or m.get('start') or ''}**"
            prov = ' _(provisional)_' if m.get('provisional') else ''
            when = f" — {m['when']}" if m.get('when') else ''
            L.append(f"- {lg}: {what}{prov}{when}"); n += 1
    if n == 0: L.append('- Nothing needs a decision right now.')
    L.append('')
    # ---- Outlook per league
    for lg, R in run['leagues'].items():
        st, lu, w = R['state'], R.get('lineup') or {}, R.get('win') or {}
        record, rank, pf = _rec(st)
        c = w.get('current') or {}
        L += [f"## {lg} — {st.me}", '']
        head = f"{record}" + (f", {rank}{_ord(rank)}" if rank else '') + f", PF {pf}"
        proj = lu.get('total_opt')
        if proj: head += f" · projected {proj:.0f}"
        if c.get('p_opp') is not None: head += f" · {c['p_opp']:.0%} to beat {w.get('opp') or 'the opponent'}"
        if c.get('p_med') is not None: head += f" · {c['p_med']:.0%} vs the league median"
        L.append(head)
        outs = [r['player'] for r in st.starters() if r['designation'] in UNUSABLE]
        qs = [r['player'] for r in st.starters() if r['designation'] in ('Q', 'D')]
        if outs: L.append(f"- **OUT in the lineup:** {', '.join(outs)}")
        if qs: L.append(f"- Q/D: {', '.join(qs)}")
        if P is not None:
            nxt = sorted({(P.kickoff(r['tm']), r['player']) for r in st.starters() if P.kickoff(r['tm']) and P.kickoff(r['tm']) > C.now()}, key=lambda x: x[0])
            if nxt:
                k0 = nxt[0][0]; names = [nm for k, nm in nxt if k == k0]
                L.append(f"- Next lock: {C.stamp(k0)} — " + (', '.join(names) if len(names) <= 3 else f'{len(names)} starters'))
        pl = ((plan or {}).get('leagues') or {}).get(lg, {}).get('planner') or {}
        la = pl.get('lineup_after') or {}
        if la:
            L += ['', '<details><summary>Lineup after the moves</summary>', '']
            for s, nm in la.items(): L.append(f"- {s}: {nm or '—'}")
            L += ['', '</details>']
        L.append('')
    # ---- folded detail: planner rejections (why not) and flags
    for lg, R in run['leagues'].items():
        pl = ((plan or {}).get('leagues') or {}).get(lg, {}).get('planner') or {}
        rej = pl.get('rejected') or []
        if rej:
            L += [f'<details><summary>{lg}: considered, not moves ({len(rej)})</summary>', '']
            for r in rej[:12]:
                L.append(f"- {r.get('name') or r.get('key')}: {str(r.get('reason') or '')[:160]}")
            L += ['', '</details>', '']
    flags = [x for lg, R in run['leagues'].items() for x in (R.get('flags') or [])]
    if flags:
        L += ['<details><summary>Flags</summary>', ''] + [f'- {x}' for x in flags[:20]] + ['', '</details>', '']
    L.append(f"_Engine stamp {run.get('stamp') or ''}. The HTML card is the full record; this page is the private, phone-readable twin._")
    return '\n'.join(L) + '\n'

def write(run, root, repo=None):
    """Write data/CARD.md under `root`; also <repo>/docs/CARD.md when the repo checkout is given."""
    plan = None
    try: plan = json.load(open(os.path.join(root, 'data', 'plan.json')))
    except (OSError, ValueError): plan = None
    md = render(run, plan)
    out = [os.path.join(root, 'data', 'CARD.md')]
    if repo and os.path.isdir(repo):
        os.makedirs(os.path.join(repo, 'docs'), exist_ok=True)
        out.append(os.path.join(repo, 'docs', 'CARD.md'))
    for p in out:
        open(p, 'w').write(md)
    return out
