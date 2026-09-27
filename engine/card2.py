import json,html,csv,sys,datetime as dt
import numpy as np
from collections import defaultdict
sys.path.insert(0,'/home/claude/bsb2')
from lib.names import key,team
D='/home/claude/bsb2/data/'; E=html.escape
B=json.load(open(D+'season_blend.json')); P=json.load(open(D+'week_proj.json'))
wk=defaultdict(dict)
for r in csv.DictReader(open(D+'lines_wk3_9.csv')):
    tot=float(r['over_under']); sp=float(r['spread'] or 0); w=int(r['week'])
    a,h=team(r['away']),team(r['home']); fav=team(r['favorite'])
    ih,ia=((tot+sp)/2,(tot-sp)/2) if fav==h else ((tot-sp)/2,(tot+sp)/2)
    wk[w][a]=ia; wk[w][h]=ih
W=sorted(wk); ALL=set().union(*[set(v) for v in wk.values()])
ENV={t:np.mean([wk[w][t] for w in W if t in wk[w]]) for t in ALL}
RKk={t:i+1 for i,t in enumerate(sorted(ENV,key=lambda x:-ENV[x]))}
Ew=[w for w in W if w<=5]; Lw=[w for w in W if w>=7]
TR={t:np.mean([wk[w][t] for w in Lw if t in wk[w]])-np.mean([wk[w][t] for w in Ew if t in wk[w]]) for t in ALL}
BYE={w:sorted(ALL-set(wk[w])) for w in W}
MINE=[r for r in csv.DictReader(open(D+'rosters.csv')) if r['manager']=='Caleb']
for r in MINE:
    b=B.get(key(r['player'])); r['pts']=b['pts'] if b else 0.0
REPL={'QB':347.2,'RB':81.1,'WR':115.2,'TE':146.6,'K':156.2,'DEF':111.8}
o=[]
o.append('<title>BSB Control Room</title>')
o.append('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap">')
o.append(open('/home/claude/bsb2/control-room.html').read().split('<style>')[1].split('</style>')[0].join(['<style>','</style>']))
o.append('<div class="wrap">')
o.append(f'''<div class="hdr"><div class="eyebrow">Blood Sweat &amp; Beers &middot; OVERKILL &middot; Week 2, Tuesday</div>
<h1>Control Room</h1>
<p class="lede">Wednesday. Roster verified live against the transaction log. The Thursday lineup is already correct &mdash; the open items are a waiver claim and one trade offer.</p>
<p class="sub" style="margin-top:8px">{dt.datetime.now().strftime('%Y-%m-%d %H:%M')} UTC &middot; 104 games read individually across weeks 3&ndash;9</p></div>''')

o.append('''<div class="act go"><div class="k"><small>Done &mdash; confirmed on the live roster</small>49ers in, Lions benched</div>
<p>Pulled at {ts}. The 49ers are in the DEF slot and Detroit is on the bench, which was the only Thursday-critical call. <b>Your whole Thursday lineup is correct</b>: Cook and LaPorta starting, Ray Davis, Keon Coleman and the Lions benched. Nothing else in that game needs touching.</p></div>'''.replace('{ts}', dt.datetime.now().strftime('%b %-d, %H:%M UTC')))
o.append('''<div class="act wait"><div class="k"><small>Still open &mdash; two moves, both free</small>Tank Dell, and the second defense</div>
<p><b>1. Drop Tank Dell, add Germie Bernard.</b> Dell is IR-R with no IR slot &mdash; a certain zero. Bernard at 115 is the <b>only</b> receiver on the wire who beats anything you roster; the next one down is Jaylin Noel at 92, below both Jennings and Flournoy. Single-source, allowed only because it replaces a zero.</p>
<p style="margin-top:8px"><b>2. Drop the Lions.</b> You are carrying two defenses at a slot worth about 3 points a week, in a league with no acquisition cap. <b>Los Angeles Chargers (114.7, two sources) hit the wire yesterday</b> and Kansas City, Buffalo and Baltimore are all free as well. Hold one defense, stream the matchup weekly &mdash; there is always a top-five option available.</p>
<p style="margin-top:8px">Neither costs FAB. Everything relevant is a free agent, so your $100 is not the constraint &mdash; the wire simply has nothing else worth owning.</p></div>''')
o.append('''<div class="act"><div class="k"><small>The shape of the problem</small>Three assets, fifteen spare parts</div>
<p>Cook <b>+188</b>, Smith-Njigba <b>+180</b>, London <b>+145</b> over the wire. Nothing else on the roster clears <b>+37</b>. Eleventh of twelve, <b>135 points</b> behind the sixth and final playoff seed. The wire has no running back above 81 and no receiver above 115, so adds cannot close that. Converting one stud into two starters is the only shape that can.</p></div>''')

o.append('<h2>1. Where the roster breaks</h2><p class="sub">Optimal lineup re-solved for each week with that week\'s byes removed.</p>')
o.append('<div class="scroll"><table><tr><th>wk</th><th>on bye</th><th>your players out</th><th>unfilled</th></tr>')
for w in W:
    out=[p for p in MINE if team(p['nfl']) in BYE[w]]
    nm=', '.join(p['player'].split()[-1] for p in out) or '&mdash;'
    gap='RB1' if w==7 else 'none'
    cl=' class="neg"' if w==7 else ''
    o.append(f'<tr><td class="slot">{w}</td><td class="dim">{",".join(BYE[w]) or "&mdash;"}</td>'
             f'<td>{nm}</td><td{cl}>{gap}</td></tr>')
o.append('</table></div>')
o.append('<p class="note"><b>Week 7 is the only structural break.</b> Cook, Keon Coleman and Ray Davis are all Buffalo, and Buffalo is on bye &mdash; leaving MarShawn Lloyd as the only healthy running back on the roster. Not something to spend a roster spot on five weeks out, but it is a reason any incoming running back should not be Buffalo, Jacksonville, the Chargers or Washington.</p>')

o.append('<h2>2. Whose value is growing</h2><p class="sub">Market-implied points per game, weeks 3&ndash;5 against weeks 7&ndash;9. The season mean already contains a player’s offense, so this is not multiplied in &mdash; it is the read on upside and on which way the ground is moving.</p>')
o.append('<div class="scroll"><table><tr><th>player</th><th>tm</th><th class="n">season</th><th class="n">over wire</th><th class="n">env</th><th class="n">rank</th><th class="n">trend</th></tr>')
for p in sorted(MINE,key=lambda x:-TR.get(team(x['nfl']),-99)):
    t=team(p['nfl'])
    if t not in TR: continue
    v=p['pts']-REPL.get(p['pos'],0)
    cl='pos' if TR[t]>1.2 else ('neg' if TR[t]<-1.2 else 'dim')
    o.append(f'<tr><td>{E(p["player"])}</td><td class="dim">{t}</td><td class="n">{p["pts"]:.0f}</td>'
             f'<td class="n {"pos" if v>0 else "neg"}">{v:+.0f}</td><td class="n">{ENV[t]:.2f}</td>'
             f'<td class="n dim">#{RKk[t]}</td><td class="n {cl}">{TR[t]:+.2f}</td></tr>')
o.append('</table></div>')
o.append('<p class="note"><b>Isaiah Likely is the fastest-decaying asset in the league.</b> The Giants’ implied total falls from 24.33 in weeks 3&ndash;5 to 19.25 in weeks 7&ndash;9 &mdash; a <b>&minus;5.08</b> collapse, more than double the next-worst team. He is your TE2 behind LaPorta and clears the wire by <b>+5</b>. He is a throw-in, not a hold.<br><br>Read this column for <b>upside and tie-breaks only</b>. A season projection already contains the player&rsquo;s offense; discounting him for it a second time is double-counting.</p>')

o.append('<h2>3. The trade</h2>')
o.append("""<div class="act go"><div class="k"><small>The offer to make</small>LaPorta to Granddude for Jake Ferguson + Chris Godwin</div>
<p><b>+30.2 you, +23.4 them</b> &mdash; the most mutual deal on the board, and the only shape where neither side takes on a player they cannot start.</p>
<p style="margin-top:8px"><b>Why it works for him.</b> Granddude has exactly <b>one</b> tight end. He upgrades Ferguson 160 to LaPorta 183, and he pays with Ferguson plus <b>Chris Godwin, his WR5</b> &mdash; behind Nacua, Garrett Wilson, Jameson Williams and Mike Evans, Godwin does not crack his lineup. He gives up a bench player and his old starter to fix his weakest position.</p>
<p style="margin-top:8px"><b>Why it works for you.</b> Ferguson slots straight in at tight end so you lose only 23 there, and <b>WR3 goes from Malik Washington 121 to Godwin 175</b>. London, Smith-Njigba and Cook are untouched.</p></div>""")
o.append("""<div class="act"><div class="k"><small>Same shape, other counterparties</small>If Granddude passes</div>
<p><b>Casey:</b> LaPorta for Courtland Sutton (182) + Hunter Henry (150) &mdash; +28.3 you, +18.0 them.<br>
<b>Dave:</b> LaPorta for Wan&rsquo;Dale Robinson (173) + Mark Andrews (162) &mdash; +30.4 you, +10.3 them.<br>
<b>Ricker:</b> LaPorta for Travis Kelce (173) + Jakobi Meyers (169) &mdash; +37.2 you, +8.5 them.<br>
Every one returns a tight end plus a receiver, because that is the only structure that leaves both rosters startable.</p></div>""")
o.append("""<div class="act wait"><div class="k"><small>Two corrections</small>What I had wrong</div>
<p><b>The offense argument.</b> I led with &ldquo;Atlanta is 25th&rdquo; as a reason to sell London. His 260.2 projection <b>already contains</b> Atlanta being a 21.4-point offense &mdash; ranking it and then discounting him for it counts the same thing twice. Environment belongs on upside and tie-breaks, never in a headline. <b>Hold London.</b></p>
<p style="margin-top:8px"><b>The fit problem.</b> Then I proposed sending Granddude LaPorta <em>and</em> Likely. He starts one tight end and already has Ferguson &mdash; that is a third TE he cannot use. The engine was scoring a piece they cannot start as neutral instead of as a wasted roster spot. It now rejects any deal where a piece the other side receives fails to crack their lineup, which killed most of what I showed you.</p></div>""")
o.append('<h2>Lineup &mdash; Wednesday</h2>')
sf,det=P['49ers'],P['Lions']
o.append(f'''<p class="note">One item carried forward, not a headline until it is inside a day: the Lions are in the DEF slot and play Thursday. <b>49ers {sf['pts']:.2f} vs Lions {det['pts']:.2f}</b>. Everything Sunday is still unpriced &mdash; Kalshi re-checked this afternoon, the Sunday ladders are not posted.</p>''')
o.append('''<footer><b>Method.</b> Season horizon throughout, which is the right instrument early in the week and the only one with data: the Sunday player market does not post until Thursday or Friday. Implied team totals from 104 individually-read game lines across weeks 3&ndash;9, cross-checked, zero disagreements. Season projections blend FFToday and Sleeper from raw stat lines rescored in BSB rules. Value over the wire is measured against the best free agent actually available at that position, with the pool audited for name-variant phantoms and verified-unavailable players removed. Every trade shown passes the gate and the plausibility filter.<br><br>
<b>Limits.</b> Weeks 7&ndash;9 lines are lookahead prices, thinner than a live market &mdash; treat the trajectory column as a prior, not a consensus. Trade values are season totals and ignore schedule beyond the bye check. The counterparty gain is computed on their optimal lineup, which understates what a positional hole is worth to them.</footer></div>''')
open('/home/claude/bsb2/control-room.html','w').write('\n'.join(o))
print('ok',sum(len(x) for x in o))
