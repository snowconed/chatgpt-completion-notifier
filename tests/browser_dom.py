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
IMAGE_DATA='data:image/png;base64,'+base64.b64encode((ROOT/'assets/icon48.png').read_bytes()).decode()
parser=argparse.ArgumentParser();parser.add_argument('--chromium',help='Chrome/Chromium executable; defaults to Playwright-managed Chromium');parser.add_argument('--report');parser.add_argument('--screenshot');args=parser.parse_args()
MOCK=r'''() => {
 window.testMessages=[];window.testListeners=[];window.testStorageListeners=[];
 if (!crypto.randomUUID) crypto.randomUUID = () => '00000000-0000-4000-8000-'+String(Math.random()).slice(2,14);
 const cfg={enabled:true,notifyWhenFocused:true,sound:true,volume:0.5,settleMs:5000,keepVisible:false};
 window.chrome={runtime:{id:'test',getURL:p=>'chrome-extension://test/'+p,getManifest:()=>({version:'1.0.1'}),
 onMessage:{addListener:f=>window.testListeners.push(f)},
 sendMessage:async m=>{window.testMessages.push(m);if(m.type==='diagnostics')return {ok:true,permission:'granted',recent:[]};return {ok:true,result:'sent'};}},
 storage:{local:{get:async()=>({settings:cfg}),set:async v=>Object.assign(cfg,v.settings)},onChanged:{addListener:f=>window.testStorageListeners.push(f)}},
 tabs:{query:async()=>[{id:1,url:'https://chatgpt.com/c/fixture'}],sendMessage:async()=>({ok:true,phase:'idle',enabled:true}),create:async()=>({id:2})}};
}'''
results=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox','--disable-gpu'])
 context=browser.new_context(viewport={'width':400,'height':820})
 context.route('**/*',lambda route:route.abort())
 def inject(p,name):p.add_script_tag(content=(ROOT/name).read_text(encoding='utf-8'))
 def page_new(mode='stream'):
  page=context.new_page();page.set_content((ROOT/'tests/dom-fixture.html').read_text(encoding='utf-8'))
  page.evaluate(MOCK);page.clock.install()
  page.evaluate('(mode)=>window.fixtureMode=mode',mode)
  for name in ['shared.js','detector-core.js','content.js']:inject(page,name)
  page.clock.run_for(2200)
  return page
 def completions(page):return page.evaluate("testMessages.filter(m=>m.type==='complete').length")
 def status(page):
  return page.evaluate("""() => {
   let result;
   for (const listener of testListeners) listener({target:'content',type:'get-status'},{id:'test'},value=>{result=value;});
   return result;
  }""")
 def visual(page,kind='svg',sibling=False,finish=False):
  # Transform the existing fixture; all media stays offline. We inspect only the
  # outer iframe element, without assuming its document has finished rendering.
  page.evaluate("""({kind,sibling,finish}) => {
   if (finish) fixtureFinish();
   const turn=document.querySelector('#thread').lastElementChild;
   const response=turn.querySelector('[data-message-author-role="assistant"]');
   response.textContent='';
   let media;
   if (kind==='svg') {
    media=document.createElementNS('http://www.w3.org/2000/svg','svg');
    media.setAttribute('width','280');media.setAttribute('height','160');
    media.innerHTML='<path d="M 20 120 L 140 20 L 260 120 Z" fill="teal"/>';
   } else if (kind==='iframe') {
    media=document.createElement('iframe');media.width='280';media.height='160';
    media.srcdoc='<html><body><svg width="250" height="130"><circle cx="100" cy="60" r="40" fill="teal"/></svg></body></html>';
   } else if (kind==='canvas') {
    media=document.createElement('canvas');media.width=280;media.height=160;
    media.getContext('2d').fillRect(20,20,100,100);
   }
   media.id='fixture-visual';(sibling?turn:response).append(media);
  }""",{'kind':kind,'sibling':sibling,'finish':finish})
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
 def sibling_iframe():
  p=page_new();p.click('#send');p.clock.run_for(500)
  visual(p,'iframe',sibling=True,finish=True)
  p.clock.run_for(4000);assert completions(p)==0
  assert status(p)['hasOutput'] is True
  p.clock.run_for(3500);assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Empty answer body with sibling iframe emits one completion',sibling_iframe)
 def svg_only():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,finish=True)
  p.clock.run_for(7500);assert status(p)['hasOutput'] is True;assert completions(p)==1;p.close()
 check('SVG-only answer is recognized as output',svg_only)
 def mixed_roles():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,sibling=True,finish=True)
  p.evaluate("""() => {
   const turn=document.querySelector('#thread').lastElementChild;
   turn.dataset.turn='assistant';turn.querySelector('[data-message-author-role="assistant"]').removeAttribute('data-message-author-role');
   turn.previousElementSibling.dataset.turn='user';turn.previousElementSibling.querySelector('[data-message-author-role="user"]').removeAttribute('data-message-author-role');
  }""")
  p.clock.run_for(7500);assert status(p)['hasOutput'] is True;assert completions(p)==1;p.close()
 check('Latest data-turn answer wins over older role-marked answers',mixed_roles)
 def busy_canvas():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,'canvas',sibling=True)
  p.clock.run_for(12000);assert status(p)['hasOutput'] is True;assert completions(p)==0
  p.evaluate("fixtureFinish();document.querySelector('#thread').lastElementChild.querySelector('[data-message-author-role=assistant]').textContent=''")
  p.clock.run_for(7500);assert completions(p)==1;p.close()
 check('Canvas displayed during generation does not trigger completion',busy_canvas)
 def copy_icon_only():
  p=page_new();p.click('#send');p.clock.run_for(500)
  p.evaluate("""() => {
   fixtureFinish();const turn=document.querySelector('#thread').lastElementChild;
   turn.querySelector('[data-message-author-role="assistant"]').textContent='';
   turn.querySelector('button').innerHTML='<svg width="24" height="24"><path d="M 0 0 L 20 20"/></svg>';
  }""")
  p.clock.run_for(15000);s=status(p)
  assert s['assistantFound'] is True and s['finalControls'] is True
  assert s['hasOutput'] is False and s['phase']=='waiting';assert completions(p)==0;p.close()
 check('Copy-button SVG with empty body remains waiting without notification',copy_icon_only)
 def decorative_icon_only():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,finish=True)
  p.evaluate("const icon=document.querySelector('#fixture-visual');icon.setAttribute('width','16');icon.setAttribute('height','16')")
  p.clock.run_for(15000);assert status(p)['hasOutput'] is False;assert completions(p)==0;p.close()
 check('Small decorative SVG does not count as answer output',decorative_icon_only)
 def hidden_visuals():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,'iframe',sibling=True,finish=True)
  p.evaluate("""() => {
   document.querySelector('#fixture-visual').hidden=true;
   const response=document.querySelector('#thread').lastElementChild.querySelector('[data-message-author-role="assistant"]');
   response.innerHTML='<svg width="280" height="160" style="display:none"><path d="M 0 0 L 200 100"/></svg><canvas width="280" height="160" aria-hidden="true"></canvas>';
  }""")
  p.clock.run_for(15000);assert status(p)['hasOutput'] is False;assert completions(p)==0;p.close()
 check('Hidden iframe, SVG and canvas do not count as output',hidden_visuals)
 def old_visual():
  p=page_new();visual(p,sibling=True);p.clock.run_for(2000)
  p.click('#send');p.clock.run_for(500)
  p.evaluate("fixtureFinish();document.querySelector('#thread').lastElementChild.querySelector('[data-message-author-role=assistant]').textContent=''")
  p.clock.run_for(15000);assert status(p)['hasOutput'] is False;assert completions(p)==0;p.close()
 check('Visual in a previous answer cannot complete a new empty answer',old_visual)
 def user_visual():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,finish=True)
  p.evaluate("document.querySelector('#thread').lastElementChild.previousElementSibling.append(document.querySelector('#fixture-visual'))")
  p.clock.run_for(15000);assert status(p)['hasOutput'] is False;assert completions(p)==0;p.close()
 check('Visual attached to the user prompt does not count as assistant output',user_visual)
 def visual_without_final_controls():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,finish=True)
  p.evaluate("document.querySelector('#thread').lastElementChild.querySelector('button').remove()")
  p.clock.run_for(10000);assert status(p)['hasOutput'] is True;assert completions(p)==0
  p.evaluate("""() => {
   const copy=document.createElement('button');copy.dataset.testid='copy-turn-action-button';copy.textContent='Copy';
   document.querySelector('#thread').lastElementChild.append(copy);
  }""")
  p.clock.run_for(7500);assert completions(p)==1;p.close()
 check('Visual-only answer also requires final answer controls',visual_without_final_controls)
 def stopped_visual_regeneration():
  p=page_new();visual(p);p.clock.run_for(2000)
  p.evaluate("""() => {
   const turn=document.querySelector('#thread').lastElementChild;
   const regenerate=document.createElement('button');regenerate.id='regenerate';regenerate.dataset.testid='regenerate-thread-action-button';regenerate.textContent='Regenerate';
   regenerate.addEventListener('click',()=>{
    const response=turn.querySelector('[data-message-author-role="assistant"]');response.className='result-streaming';
    response.querySelector('path').setAttribute('d','M 20 20 L 250 130');
    document.querySelector('#send').hidden=true;
    const stop=document.createElement('button');stop.id='stop';stop.type='button';stop.dataset.testid='stop-button';stop.textContent='Stop';
    stop.addEventListener('click',()=>{response.className='';stop.remove();document.querySelector('#send').hidden=false;});
    document.querySelector('form').append(stop);
   });turn.append(regenerate);
  }""")
  p.click('#regenerate');p.clock.run_for(600);assert status(p)['busy'] is True
  p.click('#stop');p.clock.run_for(15000);assert completions(p)==0;p.close()
 check('Trusted Stop during SVG regeneration suppresses completion',stopped_visual_regeneration)
 def late_svg_change():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,finish=True)
  p.clock.run_for(4000);assert completions(p)==0
  p.evaluate("document.querySelector('#fixture-visual path').setAttribute('d','M 20 20 L 140 130 L 260 20 Z')")
  p.clock.run_for(3000);assert completions(p)==0
  p.clock.run_for(4500);assert completions(p)==1;p.close()
 check('Late SVG geometry change restarts the completion settling interval',late_svg_change)
 def small_image_only():
  p=page_new();p.click('#send');p.clock.run_for(500)
  p.evaluate("""src => {
   fixtureFinish();const turn=document.querySelector('#thread').lastElementChild;
   turn.querySelector('[data-message-author-role="assistant"]').textContent='';
   const icon=document.createElement('img');icon.width=24;icon.height=24;icon.alt='';icon.src=src;turn.append(icon);
  }""",IMAGE_DATA)
  p.clock.run_for(15000);assert status(p)['hasOutput'] is False;assert completions(p)==0;p.close()
 check('Small image beside empty answer is not output',small_image_only)
 def expandable_image():
  p=page_new();p.click('#send');p.clock.run_for(500)
  p.evaluate("""src => {
   fixtureFinish();const response=document.querySelector('#thread').lastElementChild.querySelector('[data-message-author-role="assistant"]');
   response.innerHTML='<button aria-label="Open image"><img width="280" height="160" alt="Fixture plot"></button>';
   response.querySelector('img').src=src;
  }""",IMAGE_DATA)
  p.locator('#thread img').evaluate('(img)=>img.decode()')
  p.clock.run_for(7500);s=status(p)
  assert s['hasOutput'] is True,(s,p.locator('#thread img').evaluate('(el)=>({width:el.getBoundingClientRect().width,height:el.getBoundingClientRect().height})'))
  assert completions(p)==1;p.close()
 check('Large result image inside an expand button still counts as output',expandable_image)
 def canvas_fallback():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,'canvas',finish=True)
  p.evaluate("""() => {
   document.querySelector('#fixture-visual').textContent='Alternative chart description';
   document.querySelector('#thread').lastElementChild.querySelector('button').remove();
  }""")
  p.clock.run_for(15000);assert status(p)['visualOnly'] is True;assert completions(p)==0;p.close()
 check('Canvas fallback description cannot bypass final answer controls',canvas_fallback)
 def diagram_copy_only():
  p=page_new();p.click('#send');p.clock.run_for(500);visual(p,finish=True)
  p.evaluate("""() => {
   const copy=document.querySelector('#thread').lastElementChild.querySelector('button');
   copy.removeAttribute('data-testid');copy.setAttribute('aria-label','Copy');
  }""")
  p.clock.run_for(15000);assert status(p)['finalControls'] is False;assert completions(p)==0;p.close()
 check('Generic diagram Copy button is not an answer completion signal',diagram_copy_only)
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
