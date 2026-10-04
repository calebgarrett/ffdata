"""Worker: one build in a scenario root (FF_ROOT/FF_NOW/FF_FAST set by run.py).
Writes <FF_ROOT>/out.json and nothing outside FF_ROOT."""
import sys, os, json, re, html as _h, io, contextlib
CODE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CODE)
os.chdir(os.environ['FF_ROOT'])

def main():
    out = {}
    buf = io.StringIO()
    import ff
    from lib import contract as CT, sanity as SAN, card as CARD, paths as PA
    assert PA.root() == os.environ['FF_ROOT']
    try:
        with contextlib.redirect_stdout(buf): run = ff.build()
    except CT.Refused as e:
        out = dict(refused=sorted({v.code for v in e.result.refused}),
                   codes=sorted({v.code for v in e.result.violations}), log=buf.getvalue()[-3000:])
        json.dump(out, open(os.path.join(PA.root(), 'out.json'), 'w'), indent=1, default=str); return
    html = run.get('card_html')
    err = run.get('card_render_error')
    if html is None and not err:
        try: html = CARD.render(run)
        except Exception as e: err = repr(e)
    bad = SAN.check(run, html) if html else [f'card did not render: {err}']
    try: sim = SAN.check_plan(run)
    except Exception as e: sim = [f'check_plan raised {e!r}']
    led = json.load(open(PA.data('ledger.json'))) if os.path.exists(PA.data('ledger.json')) else []
    out = dict(refused=[], codes=(run['plan_json'] or {}).get('contract', {}).get('codes', []),
               plan=run.get('plan_json'), sanity=bad, plan_sim=sim, ledger_rows=len(led),
               card_text=_h.unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or ''))),
               log=buf.getvalue()[-3000:])
    json.dump(out, open(os.path.join(PA.root(), 'out.json'), 'w'), indent=1, default=str)

if __name__ == '__main__':
    main()
