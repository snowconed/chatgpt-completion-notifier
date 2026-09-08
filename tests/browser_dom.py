"""Offline DOM tests: mocked Chrome APIs, real Chromium DOM and trusted clicks.
No network, native extension installation, logged-in ChatGPT or OS banners.
Usage: python tests/browser_dom.py --chromium /usr/bin/chromium
Dependencies for developers only: Python + playwright + Chromium.
URL navigation and worker behavior are covered separately by the Node unit tests.
"""
from pathlib import Path
import argparse, json, re, base64
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--chromium',default='/usr/bin/chromium');parser.add_argument('--report');parser.add_argument('--screenshot');args=parser.parse_args()
MOCK=r'''() => {
 window.testMessages=[];window.testListeners=[];window.testStorageListeners=[];
 if (!crypto.randomUUID) crypto.randomUUID = () => '00000000-0000-4000-8000-'+String(Math.random()).slice(2,14);
 const cfg={enabled:true,notifyWhenFocused:true,sound:true,volume:0.5,settleMs:5000,keepVisible:false};
 window.chrome={runtime:{id:'test',getURL:p=>'chrome-extension://test/'+p,
 onMessage:{addListener:f=>window.testListeners.push(f)},
 sendMessage:async m=>{window.testMessages.push(m);if(m.type==='diagnostics')return {ok:true,permission:'granted',recent:[]};return {ok:true,result:'sent'};}},
 storage:{local:{get:async()=>({settings:cfg}),set:async v=>Object.assign(cfg,v.settings)},onChanged:{addListener:f=>window.testStorageListeners.push(f)}},
 tabs:{query:async()=>[{id:1,url:'https://chatgpt.com/c/fixture'}],sendMessage:async()=>({ok:true,phase:'idle',enabled:true}),create:async()=>({id:2})}};
}'''
results=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox','--disable-gpu'])
 context=browser.new_context(viewport={'width':400,'height':820})
 def inject(p,name):p.add_script_tag(content=(ROOT/name).read_text(encoding='utf-8'))
 def page_new(mode='stream'):
  page=context.new_page();page.set_content((ROOT/'tests/dom-fixture.html').read_text(encoding='utf-8'))
  page.evaluate(MOCK);page.clock.install()
  page.evaluate('(mode)=>window.fixtureMode=mode',mode)
  for name in ['shared.js','detector-core.js','content.js']:inject(page,name)
  page.clock.run_for(2200)
  return page
 def completions(page):return page.evaluate("testMessages.filter(m=>m.type==='complete').length")
 def check(name,fn):
  fn();results.append({'name':name,'passed':True});print('PASS',name,flush=True)
 def old():
  p=page_new();p.clock.run_for(15000);assert completions(p)==0;p.close()
 check('No completion on opening an old conversation',old)
 def normal():
  p=page_new();p.click('#send');p.clock.run_for(500);p.evaluate("fixtureToken('Streaming tokens')");p.clock.run_for(6500)
  assert completions(p)==0
  p.evaluate('fixtureFinish()');p.clock.run_for(4000);assert completions(p)==0
  p.clock.run_for(3500);assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Long text pause while busy; one event after completion',normal)
 def stopped():
  p=page_new();p.click('#send');p.clock.run_for(600);p.evaluate("fixtureToken('Partial answer')");p.click('#stop');p.clock.run_for(12000);assert completions(p)==0;p.close()
 check('Trusted manual Stop click suppresses completion',stopped)
 def fast():
  p=page_new('fast');p.click('#send');p.clock.run_for(8000);assert completions(p)==1;p.close()
 check('Fast response with stop added/removed in the same event',fast)
 def japanese():
  p=page_new('japanese');p.click('#send');p.clock.run_for(500)
  p.evaluate("document.querySelector('.result-streaming').className='' ")
  p.evaluate("fixtureToken('Thinking with Japanese stop label')");p.clock.run_for(8000);assert completions(p)==0
  p.evaluate('fixtureFinish()');p.clock.run_for(7500);assert completions(p)==1;p.close()
 check('Japanese stop-label fallback without explicit test ID',japanese)
 def late_text():
  p=page_new();p.click('#send');p.clock.run_for(500);p.evaluate('fixtureFinish()');p.clock.run_for(4000);p.evaluate("fixtureToken('Final tokens added later')");p.clock.run_for(3000);assert completions(p)==0;p.clock.run_for(4500);assert completions(p)==1;p.close()
 check('Late response DOM mutation postpones completion',late_text)
 def multi():
  p=page_new();q=page_new();p.click('#send');q.click('#send');p.clock.run_for(500);q.clock.run_for(500);p.evaluate('fixtureFinish()');q.evaluate('fixtureFinish()');p.clock.run_for(7500);q.clock.run_for(7500);assert completions(p)==completions(q)==1;p.close();q.close()
 check('Two independent tab detectors',multi)
 def popup():
  p=context.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
  html=(ROOT/'popup.html').read_text(encoding='utf-8')
  html=re.sub(r'<script src="[^"]+"></script>','',html)
  html=html.replace('<link rel="stylesheet" href="popup.css">','<style>'+(ROOT/'popup.css').read_text()+'</style>')
  icon=base64.b64encode((ROOT/'assets/icon48.png').read_bytes()).decode()
  html=html.replace('assets/icon48.png','data:image/png;base64,'+icon)
  p.set_content(html);p.evaluate(MOCK);inject(p,'shared.js');inject(p,'popup.js');p.wait_for_timeout(150)
  assert p.locator('#enabled').is_checked();assert p.locator('#tabStatus').inner_text()=='接続済み・待機中'
  p.click('#testNotification');p.wait_for_timeout(150);assert '成功' in p.locator('#testResult').inner_text()
  assert not errors,errors
  if args.screenshot:p.screenshot(path=args.screenshot,full_page=True)
  p.close()
 check('Popup layout, defaults and test-button wiring (mocked APIs)',popup)
 report={'browser':browser.version,'test_type':'Offline fixture with mock Chrome APIs; NO native extension installation, Windows banner, or logged-in ChatGPT verification','results':results}
 if args.report:Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 browser.close()
print(json.dumps({'passed':len(results),'failed':0}))
