"""THE CARD IS GENERATED. Every word on it comes from the run object, the ledger,
or the role registry. Nothing is typed in by hand -- that is how a card told
Caleb to swap in a defense that was already starting.

Layout (unchanged from the card he has been reading all season):
  clock strip -> actions -> two league panels (lineup + decisions) -> wire -> byes -> foot
"""
import html
from . import clock as C, lineup as LU, wire as W

def esc(x): return html.escape(str(x) if x is not None else '')

def fmt(x, d=2):
    return '???' if x is None else f'{x:.{d}f}'

CSS = """
:root{--bg:#F2F3EF;--surface:#FFFFFF;--surface-2:#E9EBE5;--line:#D5D8D0;--ink:#1A1E22;--muted:#5E6670;--faint:#8A929B;--accent:#1E3A5F;--accent-ink:#FFFFFF;--start:#1B7F4A;--start-bg:#DDF0E4;--warn:#B86A00;--warn-bg:#FBEBD0;--out:#B42318;--out-bg:#F9DEDB;--bench:#6E7681;--bench-bg:#E6E8EB;--bar:#1E3A5F;--bar-3:#C9A227}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111417;--surface:#1A1F25;--surface-2:#22282F;--line:#313943;--ink:#E8EAED;--muted:#A3ABB5;--faint:#727B86;--accent:#8FB3E0;--accent-ink:#0E1620;--start:#5CC48A;--start-bg:#183226;--warn:#F0A63A;--warn-bg:#3A2A10;--out:#F08A80;--out-bg:#3D1A17;--bench:#9AA3AE;--bench-bg:#2A3038;--bar:#8FB3E0;--bar-3:#E0BD4C}}
:root[data-theme="dark"]{--bg:#111417;--surface:#1A1F25;--surface-2:#22282F;--line:#313943;--ink:#E8EAED;--muted:#A3ABB5;--faint:#727B86;--accent:#8FB3E0;--accent-ink:#0E1620;--start:#5CC48A;--start-bg:#183226;--warn:#F0A63A;--warn-bg:#3A2A10;--out:#F08A80;--out-bg:#3D1A17;--bench:#9AA3AE;--bench-bg:#2A3038;--bar:#8FB3E0;--bar-3:#E0BD4C}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:15px;line-height:1.5;font-variant-numeric:tabular-nums}
.wrap{max-width:1180px;margin:0 auto;padding:18px 16px 44px}
h1,h2,h3{margin:0;text-wrap:balance}
h1{font-size:30px;font-weight:800;line-height:1.05}
h2{font-size:22px;font-weight:800}
h3{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}
.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:700}
.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:10px 24px;margin-bottom:14px}
.top .sub{color:var(--muted);margin-top:4px}
.clock{background:var(--out-bg);border-left:4px solid var(--out);border-radius:4px;padding:11px 15px;margin-bottom:16px}
.clock .hd{font-weight:800;font-size:17px;color:var(--out);text-transform:uppercase;letter-spacing:.03em}
.clock p{margin:4px 0 0}
.acts{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:10px;margin-bottom:20px}
.act{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--start);border-radius:5px;padding:11px 14px}
.act.hold{border-left-color:var(--accent)} .act.no{border-left-color:var(--out)} .act.wait{border-left-color:var(--bench);border-left-style:dashed} .act.prov{border-left-color:var(--warn)}
.act .lg{font-weight:800;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--start);display:block;margin-bottom:3px}
.act.hold .lg{color:var(--accent)} .act.no .lg{color:var(--out)} .act.wait .lg{color:var(--bench)} .act.prov .lg{color:var(--warn)}
.act .mv{font-weight:700;font-size:16px;margin-bottom:4px}
.act .why{font-size:13.5px;color:var(--muted);line-height:1.55}
.act .why b{color:var(--ink);font-weight:700}
.rev{display:inline-block;font-size:10px;font-weight:800;letter-spacing:.07em;padding:2px 6px;border-radius:3px;background:var(--warn-bg);color:var(--warn);margin-left:6px;vertical-align:1px}
.leagues{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:20px}
@media (max-width:900px){.leagues{grid-template-columns:1fr}}
.league{background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.lhead{background:var(--accent);color:var(--accent-ink);padding:13px 16px 11px;display:flex;justify-content:space-between;align-items:flex-end;gap:12px}
.lhead h2{color:inherit} .lhead .meta{font-size:12px;opacity:.85;margin-top:3px}
.lhead .tot{text-align:right} .lhead .tot .n{font-size:28px;font-weight:800;line-height:1} .lhead .tot .l{font-size:10px;text-transform:uppercase;letter-spacing:.1em;opacity:.85}
.roster{width:100%;border-collapse:collapse}
.roster th{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);font-weight:700;text-align:left;padding:8px 10px 4px;border-bottom:1px solid var(--line)}
.roster td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
.roster tr:last-child td{border-bottom:0}
.roster .slot{font-weight:800;font-size:13px;letter-spacing:.04em;color:var(--muted);width:64px;white-space:nowrap}
.roster .name{font-weight:700;white-space:nowrap} .roster .name small{display:block;font-weight:400;color:var(--muted);font-size:12px;white-space:normal}
.roster .pts{text-align:right;font-size:18px;font-weight:700;width:58px}
.roster .st{width:96px;text-align:right}
.roster tr.sec td{background:var(--surface-2);padding:5px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:700}
.roster tr.bn td{color:var(--muted)} .roster tr.bn .name{font-weight:500} .roster tr.bn .pts{color:var(--muted);font-weight:500}
.pill{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.05em;padding:2px 7px;border-radius:999px;white-space:nowrap}
.p-start{background:var(--start-bg);color:var(--start)} .p-lock{background:var(--accent);color:var(--accent-ink)} .p-q{background:var(--warn-bg);color:var(--warn)} .p-out{background:var(--out-bg);color:var(--out)} .p-bn{background:var(--bench-bg);color:var(--bench)} .p-prov{background:var(--surface-2);color:var(--muted);border:1px dashed var(--faint)}
.decis{padding:12px 14px 14px;border-top:1px solid var(--line)} .decis h3{margin-bottom:8px}
.dec{border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin-bottom:9px} .dec:last-child{margin-bottom:0}
.dec .q{display:flex;justify-content:space-between;gap:8px;align-items:baseline;margin-bottom:6px;flex-wrap:wrap}
.dec .q .sn{font-weight:800;font-size:14px} .dec .q .call{font-size:12px;color:var(--start);font-weight:700} .dec .q .call.prov{color:var(--muted)}
.dec .why{font-size:13px;color:var(--muted);margin-top:6px;line-height:1.55} .dec .why b{color:var(--ink);font-weight:700}
.gate{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:var(--faint);white-space:pre-wrap;margin-top:6px;line-height:1.45}
.gate .x{color:var(--out)} .gate .w{color:var(--warn)}
.wire{background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin-bottom:20px}
.wire .hd{padding:12px 14px 10px;border-bottom:1px solid var(--line)} .wire .hd .note{font-size:12.5px;color:var(--muted);margin-top:3px;max-width:96ch}
.wtab{width:100%;border-collapse:collapse;font-size:13.5px}
.wtab th{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--faint);text-align:left;font-weight:700;padding:8px 12px 4px}
.wtab td{padding:8px 12px;border-top:1px solid var(--line);vertical-align:top}
.wtab td:first-child{font-weight:700;white-space:nowrap;color:var(--ink)}
.wtab tr.bad td{color:var(--faint)} .wtab tr.bad td:first-child{color:var(--muted);text-decoration:line-through;text-decoration-color:var(--out)}
.wtab tr.dim td{color:var(--faint)} .wtab tr.dim td b{color:var(--muted)}
@media (max-width:820px){.wtab thead{display:none}.wtab tr{display:block;border-top:1px solid var(--line);padding:10px 12px}.wtab td{display:block;border:0;padding:2px 0}}
.foot{margin-top:18px;color:var(--faint);font-size:12px;line-height:1.6;max-width:84ch} .foot b{color:var(--muted)}

/* ---- phone-first top: masthead, decide, outlook (09-25, "too compacted") */
.mast{background:linear-gradient(135deg,var(--accent) 0%,color-mix(in srgb,var(--accent) 78%,#000) 100%);color:var(--accent-ink);border-radius:14px;padding:20px 20px 18px;margin-bottom:22px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px 24px}
.mast .eyebrow{color:inherit;opacity:.8}
.mast h1{font-family:"Barlow Condensed",ui-sans-serif,system-ui,sans-serif;font-size:44px;font-weight:700;letter-spacing:.01em;line-height:1;margin-top:4px}
.mast .stamp{font-size:13px;opacity:.85;margin-top:6px}
.mast .chips{display:flex;gap:8px;flex-wrap:wrap}
.mast .chip{background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:6px 12px;font-size:13px;font-weight:700;letter-spacing:.02em;white-space:nowrap}
.mast .chip small{font-weight:500;opacity:.8;margin-left:4px}
.sech{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:0 0 12px}
.sech h2{font-family:"Barlow Condensed",ui-sans-serif,system-ui,sans-serif;font-size:26px;font-weight:700;letter-spacing:.02em;text-transform:uppercase}
.sech .n{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.1em}
.decide{margin:0 0 26px}
.calm{background:var(--start-bg);border:1px solid color-mix(in srgb,var(--start) 30%,transparent);border-radius:12px;padding:18px 20px;font-size:17px;font-weight:700;color:var(--start);display:flex;align-items:center;gap:12px}
.calm::before{content:'';width:12px;height:12px;border-radius:50%;background:var(--start);flex:none}
.dcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.dcard{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px 14px;display:grid;grid-template-columns:1fr auto;gap:6px 16px;align-items:start;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.dcard .tag{grid-column:1/-1;display:flex;align-items:center;gap:8px;font-size:12px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
.dcard .tag .lgc{background:var(--accent);color:var(--accent-ink);border-radius:6px;padding:2px 8px;letter-spacing:.06em}
.dcard .tag .slot{color:var(--ink)}
.dcard .who{font-size:21px;font-weight:800;line-height:1.2;letter-spacing:-.01em}
.dcard .who small{display:block;font-size:14px;font-weight:500;color:var(--muted);margin-top:3px}
.dcard .delta{font-family:"Barlow Condensed",ui-sans-serif,system-ui,sans-serif;font-size:38px;font-weight:700;line-height:1;color:var(--start);text-align:right}
.dcard .delta small{display:block;font-family:ui-sans-serif,system-ui,sans-serif;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-top:4px}
.dcard .lock{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:6px;font-size:13px;color:var(--muted)}
.dcard .lock .pill{font-size:11px}
.dcard.act{display:block;border-left:5px solid var(--start);padding:16px 18px}
.dcard.act .lg{font-size:12px;letter-spacing:.09em;margin-bottom:6px}
.dcard.act .mv{font-size:19px;line-height:1.25;margin-bottom:6px}
.dcard.act .why{font-size:14px}
.dcard.act.wait{border-left-color:var(--warn);border-left-style:solid} .dcard.act.wait .lg{color:var(--warn)}
.dcard.act.no{border-left-color:var(--out)}
.outlook{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-bottom:26px}
.ol{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px 16px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.ol .hd{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:12px}
.ol .hd .team{font-family:"Barlow Condensed",ui-sans-serif,system-ui,sans-serif;font-size:26px;font-weight:700;letter-spacing:.01em;line-height:1}
.ol .hd .team small{font-family:ui-sans-serif,system-ui,sans-serif;font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);display:block;margin-bottom:4px}
.ol .hd .vs{font-size:12.5px;color:var(--muted);text-align:right;max-width:46%}
.ol .stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}
.ol .stat{background:var(--surface-2);border-radius:10px;padding:9px 10px 8px}
.ol .stat .v{font-family:"Barlow Condensed",ui-sans-serif,system-ui,sans-serif;font-size:26px;font-weight:700;line-height:1;letter-spacing:.01em}
.ol .stat .k{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-top:4px}
.ol .meter{margin-bottom:8px}
.ol .meter .lab{display:flex;justify-content:space-between;font-size:13px;margin-bottom:5px} .ol .meter .lab b{font-size:15px}
.ol .meter .bar{height:10px;border-radius:999px;background:var(--surface-2);overflow:hidden;position:relative}
.ol .meter .bar i{position:absolute;left:0;top:0;bottom:0;border-radius:999px;background:var(--accent)}
.ol .meter .bar u{position:absolute;left:50%;top:-2px;bottom:-2px;width:2px;background:var(--faint);opacity:.7}
.ol .meter.na .lab{color:var(--muted)}
.ol .row{font-size:14px;color:var(--muted);line-height:1.6;margin-top:8px} .ol .row b{color:var(--ink)}
.ol .row .pill{margin-right:2px;vertical-align:1px}
.ol .rowhd{font-size:11px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);margin-right:6px}
details.sec{background:var(--surface);border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden}
details.sec>summary{cursor:pointer;list-style:none;padding:16px 18px;font-weight:800;font-size:16px;display:flex;justify-content:space-between;align-items:center;gap:12px}
details.sec>summary::-webkit-details-marker{display:none}
details.sec>summary::after{content:'';width:10px;height:10px;border-right:2px solid var(--faint);border-bottom:2px solid var(--faint);transform:rotate(45deg);flex:none;margin:0 4px 4px 0;transition:transform .15s} details.sec[open]>summary::after{transform:rotate(-135deg);margin:4px 4px 0 0}
details.sec>summary small{font-weight:500;color:var(--muted);font-size:13px;display:block;margin-top:2px}
details.sec>summary .st{display:flex;flex-direction:column}
details.sec .wire,details.sec .league{border:0;border-radius:0;margin:0} details.sec .leagues{margin:0;gap:0}
details.sec .wire+.wire{border-top:1px solid var(--line)}
@media (prefers-reduced-motion:reduce){details.sec>summary::after{transition:none}}
@media (max-width:420px){.ol .stats{grid-template-columns:repeat(2,1fr)} .mast h1{font-size:38px}}
"""

def gate_html(g):
    lines = [f'{g.verdict}  {g.kind.upper()}: {esc(g.subject)}']
    for name, sev, msg in g.checks:
        m = {'PASS': 'ok', 'WARN': '!!', 'BLOCK': 'XX'}[sev]
        cls = {'PASS': '', 'WARN': ' class="w"', 'BLOCK': ' class="x"'}[sev]
        lines.append(f'<span{cls}>  {m} {name:<12} {esc(msg)}</span>')
    return '<div class="gate">' + '\n'.join(lines) + '</div>'

def pill(text, kind): return f'<span class="pill p-{kind}">{esc(text)}</span>'

def _totline(R):
    lu, act = R['lineup'], R.get('actuals') or {}
    done = [r for r in lu['current'].values() if r and r.get('final')]
    live = [r for r in lu['current'].values() if r and r.get('live')]
    if not done and not live: return 'proj · current lineup'
    a = sum(r['pts'] for r in done) + sum(r['actual'] for r in live)
    parts = [f'{a:.1f} scored ({len(done)} final' + (f', {len(live)} live' if live else '') + ')']
    return ' + '.join(parts + [f'{lu["total_cur"] - a:.1f} to come'])

def _winline(R):
    w = R.get('win')
    if not w: return ''
    c = w['current']
    parts = []
    if c['p_opp'] is not None: parts.append(f'{c["p_opp"]:.0%} to beat {esc(w["opp"])}')
    if c['p_med'] is not None: parts.append(f'{c["p_med"]:.0%} to beat the median')
    return f'<div class="l" style="margin-top:4px;text-transform:none;letter-spacing:0;font-size:11px">{" · ".join(parts)}</div>' if parts else ''

def render(run):
    week, stamp = run['week'], run['stamp']
    B, H = run['leagues']['BSB'], run['leagues']['HH']
    WNd = run['windows']
    out = []
    out.append(f'<title>BSB &amp; Heritage House Lineup Card</title>\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&display=swap">\n<style>{CSS}</style>\n<div class="wrap">')
    out.append(f'<div class="top"><div><div class="eyebrow">NFL Week {week} · 2026</div><h1>Lineup Card</h1>'
               f'<div class="sub">{esc(stamp)}</div></div></div>')
    out.append('@@ASSEMBLE@@')

    # ---- inputs strip: what this card was computed FROM, and how old each
    # input is. Caleb 09-17: "every time I refresh this, we are checking for a
    # new player, right?" — only if the inputs moved. This says whether they did.
    import os as _os
    from lib import usage as _U
    D_ = '/home/claude/bsb2/data/'
    def _age(pth):
        return (C.now().timestamp() - _os.path.getmtime(pth)) / 3600 if _os.path.exists(pth) else None
    def _fmt_age(h):
        if h is None: return 'missing'
        return f'{h:.0f}h' if h < 48 else f'{h/24:.0f}d'
    up = _U.pulled_at(week - 1)
    inputs = [('rosters', f"BSB {B['state'].age_h:.0f}h · HH {H['state'].age_h:.0f}h"),
              ('Kalshi ladders', _fmt_age(_age(D_ + 'kalshi.csv')) + f' · {len(run["proj"].ready)}/32 teams priced'),
              ('game lines', (f'Kalshi spreads/totals {len(run["proj"].kal_games)}/{max(len(run["proj"].games), 1)} games · ' + _fmt_age(_age(D_ + 'kalshi.csv'))) if getattr(run['proj'], 'kal_games', None) else _fmt_age(_age(D_ + 'espn_games.csv'))),
              (f'week-{week-1} usage', (f'{(C.now() - up).total_seconds()/3600:.0f}h' if up else 'missing')),
              ('trending adds', _fmt_age(_age(D_ + 'trending_adds.csv'))),
              ('BSB claim log', _fmt_age(_age(D_ + 'bsb_transactions.csv'))),
              ('actuals', ' · '.join(f'{lg} {sum(1 for a in (R.get("actuals") or {}).values() if a["final"])} final, {sum(1 for a in (R.get("actuals") or {}).values() if not a["final"])} live' + (f' ({(C.now() - R["actuals_at"]).total_seconds()/3600:.0f}h)' if R.get('actuals_at') else '') for lg, R in (('BSB', B), ('HH', H))))]
    out.append('<div class="wire" style="margin-bottom:12px"><div class="hd" style="border:0;padding:9px 14px"><h3>Inputs this card was computed from</h3>'
               '<div class="note">' + ' · '.join(f'<b>{esc(k)}</b> {esc(v)}' for k, v in inputs) +
               '<br>This page does not recompute when you reload it. It changes when the inputs above are re-pulled and the engine is re-run — say "are we good?" and that is what happens. '
               'The pool, the breakout scan and the FAB bands cannot show a new player until the rosters, the usage pull or the market on this strip are newer than the last run.</div></div></div>')

    # ---- clock strip
    wd = C.bsb_waiver_deadline(); hrs = (wd - C.now()).total_seconds() / 3600
    claims = [c for c in B['calls'] if c['kind'] == 'swap' and c['ledger']['status'] == 'proposed']
    if 0 < hrs < 48:
        out.append(f'<div class="clock"><div class="hd">BSB waivers process {esc(C.stamp(wd))} — {hrs:.0f} hours from now</div>'
                   f'<p>{len(claims)} claim{"s" if len(claims) != 1 else ""} below. Acquisitions are uncapped in BSB. Heritage House has a 7-per-week cap.</p></div>')

    # ---- actions
    out.append('<div class="acts">')
    for i, c in enumerate(claims, 1):
        b = c['item']; a, d = b['add'], b['drop']
        reg = B['wire'].verified.get(a['key'], {}); dreg = B['wire'].drop_ok.get(d['key'], {})
        v = 'no' if 'BLOCK' in (c['gate_add'].verdict, c['gate_drop'].verdict) else ('prov' if 'WARN' in (c['gate_add'].verdict, c['gate_drop'].verdict) else '')
        rev = '<span class="rev">reverses a prior hold</span>' if dreg.get('reverses') else ''
        out.append(f'<div class="act {v}"><span class="lg">BSB claim {i}{" — BLOCKED" if v=="no" else ""}</span>'
                   f'<div class="mv">Drop {esc(d["player"])} → Add {esc(a["name"])} <span style="color:var(--muted);font-weight:400">{esc(a["fam"])}, {esc(a["tm"])}</span>{rev}</div>'
                   f'<div class="why"><b>Why drop:</b> {esc(dreg.get("why") or ("designation " + d["designation"]))}<br>'
                   f'<b>Why add:</b> {esc(reg.get("usage_wk1",""))} {esc(reg.get("why",""))}'
                   + (f'<br><b>Caveat:</b> {esc(reg["caveat"])}' if reg.get('caveat') else '')
                   + f'<br><span style="color:var(--faint)">{b["gain"]:+.1f} on the {esc(b["basis"])} · gate {c["gate_add"].verdict}/{c["gate_drop"].verdict}</span></div></div>')
    for lg, R in (('BSB', B), ('HH', H)):
        for k, hreg in R['wire'].hold.items():
            row = R['state'].row_of(k)
            if not row: continue
            out.append(f'<div class="act hold"><span class="lg">{lg} — hold</span><div class="mv">{esc(row["player"])} stays</div>'
                       f'<div class="why">{esc(hreg["call"])}<br><span style="color:var(--faint)">{esc(hreg.get("why","")[:260])}</span></div></div>')
    # (do-not-add names are enforced silently by gate G11; Caleb 09-17: no
    #  updates about things he should not do)
    for lg, R in (('BSB', B), ('HH', H)):
        for c in R.get('stream_calls', []):
            if c['ledger']['status'] not in ('proposed',): continue
            b, a, d = c['board'], c['add'], c['drop']
            out.append(f'<div class="act"><span class="lg">{lg} — week {week+1} stream, free now</span>'
                       f'<div class="mv">Add {esc(a["name"])} <span style="color:var(--muted);font-weight:400">{esc(c["fam"])}, {esc(a["tm"])}</span>'
                       + (f' → drop {esc(d["player"])}' if d else '') + '</div>'
                       f'<div class="why">Week {week+1} {"opponent" if c["fam"]=="DEF" else "own-team"} implied total: <b>{esc(a["tm"])} {b["best_fa"]["val"]:.1f}</b> vs your best {esc(b["best_mine"]["name"])} {b["best_mine"]["val"]:.1f} — a <b>{b["edge"]:.1f}-point</b> edge on a posted line. '
                       + (f'Dropping {esc(d["player"])} also clears the second-{esc(W._fam(d["pos"]))} spot. ' if d else '')
                       + f'Waivers have run, so the pool is first-come; this is worth taking today rather than Tuesday.<br><span style="color:var(--faint)">gate {c["gate_add"].verdict}' + (f'/{c["gate_drop"].verdict}' if c['gate_drop'] else '') + '</span></div></div>')
        # breakout adds get a tile at the top: this is the one call on the card
        # that is about next month, not this week
        for x in (R.get('breakout') or {}).get('rows', []):
            m = x['move']
            if m['verb'] not in ('ADD', 'ADD-DEAD'): continue
            g = x.get('gate')
            warns = [msg for gg, st, msg in (g.checks if g else []) if st == 'WARN']
            out.append(f'<div class="act{" prov" if warns else ""}"><span class="lg">{lg} — breakout add, tier {esc(x["tier"])}{" — check first" if warns else ""}</span>'
                       f'<div class="mv">Add {esc(x["name"])} <small style="font-weight:400;color:var(--muted)">{esc(x["pos"])} {esc(x["tm"])}</small> · drop {esc(m["drop"])}</div>'
                       f'<div class="why"><b>When:</b> {esc(m["when"])}.<br><b>Why:</b> {esc(m["why"])}'
                       + (''.join(f'<br><b>Check:</b> {esc(w_)}' for w_ in warns) if warns else '')
                       + f'<br><span style="color:var(--faint)">{esc(x["usage"])} · {esc(x["market"])}</span></div></div>')
        dropping = {c['item']['drop']['player'] for c in R['calls'] if c['kind'] == 'swap'}
        for f in R['flags']:
            if 'holds a roster spot' in f and 'HOLD' in f: continue
            if any(f.startswith(p) for p in dropping): continue     # already a claim above
            if 'NEXT MAN UP' in f:
                head, rest = f.split(' — NEXT MAN UP ', 1)
                out.append(f'<div class="act"><span class="lg">{lg} — next man up</span><div class="mv">{esc(head)}</div>'
                           f'<div class="why"><b>Add {esc(rest.split(" is a free agent")[0])}</b>{esc(rest[len(rest.split(" is a free agent")[0]):])}</div></div>')
                continue
            out.append(f'<div class="act wait"><span class="lg">{lg} — structure</span><div class="mv">{esc(f.split(" — ")[0])}</div>'
                       f'<div class="why">{esc(f.split(" — ",1)[1] if " — " in f else "")}</div></div>')
    for lg, R in (('BSB', B), ('HH', H)):
        starts = [c for c in R['calls'] if c['kind'] == 'start' and c['ledger']['status'] == 'proposed']
        firm = [c for c in starts if not c['change']['provisional']]
        if firm:
            for c in firm:
                ch = c['change']
                out.append(f'<div class="act"><span class="lg">{lg} lineup — decided</span><div class="mv">{esc(ch["slot"])}: {esc(ch["start"]["player"])} over {esc(ch["sit"]["player"] if ch["sit"] else "empty")}</div>'
                           f'<div class="why">{ch["gain"]:+.2f} · locks {esc(C.stamp(ch["kick"]))}</div></div>')
        elif starts:
            out.append(f'<div class="act prov"><span class="lg">{lg} lineup — provisional</span><div class="mv">{len(starts)} swap{"s" if len(starts)>1 else ""} inside the noise band or before the market posts</div>'
                       f'<div class="why">' + '; '.join(f'{esc(c["change"]["start"]["player"])} over {esc(c["change"]["sit"]["player"] if c["change"]["sit"] else "empty")} ({c["change"]["gain"]:+.2f})' for c in starts)
                       + ('. ' + esc('; '.join(c['change']['reason'] for c in starts if c['change'].get('reason'))) if any(c['change'].get('reason') for c in starts) else '')
                       + '. Not a move until the market posts or the status clears.</div></div>')
        else:
            out.append(f'<div class="act hold"><span class="lg">{lg} lineup</span><div class="mv">Already optimal — no change</div><div class="why">Nobody on the bench outscores a starter. Exact assignment over all {len(R["state"].cfg.slots)} slots.</div></div>')
        # win-probability view: the lineup that wins the week's results, not the highest mean
        w = R.get('win')
        if w:
            c, b = w['current'], w['best']
            def pct(x): return f'{x:.0%}' if x is not None else 'n/a'
            head = ' · '.join(p for p in ((f'{pct(c["p_opp"])} to beat {esc(w["opp"])}' if c['p_opp'] is not None else ''),
                                          (f'{pct(c["p_med"])} to beat the league median' if c['p_med'] is not None else '')) if p)
            if not head:
                why = next((n for n in w.get('notes', []) if 'not computed' in n), 'not computed')
                head = 'Not computed — ' + esc(why)
            if b['label'] != 'current' and b['gain'] >= 0.03:
                out.append(f'<div class="act"><span class="lg">{lg} lineup — win probability</span><div class="mv">{esc(b["label"])}</div>'
                           f'<div class="why">Current lineup: {head}. This swap adds <b>{b["gain"]:+.1%}</b> combined win probability '
                           f'(→ {pct(b["p_opp"])} / {pct(b["p_med"])}). Sampled {w["n"]:,} times from the posted Kalshi ladders; the mean-optimal lineup is not the win-optimal one when the results are head-to-head and vs the median.</div></div>')
            else:
                out.append(f'<div class="act hold"><span class="lg">{lg} lineup — win probability</span><div class="mv">{head}</div>'
                           f'<div class="why">Current lineup {c["mean"]:.1f} ± {c["sd"]:.1f}. No bench swap moves the combined win probability by 3 points or more; {w["priced"]} players sampled from Kalshi ladders, {w["assumed"]} from assumed spreads. Same-game correlation is not modelled.</div></div>')
    out.append('</div>')

    # ---- league panels
    out.append('<div class="leagues">')
    for lg, R in (('BSB', B), ('HH', H)):
        st, lu = R['state'], R['lineup']
        cfg = st.cfg
        out.append(f'<section class="league"><div class="lhead"><div><h2>{esc(st.me)}</h2><div class="meta">{esc(cfg.key)} · state {esc(st.pulled[:16])} ({st.age_h:.0f}h old)</div></div>'
                   f'<div class="tot"><div class="n">{lu["total_cur"]:.1f}</div><div class="l">' + _totline(R) + '</div>' + _winline(R) + '</div></div>')
        out.append('<table class="roster"><thead><tr><th>Slot</th><th>Player</th><th style="text-align:right">Pts</th><th></th></tr></thead><tbody>')
        opt_keys = {r['key'] for r in lu['optimal'].values() if r}
        for s in cfg.slots:
            r = lu['current'].get(s)
            if not r: out.append(f'<tr><td class="slot">{esc(s)}</td><td class="name">—</td><td class="pts">—</td><td class="st">{pill("EMPTY","out")}</td></tr>'); continue
            ph = r.get('phase', ''); kick = r.get('kick')
            if r.get('final'):
                a = R['actuals'][r['key']]
                out.append(f'<tr><td class="slot">{esc(s)}</td><td class="name">{esc(r["player"])}<small>{esc(a["status"])} · actual, from Yahoo</small></td>'
                           f'<td class="pts">{fmt(r["pts"])}</td><td class="st">{pill("FINAL", "lock")}</td></tr>')
                continue
            if r.get('live'):
                a = R['actuals'][r['key']]
                out.append(f'<tr><td class="slot">{esc(s)}</td><td class="name">{esc(r["player"])}<small>{esc(a["status"])} · {a["pts"]:.2f} so far + {r["proj_pts"] or 0:.2f} × {1 - a["frac"]:.0%} of the game left</small></td>'
                           f'<td class="pts">{fmt(r["pts"])}</td><td class="st">{pill("LIVE", "q")}</td></tr>')
                continue
            small = esc(C.stamp(kick)) if kick else ''
            if r['line'].get('prov'):
                k0 = next(iter(r['line']['prov'].values()))
                small += (' · ' if small else '') + esc(k0[:70])
            tag = pill('LOCK ' + (C.stamp(kick).split(',')[0] if kick else ''), 'lock') if ph in ('alert', 'decide') else \
                  pill('UNKNOWN', 'q') if r['pts'] is None else \
                  pill(r['designation'], 'q') if r['designation'] in ('Q', 'D') else pill('START', 'start')
            out.append(f'<tr><td class="slot">{esc(s)}</td><td class="name">{esc(r["player"])}<small>{small}</small></td><td class="pts">{fmt(r["pts"])}</td><td class="st">{tag}</td></tr>')
        out.append('<tr class="sec"><td colspan="4">Bench — judged on upside, not mean</td></tr>')
        for r in sorted([x for x in lu['rows'] if x['slot'] == 'BN'], key=lambda x: -(x['pts'] or -1)):
            reg = R['wire'].drop_ok.get(r['key']) or R['wire'].hold.get(r['key'])
            if r.get('final') or r.get('live'):
                out.append(f'<tr class="bn"><td class="slot">{esc(W._fam(r["pos"]))}</td><td class="name">{esc(r["player"])}<small>{esc(R["actuals"][r["key"]]["status"])} · {"actual" if r.get("final") else "%.2f so far" % r["actual"]}</small></td><td class="pts">{fmt(r["pts"])}</td><td class="st">{pill("FINAL" if r.get("final") else "LIVE", "lock" if r.get("final") else "q")}</td></tr>')
                continue
            small = (f'boom {r["boom"]*100:.0f}%' if r.get('boom') is not None else '')
            if reg: small += (' · ' if small else '') + esc(reg['call'][:90])
            tag = pill(r['designation'], 'out') if r['designation'] in S_UNUSABLE else \
                  pill('OPTIMAL', 'prov') if r['key'] in opt_keys else pill('BENCH', 'bn')
            out.append(f'<tr class="bn"><td class="slot">{esc(W._fam(r["pos"]))}</td><td class="name">{esc(r["player"])}<small>{small}</small></td><td class="pts">{fmt(r["pts"])}</td><td class="st">{tag}</td></tr>')
        for r in st.ir():
            out.append(f'<tr class="bn"><td class="slot">IR</td><td class="name">{esc(r["player"])}</td><td class="pts">—</td><td class="st">{pill(r["designation"],"out")}</td></tr>')
        out.append('</tbody></table>')
        # decisions
        out.append('<div class="decis"><h3>Decisions, with the gate output verbatim</h3>')
        starts = [c for c in R['calls'] if c['kind'] == 'start']
        if not starts:
            out.append('<div class="dec"><div class="q"><span class="sn">Lineup</span><span class="call">already optimal</span></div>'
                       f'<div class="why">{len(lu["perms"])} slot permutation(s) of the same starters suppressed as net zero.</div></div>')
        for c in starts:
            ch, g, e = c['change'], c['gate'], c['ledger']
            tag = 'already set' if e['status'] == 'already_set' else ('provisional' if ch['provisional'] else g.verdict.lower())
            out.append(f'<div class="dec"><div class="q"><span class="sn">{esc(ch["slot"])}</span><span class="call {"prov" if tag=="provisional" else ""}">{esc(ch["start"]["player"])} over {esc(ch["sit"]["player"] if ch["sit"] else "empty")} · {ch["gain"]:+.2f} · {esc(tag)}</span></div>')
            if ch['provisional']:
                why = []
                if ch['gain'] < LU.NOISE: why.append(f'inside the {LU.NOISE}-point noise band')
                if not ch['start']['ready'] or (ch['sit'] and not ch['sit'].get('ready', True)): why.append('no player market posted yet for ' + ('both games' if not ch['start']['ready'] and ch['sit'] and not ch['sit'].get('ready', True) else (ch['start']['player'] if not ch['start']['ready'] else ch['sit']['player']) + "'s game"))
                if ch.get('reason'): why.append(ch['reason'])
                out.append(f'<div class="why">Not a move: {esc("; ".join(why))}. Locks {esc(C.stamp(ch["kick"]))}.</div>')
            out.append(gate_html(g) + '</div>')
        for u in lu['unknown']:
            out.append(f'<div class="dec"><div class="q"><span class="sn">{esc(u["player"])}</span><span class="call prov">unknown, not zero</span></div><div class="why">No source covers him this week. A silent 0.00 is how a real contributor gets benched on an absence instead of on evidence.</div></div>')
        out.append('</div></section>')
    out.append('</div>')

    # (the full wire inventory used to render here. Caleb 09-17: the actions are
    #  at the top; an inventory of players not being acted on is noise.)

    # (trade market panel removed 09-17 — Caleb: trades do not happen in these
    #  leagues; lib/trade.py stays available via `ff.py` but is not run.)

    # ---- what the market learned between pulls
    stm = run.get('steam') or {}
    if stm:
        from lib import steam as _STM
        if stm.get('note'):
            head = esc(stm['note'])
        else:
            head = (f"Every rostered player's Kalshi ladder, this pull against the week's first pull ({stm['baseline'].astimezone(C.ET):%a %-I:%M %p} ET). "
                    f"A move past {_STM.THRESH:.0%} is the market pricing news — a practice report, a role change, a quiet injury — before the projection or the Yahoo tag catches up. "
                    + (f"Withdrawn markets are checked against the previous pull ({stm['previous'].astimezone(C.ET):%a %-I:%M %p} ET): Kalshi pulls a player's markets when he is ruled out." if stm.get('previous') else ''))
        out.append('<div class="wire"><div class="hd"><h3>Market moves — what Kalshi learned since Wednesday</h3><div class="note">' + head + '</div></div>')
        if stm.get('gone'):
            for g in stm['gone']:
                who = ', '.join(f'{lg} {o}' for lg, o, *_ in g['owners'])
                out.append(f'<div class="act no" style="margin:10px 12px 4px;border-radius:5px"><span class="lg">markets withdrawn</span><div class="mv">{esc(g["player"])} <small style="font-weight:400;color:var(--muted)">{esc(g["tm"])}</small></div>'
                           f'<div class="why">Had {esc(", ".join(g["series"]))} in the previous pull, none now, game not started — treat as OUT until Yahoo says otherwise. Rostered by {esc(who)}.</div></div>')
        moves = stm.get('moves') or []
        if moves:
            out.append('<table class="wtab"><thead><tr><th>Move</th><th>Player</th><th>Stat</th><th>Was → now</th><th>Rostered by</th></tr></thead><tbody>')
            for m in moves[:16]:
                who = ', '.join(f'{lg} {o}' for lg, o, *_ in m['owners'])
                mine = (' <b>← yours (' + ', '.join(f'{lg} {sl}' for lg, sl in m['mine']) + ')</b>') if m['mine'] else ''
                cls = ' style="color:var(--start);font-weight:700"' if m['pct'] > 0 else ' style="color:var(--out);font-weight:700"'
                out.append(f'<tr><td{cls}>{m["pct"]:+.0%}</td><td>{esc(m["key"].title())}{mine}</td><td>{esc(m["stat"])}</td><td>{m["before"]:.1f} → {m["after"]:.1f}</td><td>{esc(who)}</td></tr>')
            out.append('</tbody></table>')
        elif not stm.get('note'):
            out.append('<div class="hd" style="border:0"><div class="note">No rostered player\'s ladder has moved past the threshold since the first pull of the week.</div></div>')
        out.append('</div>')
    # ---- next man up
    nus = {lg: R.get('nextup') for lg, R in (('BSB', B), ('HH', H)) if R.get('nextup')}
    if nus:
        uw = next((n['usage_week'] for n in nus.values() if n.get('usage_week')), None)
        out.append('<div class="wire"><div class="hd"><h3>Next man up — who inherits the role, and whether he is on the wire</h3><div class="note">'
                   f'Depth charts from the snap and touch shares in the last two usage pulls (week {uw} newest, weighted double). For each of your starters and your opponent\'s whose game has not kicked off: the next man at his position on his NFL team, his share, and where he is in this league. '
                   'When a starter is ruled out — Yahoo tag or Kalshi withdrawing his markets on the Sunday 11:30 pull — and the backup is a free agent, it becomes a Decide tile: in BSB a never-rostered free agent is yours until his game kicks off; in HH free agents are immediate.</div></div>')
        for lg, n in nus.items():
            if n.get('note'):
                out.append(f'<div class="hd" style="border:0"><div class="note"><b>{lg}</b> — {esc(n["note"])}</div></div>'); continue
            out.append(f'<table class="wtab"><thead><tr><th>{lg}</th><th>Starter</th><th>Status</th><th>Next man up</th></tr></thead><tbody>')
            for r in n['rows']:
                b = ' · '.join(f'<b>{esc(x["name"])}</b> {x["share"]:.0%} <small>{esc(x["where_txt"])}' + (f', {x["pts"]:.1f}' if x["pts"] is not None else '') + '</small>' for x in r['backups']) or '<small>no backup in the usage data</small>'
                stc = ' style="color:var(--out);font-weight:700"' if r['out'] else (' style="color:var(--warn);font-weight:700"' if r['status'] == 'Q' else '')
                out.append(f'<tr{" class=dim" if r["side"] != "you" else ""}><td>{esc(r["side"])}</td><td>{esc(r["player"])} <small>{esc(r["slot"])}</small></td><td{stc}>{esc(r["status"])}</td><td>{b}</td></tr>')
            out.append('</tbody></table>')
        out.append('</div>')
    fab = run.get('fab') or {}
    if fab.get('n'):
        bands = fab['bands']
        out.append('<div class="wire"><div class="hd"><h3>BSB FAB — what a claim costs in this league</h3>'
                   f'<div class="note">Every winning bid on the league log so far ({fab["n"]} claims, {len(fab["runs"])} waiver runs): '
                   + ', '.join(f'${b}' for b in fab['bids']) + f'. Median winning bid ${fab["med"]:.0f}; the one whale is {esc(fab["whale_mgr"])} at ${fab["whale"]}. '
                   f'<b>Bands the card uses:</b> Tier B ${bands["B"]["bid"]} ({esc(bands["B"]["why"])}); Tier A ${bands["A"]["bid"]} ({esc(bands["A"]["why"])}); contested ${bands["contested"]["bid"]} ({esc(bands["contested"]["why"])}). '
                   'Budgets: ' + ', '.join(f'{esc(k)} ${fab["remaining"][k]} left' for k, v in sorted(fab['spent'].items(), key=lambda kv: -kv[1])) + '. Every manager not listed has spent $0.</div></div>')
        # ---- the field: how each manager behaves, and the bid to beat by position
        rv = B.get('rivals')
        if rv:
            from lib import rivals as _RV
            bids = {fam: _RV.bid_for(rv, fam, 'A', fab) for fam in ('QB', 'RB', 'WR', 'TE', 'DEF', 'K')}
            out.append('<div class="hd" style="border-top:1px solid var(--line)"><div class="note"><b>The bid to beat for a Tier-A claim, by position</b> — each manager priced at his usual winning bid (one claim counts at 60% unless he is thin at the position); the field is everyone thin there plus the habitual bidders: '
                       + ' · '.join(f'{fam} <b>${bd["bid"]}</b>' for fam, bd in bids.items()) + '. Tier-B (unpriced) claims take the $' + str(fab['bands']['B']['bid']) + ' floor: nobody else\'s model is looking.</div></div>')
            out.append('<table class="wtab"><thead><tr><th>Manager</th><th>Adds</th><th>FAB left</th><th>Usual bid</th><th>Last 7 days</th><th>Thin at</th></tr></thead><tbody>')
            for o, pr in sorted(rv['profiles'].items(), key=lambda kv: (-(kv[1]['spent'] or 0), -kv[1]['adds'])):
                usual = (f'${pr["med_bid"]:.0f} (max ${pr["max_bid"]}, {len(pr["bids"])} claims)' if pr['bids'] else 'never bid')
                thin = ', '.join(f'{f} <small>({why})</small>' for f, (w_, m_, why) in pr['need'].items()) or '—'
                out.append(f'<tr{" style=font-weight:700" if pr["me"] else ""}><td>{esc(o)}{" ← you" if pr["me"] else ""}</td><td>{pr["adds"]} <small>({pr["claims"]} claims, {pr["fa"]} FA)</small></td><td>${pr["remaining"]}</td><td>{usual}</td><td>{pr["recent"]}</td><td>{thin}</td></tr>')
            out.append('</tbody></table>')
            nostream = sum(1 for pr in rv['profiles'].values() if not pr['streams_def'])
            out.append(f'<div class="hd" style="border:0"><div class="note">{nostream} of {len(rv["profiles"])} managers have not streamed a defense this season — the DEF wire stays deep, which is part of why the second DEF is worth holding rather than chasing.</div></div>')
        out.append('</div>')
    rvh = H.get('rivals')
    if rvh:
        out.append('<div class="wire"><div class="hd"><h3>HH — who is active on the wire</h3><div class="note">Free agents are immediate in HH and each manager has 7 acquisitions a week (the reset day is not documented by Yahoo, so this counts the last 7 days). A manager at or near the cap cannot compete for a Sunday-morning pickup.</div></div>')
        out.append('<table class="wtab"><thead><tr><th>Manager</th><th>Adds (season)</th><th>Last 7 days</th><th>Thin at</th></tr></thead><tbody>')
        for o, pr in sorted(rvh['profiles'].items(), key=lambda kv: -kv[1]['recent']):
            thin = ', '.join(f'{f} <small>({why})</small>' for f, (w_, m_, why) in pr['need'].items()) or '—'
            out.append(f'<tr{" style=font-weight:700" if pr["me"] else ""}><td>{esc(o)}{" ← you" if pr["me"] else ""}</td><td>{pr["adds"]}</td><td>{pr["recent"]}{" of 7" if pr["recent"] >= 5 else ""}</td><td>{thin}</td></tr>')
        out.append('</tbody></table></div>')

    # ---- next-week streaming boards
    out.append(f'<div class="wire"><div class="hd"><h3>Week {week+1} streaming — DEF and K priced off posted lines</h3>'
               '<div class="note">DEF ranked by the OPPONENT\'s implied total (lower is better); K by his OWN team\'s implied total (higher is better). * marks a player you already roster. In BSB the unclaimed pool is free and first-come the moment waivers run, so a next-week edge is worth taking now.</div></div>')
    out.append('<table class="wtab"><thead><tr><th>League</th><th>DEF — opponent implied</th><th>K — own implied</th></tr></thead><tbody>')
    for lg, R in (('BSB', B), ('HH', H)):
        sb = R.get('stream') or {}
        cells = []
        for fam in ('DEF', 'K'):
            b = sb.get(fam)
            if not b: cells.append('—'); continue
            rows = ' · '.join(f'{esc(x["name"][:18])}{"*" if x["mine"] else ""} <small>{x["val"]:.1f}</small>' for x in b['rows'][:6] if x['val'] is not None)
            verdict = ''
            if b['best_mine'] and b['best_fa'] and b['edge'] is not None:
                verdict = (f'<br><b>{esc(b["best_fa"]["name"])} beats your best by {b["edge"]:.1f}</b>' if b['edge'] > 0
                           else f'<br>yours ({esc(b["best_mine"]["name"])}) is best by {abs(b["edge"]):.1f} — hold')
            if b['byes']: verdict += f'<br><span style="color:var(--warn)">on bye: {esc(", ".join(b["byes"]))}</span>'
            if b.get('note'): verdict += f'<br><span style="color:var(--muted)">{esc(b["note"])}</span>'
            cells.append(rows + verdict)
        out.append(f'<tr><td>{lg}</td><td>{cells[0]}</td><td>{cells[1]}</td></tr>')
    out.append('</tbody></table></div>')

    # ---- breakout scan
    out.append('<div class="wire"><div class="hd"><h3>Breakouts — the undrafted players who change seasons</h3>'
               '<div class="note"><b>What this tracks.</b> Every year 3-4 players nobody drafted win leagues, and they share one trait: their <b>role</b> shows up in the snap and target counts one to two weeks before their <b>price</b> shows up in projections and waiver bids. So this panel ignores fantasy points and watches four facts about every unrostered player: last week\'s share of his team\'s snaps, targets and air yards (or RB touches) from the verified usage pull; whether next week\'s Kalshi or DraftKings line is above or below the Sleeper projection; where the preseason rankings had him; and how many Sleeper managers added him in the last 48 hours (the crowd).<br>'
               '<b>The tiers.</b> <b>A</b> — usage says starter and the market already agrees: this is the one. <b>B</b> — usage says starter, the market has not caught up: the cheap window, but one game is one game. <b>C</b> — the crowd is chasing a box score the snaps do not back: let them. <b>W</b> — rising, or the market prices him under the projection: watch.<br>'
               '<b>When to move.</b> The Action column is the call. <b>ADD</b> names the player to drop and the mechanics (HH: free agents are immediate, 1 of 7 weekly adds; BSB: free agent until his game locks, then a Tuesday-night waiver claim). <b>WAIT</b> means re-check after the next usage pull, Monday night or Tuesday, before BSB waivers run Wednesday. <b>NONE</b> means no move whatever the numbers say, with the reason. Nothing here is ever proposed over a registry hold or a handcuff.</div></div>')
    for lg, R in (('BSB', B), ('HH', H)):
        bk = R.get('breakout') or {}
        rows = bk.get('rows', [])
        acts = [x for x in rows if x['move']['verb'] in ('ADD', 'ADD-DEAD')]
        cls = 'act' if acts else 'act wait'
        out.append(f'<div class="{cls}" style="margin:10px 12px 4px;border-radius:5px"><span class="lg">{lg} — {"act" if acts else "no move"}</span><div class="mv">{esc(bk.get("summary", "no scan"))}</div>'
                   + (f'<div class="why">Usage: week {bk["week"]} pull, {bk["pulled"]:%a %m-%d %-I:%M %p} ET.' + (' <b>' + esc(next((n for n in bk.get('notes', []) if 'older than it should be' in n), '')) + '</b>' if any('older than it should be' in n for n in bk.get('notes', [])) else ' Next pull: the data pump, Tuesday morning.') + '</div>' if bk.get('pulled') else '') + '</div>')
        show = [x for x in rows if x['tier'] == 'A'] + [x for x in rows if x['tier'] == 'B'][:6] + [x for x in rows if x['tier'] == 'C'][:3]
        if not show:
            out.append(f'<div class="note" style="padding:6px 14px 12px;color:var(--faint)">{esc("; ".join(bk.get("notes", ["no scan"])))}</div>'); continue
        out.append('<table class="wtab"><thead><tr><th>Tier</th><th>Player · last week\'s usage</th><th>Market next week</th><th>Crowd</th><th>Action</th></tr></thead><tbody>')
        for x in show:
            m = x['move']
            pk = {'ADD': 'start', 'ADD-DEAD': 'start', 'WAIT': 'q', 'NONE': 'bn', 'BLOCKED': 'out'}[m['verb']]
            share = (f'{x["snap"]:.0%} snaps · {x["touch"]:.0%} of RB touches' if x['pos'] == 'RB'
                     else f'{x["snap"]:.0%} snaps' if x['pos'] == 'QB'
                     else f'{x["snap"]:.0%} snaps · {x["tgt"]:.0%} targets · {x["air"]:.0%} air yds')
            pre = f'preseason {x["pos"]}{x["prank"]}' if x['prank'] else 'not in the preseason blend'
            crowd = f'{(x["crowd"] or 0)/1e6:.1f}M adds' if (x['crowd'] or 0) >= 1e6 else f'{(x["crowd"] or 0)//1000}k adds' if x['crowd'] else '—'
            rcls = ' class="dim"' if m['verb'] in ('NONE', 'BLOCKED') else ''
            out.append(f'<tr{rcls}><td><b>{x["tier"]}</b></td>'
                       f'<td><b>{esc(x["name"])}</b> <small>{esc(x["pos"])} {esc(x["tm"])}</small><br><small>{share} · {x["pts_wk1"]:.1f} pts wk{bk["week"]} · {pre}</small></td>'
                       f'<td><small>{esc(x["market"])}</small></td><td><small>{crowd}</small></td>'
                       f'<td>{pill(m["verb"].replace("-DEAD", " over dead spot"), pk)}' + (f' <b>drop {esc(m["drop"])}</b>' if m['drop'] else '')
                       + f'<br><small>{esc(m["when"])}</small><br><small style="color:var(--muted)">{esc(m["why"])}</small></td></tr>')
        out.append('</tbody></table>')
    out.append('</div>')

    # ---- playoff picture
    pos_ = {lg: R.get('playoff') for lg, R in (('BSB', B), ('HH', H)) if R.get('playoff')}
    if pos_:
        out.append('<div class="wire"><div class="hd"><h3>Playoff picture — the race, and what this week is worth</h3><div class="note">'
                   'Every roster\'s strength is its optimal lineup on individual per-week values (BSB: season blend ÷ 17; HH: this week\'s projections), re-solved for each future week with that week\'s byes zeroed. '
                   'The rest of the regular season (through week 14) is simulated 4,000 times: this week\'s known opponent, random pairings after (the league schedule is not on file), BSB\'s vs-median result each week, standings by wins then points-for. '
                   'BSB divisions are not modelled. Leverage is the gap between making the playoffs after a win this week and after a loss; +5/wk is what a roster upgrade of five points a week buys.</div></div>')
        for lg, po in pos_.items():
            lev = (f' · this game: win <b>{po["p_win"]:.0%}</b> / lose <b>{po["p_loss"]:.0%}</b> (<b>{po["leverage"]:+.0%}</b>)' if po.get('leverage') is not None else '')
            out.append(f'<div class="hd" style="border:0"><div class="note"><b>{lg}</b> — playoffs <b>{po["mine"]:.0%}</b>{lev} · +5 pts/week → <b>{po["p_plus5"]:.0%}</b> · top-{po["top_k"]} seed <b>{po["mine_top"]:.0%}</b>'
                       + (f' (win {po["top_win"]:.0%} / lose {po["top_loss"]:.0%})' if po.get('top_leverage') is not None else '') + '</div></div>')
            out.append(f'<table class="wtab"><thead><tr><th>Playoffs</th><th>Top-{po["top_k"]} seed</th><th>Team</th><th>Wins now</th><th>Points for</th><th>Strength / wk</th></tr></thead><tbody>')
            for r in po['race']:
                me_ = r['owner'] == (B if lg == 'BSB' else H)['state'].me
                out.append(f'<tr{" style=font-weight:700" if me_ else ""}><td>{r["p"]:.0%}</td><td>{r["p_top"]:.0%}</td><td>{esc(r["owner"])}{" ← you" if me_ else ""}</td><td>{r["wins"]:.0f}</td><td>{r["pf"]:.0f}</td><td>{r["strength"]:.1f}</td></tr>')
            out.append('</tbody></table>')
        out.append('</div>')
    # ---- December + byes
    out.append('<div class="wire"><div class="hd"><h3>December environment and byes — from posted look-ahead lines</h3>'
               '<div class="note">Implied team totals for weeks 15–17 (fantasy playoffs, both leagues). IDP is judged on the OPPONENT\'s total — a tackle needs an opposing play. Look-ahead lines are real prices at low limits: use the ordering, never a one-point gap. Roster spots go to upside; bye holes get streamed one to two weeks out.</div></div>')
    out.append('<table class="wtab"><thead><tr><th>League</th><th>Playoff assets (top 8)</th><th>Thin Decembers (bottom 8)</th><th>Byes ahead — starters out</th></tr></thead><tbody>')
    for lg, R in (('BSB', B), ('HH', H)):
        dec = sorted(R['dec'], key=lambda x: x[2])
        top = [f'{esc(r["player"])} <small>{esc(r["tm"])} {e:.1f} #{rk}</small>' for r, e, rk, n, idp in dec if rk <= 8]
        bot = [f'{esc(r["player"])} <small>{esc(r["tm"])} {e:.1f} #{rk}</small>' for r, e, rk, n, idp in dec if rk >= n - 7]
        byes = [f'wk {w_}: {esc(", ".join(who))}' for w_, who in R['byes'].items() if who]
        out.append(f'<tr><td>{lg}</td><td>{"<br>".join(top) or "—"}</td><td>{"<br>".join(bot) or "—"}</td><td>{"<br>".join(byes) or "—"}</td></tr>')
    out.append('</tbody></table></div>')

    # ---- foot
    out.append(f'<div class="foot"><b>How this page is made.</b> `ff.py run` loads the newest roster snapshot for each league (with its pull time), builds one stat line per player market-first (Kalshi ladders → Vegas lines → DraftKings props → Sleeper), scores that line under each league\'s own rules, solves each lineup by exact assignment against the slots that are actually filled, derives the free-agent pool by subtraction, audits it for phantoms, ranks it usage-first, and runs every resulting call through a 12-check gate and the decision ledger. The regression suite — every failure that has ever had to be corrected in this thread — must pass before any of that runs. This card is rendered from that output and nothing else.'
               f'<br><br><b>State:</b> BSB {esc(B["state"].pulled[:16])} · HH {esc(H["state"].pulled[:16])}. <b>Lines:</b> {len(WNd.weeks)} weeks posted through week {max(WNd.weeks)}. <b>Markets ready:</b> {esc(", ".join(sorted(run["proj"].ready)) or "none")}.</div>')
    out.append('</div>')
    return _assemble(out, run)

def _assemble(out, run):
    """Phone-first order (Caleb 09-25: 'less detailed, highlight my decision
    points and outlooks'): header -> DECIDE (only what needs a hand) -> OUTLOOK
    (one tile per league) -> everything else collapsed, in the order it was."""
    import re as _re
    i0 = out.index('@@ASSEMBLE@@')
    head, body = out[:i0], out[i0 + 1:]
    # ---- pull the pieces out of the body
    inputs = [x for x in body if x.startswith('<div class="wire" style="margin-bottom:12px"><div class="hd" style="border:0;padding:9px 14px"><h3>Inputs')]
    clock = [x for x in body if x.startswith('<div class="clock">')]
    ia = body.index('<div class="acts">'); ib = body.index('</div>', ia)
    tiles = body[ia + 1:ib]
    il = body.index('<div class="leagues">')
    last_sec = max(i for i, x in enumerate(body) if '</section>' in x)
    ilc = next(i for i in range(last_sec, len(body)) if body[i] == '</div>')
    leagues = body[il:ilc + 1]
    rest = body[ilc + 1:]
    foot_i = next((i for i, x in enumerate(rest) if x.startswith('<div class="foot">')), len(rest))
    wires_flat, foot = rest[:foot_i], rest[foot_i:]
    wires = []
    for x in wires_flat:
        if x.startswith('<div class="wire"') and 'Inputs this card' not in x: wires.append([x])
        elif wires and 'Inputs this card' not in x: wires[-1].append(x)
    def title(w):
        m = _re.search(r'<h3>(.*?)</h3>', w[0]); return _re.sub(r'<[^>]+>', '', m.group(1)) if m else 'More'
    # ---- classify the action tiles
    decide, watch, holds = [], [], []
    for t in tiles:
        lab = _re.search(r'<span class="lg">(.*?)</span>', t); lab = lab.group(1) if lab else ''
        if 'win probability' in lab: continue                      # goes into the outlook tile
        if t.startswith('<div class="act hold">'): holds.append(t)
        elif t.startswith('<div class="act wait">'):
            # a Q contingency is a decision inside 36h of its lock (Caleb: lineup
            # warnings one day out, not Monday); before that it is outlook
            m = _re.search(r'decide before ([A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [ap]m)', t)
            soon = False
            if m:
                try:
                    import datetime as _dt
                    k = _dt.datetime.strptime(m.group(1) + f' {C.now().year}', '%a %b %d, %I:%M %p %Y').replace(tzinfo=C.ET)
                    soon = (k - C.now()).total_seconds() <= 36 * 3600
                except ValueError: soon = True
            (decide if soon or 'WITHDREW' in t or 'market cut' in t else holds).append(t)
        elif t.startswith('<div class="act prov">'): watch.append(t)
        else: decide.append(t)
    # ---- decision cards: a decided swap becomes a card whose focal point is
    # the number; everything else that needs a hand keeps its tile, larger
    def dcard(t):
        lab = _re.search(r'<span class="lg">(.*?)</span>', t); lab = lab.group(1) if lab else ''
        if '— decided' in lab:
            lg = lab.split(' ')[0]
            mv = _re.search(r'<div class="mv">(.*?)</div>', t).group(1)
            why = _re.search(r'<div class="why">(.*?)</div>', t).group(1)
            slot, rest = mv.split(': ', 1)
            start, sit = rest.split(' over ', 1)
            gain = _re.match(r'([+-]?\d+\.\d+)', why); gain = float(gain.group(1)) if gain else None
            lock = _re.search(r'locks (.*)$', why); lock = lock.group(1) if lock else ''
            return (f'<div class="dcard"><div class="tag"><span class="lgc">{lg}</span><span class="slot">{slot}</span><span>lineup</span></div>'
                    f'<div class="who">Start {start}<small>over {sit}</small></div>'
                    f'<div class="delta">{gain:+.1f}<small>points</small></div>'
                    f'<div class="lock">{pill("locks " + lock.replace(" ET",""), "lock")}<span>set it in Yahoo before then</span></div></div>')
        return t.replace('<div class="act', '<div class="dcard act', 1)
    decide = [dcard(t) for t in decide]
    # ---- outlook: one stat card per league
    ol = ['<div class="outlook">']
    for lg, R in run['leagues'].items():
        st, lu, w = R['state'], R['lineup'], R.get('win') or {}
        rec = (st.records or {}).get(st.me, {})
        c = w.get('current') or {}
        P = run['proj']
        nxt = sorted({(P.kickoff(r['tm']), r['player']) for r in st.starters() if P.kickoff(r['tm']) and P.kickoff(r['tm']) > C.now()}, key=lambda x: x[0])
        if nxt:
            k0 = nxt[0][0]; names = [n for k, n in nxt if k == k0]
            lock = f'<b>{esc(C.stamp(k0).replace(" ET",""))}</b> — ' + (esc(', '.join(names)) if len(names) <= 3 else f'{len(names)} starters')
        else: lock = 'all starters locked'
        qs = [r['player'] for r in st.starters() if r['designation'] in ('Q', 'D')]
        outs = [r['player'] for r in st.starters() if r['designation'] in S_UNUSABLE]
        watching = []
        if outs: watching.append(pill('OUT', 'out') + ' in the lineup: <b>' + esc(', '.join(outs)) + '</b>')
        if qs: watching.append(pill('Q', 'q') + ' ' + esc(', '.join(qs)))
        prov = [x for x in watch if f'>{lg} lineup' in x]
        if prov: watching.append(esc(_re.sub(r'<[^>]+>', ' ', _re.search(r'<div class="why">(.*?)</div>', prov[0]).group(1)).split('. Not a move')[0].strip()))
        recs = (rec.get('record') or '').split(' PF ')
        record = esc(recs[0]) if rec else '—'
        rank = (esc(str(rec.get('rank', ''))) + _ord(rec.get('rank', ''))) if rec and rec.get('rank') else '—'
        pf = f'{float(recs[1]):.0f}' if len(recs) > 1 else '—'
        meters = []
        if c.get('p_opp') is not None:
            meters.append(f'<div class="meter"><div class="lab"><span>to beat {esc(w.get("opp") or "?")}</span><b>{c["p_opp"]:.0%}</b></div><div class="bar"><i style="width:{c["p_opp"]*100:.0f}%"></i><u></u></div></div>')
        elif w:
            meters.append(f'<div class="meter na"><div class="lab"><span>to beat {esc(w.get("opp") or "?")}</span><b>n/a</b></div></div>')
        if c.get('p_med') is not None:
            meters.append(f'<div class="meter"><div class="lab"><span>to beat the league median</span><b>{c["p_med"]:.0%}</b></div><div class="bar"><i style="width:{c["p_med"]*100:.0f}%"></i><u></u></div></div>')
        po = R.get('playoff')
        if po:
            trivial = po['mine'] >= 0.995 and po.get('p_loss', 1) >= 0.99
            if trivial:   # 8 of 10 qualify in HH: the seed is the number that moves
                meters.append(f'<div class="meter"><div class="lab"><span>top-{po["top_k"]} seed</span><b>{po["mine_top"]:.0%}</b></div><div class="bar"><i style="width:{po["mine_top"]*100:.0f}%"></i><u></u></div></div>')
                if po.get('top_leverage') is not None:
                    meters.append(f'<div class="row"><span class="rowhd">This game</span>win → <b>{po["top_win"]:.0%}</b> · lose → <b>{po["top_loss"]:.0%}</b> for the seed; the playoffs themselves are {po["mine"]:.0%} either way</div>')
            else:
                meters.append(f'<div class="meter"><div class="lab"><span>to make the playoffs</span><b>{po["mine"]:.0%}</b></div><div class="bar"><i style="width:{po["mine"]*100:.0f}%"></i><u></u></div></div>')
                if po.get('leverage') is not None:
                    meters.append(f'<div class="row"><span class="rowhd">This game</span>win → <b>{po["p_win"]:.0%}</b> · lose → <b>{po["p_loss"]:.0%}</b> to make the playoffs ({po["leverage"]:+.0%} riding on it)</div>')
        ol.append(f'<div class="ol"><div class="hd"><div class="team"><small>{esc(lg)}</small>{esc(st.me)}</div><div class="vs">week {run["week"]} vs<br><b>{esc(w.get("opp") or "?")}</b></div></div>'
                  f'<div class="stats"><div class="stat"><div class="v">{record}</div><div class="k">record</div></div>'
                  f'<div class="stat"><div class="v">{rank}</div><div class="k">place</div></div>'
                  f'<div class="stat"><div class="v">{pf}</div><div class="k">points for</div></div>'
                  f'<div class="stat"><div class="v">{lu["total_cur"]:.0f}</div><div class="k">projected</div></div></div>'
                  + ''.join(meters)
                  + f'<div class="row"><span class="rowhd">Next lock</span>{lock}</div>'
                  + (f'<div class="row"><span class="rowhd">Watching</span>{" · ".join(watching)}</div>' if watching else '') + '</div>')
    ol.append('</div>')
    # ---- masthead replaces the plain header
    stamp = esc(run['stamp'])
    chips = ''.join(f'<span class="chip">{esc(R["state"].me)}<small>{esc(lg)}</small></span>' for lg, R in run['leagues'].items())
    mast = (f'<div class="mast"><div><div class="eyebrow">NFL Week {run["week"]} · 2026</div><h1>Lineup Card</h1>'
            f'<div class="stamp">{stamp}</div></div><div class="chips">{chips}</div></div>')
    # ---- assemble
    A = [x for x in head if not x.startswith('<div class="top">')]
    A.append(mast)
    A += clock
    A.append(f'<div class="decide"><div class="sech"><h2>Decide</h2><span class="n">{len(decide)} open</span></div>')
    if decide: A.append('<div class="dcards">'); A += decide; A.append('</div>')
    else:
        # say what was checked, not just that it came up empty (Caleb 09-27)
        nxt = []
        for lg, R in run['leagues'].items():
            ks = sorted({run['proj'].kickoff(r['tm']) for r in R['state'].starters() if run['proj'].kickoff(r['tm']) and run['proj'].kickoff(r['tm']) > C.now()})
            if ks: nxt.append(f'{lg} {C.stamp(ks[0]).replace(" ET", "")}')
        A.append('<div class="calm"><div>Nothing needs a decision right now — both lineups are set as the engine would set them, and no add or drop clears the gate in either league.'
                 + (f'<div style="font-size:14px;font-weight:500;margin-top:4px;opacity:.85">Next lock: {esc(" · ".join(nxt))}. The card re-checks on every pull.</div>' if nxt else '') + '</div></div>')
    A.append('</div>')
    A.append('<div class="decide"><div class="sech"><h2>Outlook</h2><span class="n">both leagues</span></div>'); A += ol; A.append('</div>')
    def sec(title_, items, sub=''):
        return [f'<details class="sec"><summary><span class="st">{esc(title_)}' + (f'<small>{esc(sub)}</small>' if sub else '') + '</span></summary>'] + items + ['</details>']
    A += sec('Lineups and gate output', leagues, 'both rosters, every call with its checks')
    if watch or holds: A += sec('Provisional calls and holds', ['<div class="acts" style="padding:10px 12px">'] + watch + holds + ['</div>'], f'{len(watch)} provisional · {len(holds)} holds')
    for w in wires: A += sec(title(w), w)
    cal = run.get('calib')
    calh = []
    if cal and cal.get('rows'):
        calh.append('<div class="wire" style="margin:0"><div class="hd"><h3>Calibration — each source\'s pregame error vs Yahoo actuals</h3><div class="note">'
                    + esc(cal['note']) + ' Weeks scored: ' + esc(', '.join(f'{lg} wk{w}' for lg, w in cal['weeks'])) + f' · {cal["n_total"]} player-weeks.</div></div>')
        calh.append('<table class="wtab"><thead><tr><th>League</th><th>Pos</th><th>Source</th><th>n</th><th>Mean abs error</th><th>Bias</th></tr></thead><tbody>')
        for r in cal['rows']:
            calh.append(f'<tr{" style=font-weight:700" if r["pos"] == "ALL" else ""}><td>{r["league"]}</td><td>{r["pos"]}</td><td>{r["source"]}</td><td>{r["n"]}</td><td>{r["mae"]:.2f}</td><td>{r["bias"]:+.2f}</td></tr>')
        calh.append('</tbody></table></div>')
    A += sec('Inputs and how this page is made', inputs + calh + foot)
    A.append('</div>')
    return '\n'.join(A)

def _ord(n):
    try: n = int(n)
    except (TypeError, ValueError): return ''
    return 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

S_UNUSABLE = {'IR','IR-R','O','NA','PUP','PUP-R','SUSP','CEL'}
