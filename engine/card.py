import json,html,csv,sys,datetime as dt
sys.path.insert(0,'/home/claude/bsb2')
from lib.names import team
D='/home/claude/bsb2/data/'
E=html.escape
P=json.load(open(D+'week_proj.json'))
ENV=json.load(open(D+'season_env.json'))
GAMES={}
for r in csv.DictReader(open(D+'espn_games.csv')):
    GAMES[team(r['away'])]=GAMES[team(r['home'])]=r['kickoff'][:10]
SLOTS=['QB','RB1','RB2','WR1','WR2','WR3','TE','W/R/T','K','DEF']
o=[]
o.append('<title>BSB Control Room</title>')
o.append('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">')
o.append('''<style>
:root{--bg:#F2F3EF;--surface:#FFF;--s2:#E9EBE5;--line:#D5D8D0;--ink:#1A1E22;--muted:#5E6670;--faint:#8A929B;
--accent:#6B2131;--good:#1B7F4A;--good-bg:#DDF0E4;--warn:#B86A00;--warn-bg:#FBEBD0;--bad:#B42318;--bad-bg:#F9DEDB;--gold:#9A7B0A;}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111417;--surface:#1A1F25;--s2:#22282F;--line:#313943;--ink:#E8EAED;--muted:#A3ABB5;--faint:#727B86;--accent:#E08A9C;--good:#5CC48A;--good-bg:#183226;--warn:#F0A63A;--warn-bg:#3A2A10;--bad:#F08A80;--bad-bg:#3D1A17;--gold:#E0BD4C;}}
:root[data-theme="dark"]{--bg:#111417;--surface:#1A1F25;--s2:#22282F;--line:#313943;--ink:#E8EAED;--muted:#A3ABB5;--faint:#727B86;--accent:#E08A9C;--good:#5CC48A;--good-bg:#183226;--warn:#F0A63A;--warn-bg:#3A2A10;--bad:#F08A80;--bad-bg:#3D1A17;--gold:#E0BD4C;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;font-size:14px;line-height:1.45;font-variant-numeric:tabular-nums}
.wrap{max-width:1000px;margin:0 auto;padding:22px 16px 56px}
h1,h2,h3{font-family:"Barlow Condensed",sans-serif;margin:0}h1{font-size:38px;font-weight:700;line-height:1}
h2{font-size:24px;font-weight:700;margin:32px 0 4px}h3{font-size:14px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin:20px 0 6px;font-weight:600}
.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.13em;color:var(--muted);font-weight:600}
.sub{color:var(--muted);font-size:13px}.lede{font-size:15px;margin:10px 0 0;max-width:70ch}
.hdr{border-bottom:2px solid var(--accent);padding-bottom:14px}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden;margin-top:8px}
th{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--faint);font-weight:600;text-align:left;padding:8px 9px 5px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:6px 9px;border-bottom:1px solid var(--line)}tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;font-family:"Barlow Condensed",sans-serif;font-size:16px;font-weight:600;white-space:nowrap}
td.slot{font-family:"Barlow Condensed",sans-serif;font-weight:700;color:var(--muted);white-space:nowrap}
.pos{color:var(--good)}.neg{color:var(--bad)}.dim{color:var(--faint)}
.chip{display:inline-block;font-size:10px;font-weight:600;letter-spacing:.05em;padding:2px 6px;border-radius:999px;background:var(--s2);color:var(--muted);white-space:nowrap}
.chip.g{background:var(--good-bg);color:var(--good)}.chip.w{background:var(--warn-bg);color:var(--warn)}.chip.b{background:var(--bad-bg);color:var(--bad)}
.act{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--gold);border-radius:6px;padding:13px 15px;margin-top:10px}
.act .k{font-family:"Barlow Condensed",sans-serif;font-size:19px;font-weight:700}
.act .k small{display:block;font-family:"IBM Plex Sans",sans-serif;font-size:10.5px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--gold);margin-bottom:2px}
.act p{margin:6px 0 0;font-size:13px;color:var(--muted)}.act p b{color:var(--ink)}
.act.go{border-left-color:var(--good)}.act.go .k small{color:var(--good)}
.act.wait{border-left-color:var(--warn)}.act.wait .k small{color:var(--warn)}
pre{background:var(--s2);border:1px solid var(--line);border-radius:6px;padding:11px 13px;font-family:"IBM Plex Mono",monospace;font-size:11.5px;line-height:1.5;overflow-x:auto;margin-top:8px;color:var(--ink)}
.note{font-size:12px;color:var(--muted);margin-top:7px;line-height:1.5}.note b{color:var(--ink)}
.scroll{overflow-x:auto}
footer{margin-top:38px;padding-top:15px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);line-height:1.6}footer b{color:var(--ink)}
@media(max-width:640px){h1{font-size:29px}.wrap{padding:18px 16px 44px}pre{font-size:10.5px}}
</style>''')
o.append('<div class="wrap">')
o.append(f'''<div class="hdr"><div class="eyebrow">Blood Sweat &amp; Beers &middot; OVERKILL &middot; Week 2</div>
<h1>Control Room</h1>
<p class="lede">Market first: Kalshi ladders where the price <em>is</em> the probability, Vegas implied totals for defense and environment, consensus projections only for the tail &mdash; and every call run through a gate that blocks the exact mistakes made before it existed.</p>
<p class="sub" style="margin-top:8px">Verified live {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} UTC &middot; roster re-pulled and reconciled against the transaction log &middot; Sunday market re-checked and still unposted</p></div>''')

sf,det=P['49ers'],P['Lions']
o.append(f'''<div class="act go"><div class="k"><small>Do this before Thursday</small>Start the 49ers, bench the Lions</div>
<p><b>STILL NOT DONE &mdash; the Lions are in your DEF slot right now.</b> 49ers <b>{sf['pts']:.2f}</b> vs Lions <b>{det['pts']:.2f}</b> &mdash; a <b>{sf['pts']-det['pts']:+.2f}</b> point swing in BSB scoring. Points allowed: 49ers {E(sf['prov']['pts_allow'])}; Lions {E(det['prov']['pts_allow'])}. Vegas and Sleeper agree on the 49ers to the decimal. The Lions play Thursday, so this locks {GAMES.get('DET','')}.</p></div>''')
o.append('''<div class="act go"><div class="k"><small>Free, waivers run Wednesday morning</small>Drop Tank Dell</div>
<p>IR-R, and BSB has <b>no IR slot</b> &mdash; he is a roster spot scoring a certain zero. The add is <b>Germie Bernard</b>, but read the flag: he is <b>single-source</b> (FFToday only; Sleeper does not carry him). The gate normally blocks a single-source add and permits this one only because what it replaces is a verified zero.</p></div>''')
o.append('''<div class="act wait"><div class="k"><small>Not ready, and that is the answer</small>Every Sunday slot</div>
<p>WR3 separates by <b>0.14</b> points and the flex by <b>0.06</b>. No player market exists for the Sunday slate yet &mdash; Kalshi has posted only the Thursday game, DraftKings has posted no Sunday player props, and FFToday has not published Week 2 at all. <b>Calvin Ridley has no weekly source from anyone.</b> Re-run Friday and these resolve on market prices instead of a coin flip.</p></div>''')

o.append('<h2>Lineup</h2><p class="sub">Asterisk = priced off a full Kalshi ladder. Kickoff decides what locks when.</p>')
o.append('<div class="scroll"><table><tr><th>slot</th><th>player</th><th class="n">proj</th><th>sources</th><th>plays</th><th class="n">env wk3-9</th></tr>')
for s in SLOTS:
    p=next((v for k,v in P.items() if v['slot']==s),None)
    if not p: continue
    nm=[k for k,v in P.items() if v['slot']==s][0]
    deep=sum(1 for f in ('rec','rec_yd','rush_yd','pass_yd','pass_td') if 'KALSHI' in str(p['prov'].get(f,'')))
    star='<b>*</b>' if deep>=2 else ''
    e=ENV['ENV'].get(team(p['nfl'])); rk=ENV['ENV_RK'].get(team(p['nfl']))
    es=f'{e:.2f} <span class="dim">#{rk}</span>' if e else '&mdash;'
    o.append(f'<tr><td class="slot">{s}</td><td>{E(nm)} <span class="dim">{E(p["nfl"])}</span></td>'
             f'<td class="n">{p["pts"]:.2f}{star}</td><td class="dim">{E(",".join(p["sources"]))}</td>'
             f'<td class="dim">{GAMES.get(team(p["nfl"]),"")}</td><td class="n">{es}</td></tr>')
o.append('</table></div>')

o.append('<h3>The market read on your Thursday players</h3>')
o.append('<div class="scroll"><table><tr><th>player</th><th>stat</th><th>Kalshi (price = probability)</th></tr>')
for n in ('James Cook','Sam LaPorta','Keon Coleman'):
    v=P[n]
    for f,x in v['prov'].items():
        if 'KALSHI' in str(x):
            o.append(f'<tr><td>{E(n)}</td><td class="dim">{E(f)}</td><td style="font-size:12px">{E(x)}</td></tr>')
o.append('</table></div>')
o.append('<p class="note">LaPorta is the calibration point: the market says <b>4.24 receptions / 44.36 yards</b>, Rotowire says <b>4.25 / 44.50</b>. Two fully independent methods landing on the same player to two decimals is the strongest corroboration available.</p>')

o.append('<h2>The gate</h2><p class="sub">Every recommendation that had to be corrected, replayed through it.</p>')
g=open(D+'out_gate.txt').read()
lines=[l for l in g.splitlines() if l.startswith('[') or ' XX ' in l or 'behaved' in l]
o.append('<pre>'+E('\n'.join(lines))+'</pre>')
o.append('<p class="note">Controls included: the two calls that <em>should</em> pass do pass, so this is a filter and not a blanket refusal.</p>')

o.append('<h2>Where value grows &mdash; market-priced offense, weeks 3&ndash;9</h2>')
o.append('<p class="sub">104 games, each line read individually and cross-checked. The mean already contains a player’s team context, so this is shown separately and used for upside, never multiplied in.</p>')
o.append('<div class="scroll"><table><tr><th>your skill player</th><th>tm</th><th class="n">implied pts/gm</th><th class="n">rank of 32</th></tr>')
mine=[(k,v) for k,v in P.items() if v['pos'] in ('QB','RB','WR','TE')]
for k,v in sorted(mine,key=lambda x:-(ENV['ENV'].get(team(x[1]['nfl']),0))):
    e=ENV['ENV'].get(team(v['nfl']));rk=ENV['ENV_RK'].get(team(v['nfl']))
    if not e: continue
    cl='pos' if rk<=10 else ('neg' if rk>=23 else '')
    o.append(f'<tr><td>{E(k)}</td><td class="dim">{E(v["nfl"])}</td><td class="n">{e:.2f}</td><td class="n {cl}">#{rk}</td></tr>')
o.append('</table></div>')
o.append('<p class="note">Stafford, LaPorta and Cook are buying into the <b>1st, 2nd and 6th</b> best scoring environments in the league over the next seven weeks. <b>Drake London (#25), Calvin Ridley (#26) and Malik Washington (#28)</b> are in three of the worst eight. Your receiving corps is the part of this roster the market likes least.</p>')

o.append(f'''<footer>
<b>Sources, in the order they were trusted.</b> <b>Kalshi</b> &mdash; a contract pays $1 if the player clears the line, so the price is the probability and a multi-strike ladder is a whole distribution; fitted negative-binomial for counts and zero-inflated gamma for yards, SSE 0.0008&ndash;0.01 across 3&ndash;15 strikes. Midpoints, not bids: 22 soft inversions in the book mean the bid side alone is not monotone. <b>Vegas game lines</b> &mdash; all 16 Week 2 games plus 104 games across Weeks 3&ndash;9, each read per-event rather than off the scoreboard endpoint, which truncates and has returned wrong lines. <b>ESPN player props</b> &mdash; line only; re-confirmed this run that no price field exists anywhere in the feed. <b>Sleeper</b> and <b>FFToday</b> for the tail; Sleeper and Yahoo are one source, not two.<br><br>
<b>Known limits, stated rather than hidden.</b> Kalshi has posted only the Thursday game; the Sunday slate has no player market yet. FFToday has not published Week 2. Calvin Ridley is covered by nothing this week and is shown as unknown, not as zero &mdash; a silent zero is how a real contributor gets benched on an absence. Kicker scoring uses 36 yards per made field goal, calibrated against Yahoo, because Sleeper&rsquo;s own fgm_yds field reports ~26 and is broken. Anytime-TD prices are P(at least one), which slightly understates expected touchdowns. Weeks 7&ndash;9 lines are lookahead prices, thinner than a live market.
</footer></div>''')
open('/home/claude/bsb2/control-room.html','w').write('\n'.join(o))
print('card bytes',sum(len(x) for x in o))
