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
 window.chrome={runtime:{id:'test',getURL:p=>'chrome-extension://test/'+p,getManifest:()=>({version:'1.0.3'}),
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
 def page_new(mode='stream',fixture='tests/dom-fixture.html',setup=None):
  page=context.new_page();page.set_content((ROOT/fixture).read_text(encoding='utf-8'))
  page.evaluate(MOCK);page.clock.install()
  page.evaluate('(mode)=>window.fixtureMode=mode',mode)
  if setup is not None:page.evaluate(setup)
  for name in ['shared.js','detector-core.js','content.js']:inject(page,name)
  page.clock.run_for(2200)
  return page
 def current_page(mode='stream',setup=None):return page_new(mode,'tests/current-ui-fixture.html',setup)
 def logged_page(mode='stream',setup=None):return page_new(mode,'tests/logged-in-ui-fixture.html',setup)
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
 def current_discovery():
  p=current_page();s=status(p)
  assert s['composerFound'] is True,s
  assert s['assistantFound'] is True,s
  assert s['hasOutput'] is True and s['finalControls'] is True,s
  assert s['busy'] is False,s;p.close()
 check('Current UI discovers message-role answers and the footer textarea',current_discovery)
 def current_old():
  p=current_page();p.clock.run_for(20000)
  assert completions(p)==0;assert status(p)['active'] is False;p.close()
 check('Current UI does not notify for an already completed conversation',current_old)
 def current_old_loading_widget():
  p=current_page(setup="""() => {
   const response=document.querySelector('[data-assistant-markdown-root]');
   response.insertAdjacentHTML('beforeend','<span data-fixture-loading aria-busy="true">Loading an old attachment</span>');
  }""")
  s=status(p)
  assert s['busy'] is False and s['streamingDetected'] is False,s
  assert s['active'] is False,s
  p.clock.run_for(10000);assert completions(p)==0
  p.evaluate("document.querySelector('[data-fixture-loading]').setAttribute('aria-busy','false')")
  p.clock.run_for(10000);s=status(p)
  assert s['busy'] is False and s['active'] is False,s
  assert completions(p)==0
  assert p.evaluate("testMessages.filter(m=>m.type==='status' && m.status.phase==='generating').length")==0
  p.close()
 check('Current UI loading widget in a completed answer never starts monitoring',current_old_loading_widget)
 def current_previous_loading_widget():
  p=current_page();p.click('#current-submit');p.clock.run_for(500)
  assert status(p)['busy'] is True
  p.evaluate("""() => {
   const oldResponse=document.querySelector('[data-assistant-markdown-root]');
   oldResponse.insertAdjacentHTML('beforeend','<span data-fixture-loading aria-busy="true">Loading an old attachment</span>');
   currentFinish();
  }""")
  p.clock.run_for(7500);s=status(p)
  assert p.locator('[data-fixture-loading]').get_attribute('aria-busy')=='true'
  assert s['busy'] is False and s['streamingDetected'] is False,s
  assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Current UI loading widget in an older turn cannot block a new completion',current_previous_loading_widget)
 def current_idle_submit():
  p=current_page();p.clock.run_for(15000);s=status(p)
  assert p.locator('[data-composer-submit]').get_attribute('type')=='submit'
  assert s['busy'] is False and s['stopDetected'] is False,s
  assert completions(p)==0;p.close()
 check('Current UI ordinary submit button does not imply generation',current_idle_submit)
 def current_normal():
  p=current_page();p.click('#current-submit');p.clock.run_for(500);s=status(p)
  assert s['composerFound'] is True and s['assistantFound'] is True,s
  assert s['busy'] is True and s['stopDetected'] is True,s
  p.evaluate("currentToken('Current UI streaming answer')");p.clock.run_for(10000)
  assert completions(p)==0
  p.evaluate('currentFinish()')
  assert p.locator('[data-composer-submit]').get_attribute('aria-disabled')=='true'
  assert p.locator('[data-mobile-composer-prompt]').is_enabled()
  p.clock.run_for(4000);assert completions(p)==0
  p.clock.run_for(3500);assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Current UI streams then notifies once with an empty-input disabled send button',current_normal)
 def current_fast():
  p=current_page('fast');p.click('#current-submit');p.clock.run_for(8000)
  assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Current UI fast answer with stop markers added and removed synchronously',current_fast)
 def current_stopped():
  p=current_page();p.click('#current-submit');p.clock.run_for(500)
  p.evaluate("currentToken('Partial current UI answer')");p.click('#current-submit')
  p.clock.run_for(15000);assert completions(p)==0
  assert status(p)['lastEvent']=='manual-stop';p.close()
 check('Current UI shared send-stop button suppresses manual-stop notification',current_stopped)
 def current_svg():
  p=current_page();p.click('#current-submit');p.clock.run_for(500)
  p.evaluate("""() => {
   const response=document.querySelector('[data-conversation-transcript]').lastElementChild.querySelector('[data-assistant-markdown-root]');
   response.innerHTML='<svg width="280" height="160"><path d="M 20 120 L 140 20 L 260 120 Z" fill="teal"/></svg>';
  }""")
  p.clock.run_for(8000);assert completions(p)==0
  p.evaluate('currentFinish({preserve:true})');p.clock.run_for(7500)
  assert status(p)['visualOnly'] is True;assert completions(p)==1;p.close()
 check('Current UI SVG-only answer waits for generation to finish',current_svg)
 def current_iframe():
  p=current_page();p.click('#current-submit');p.clock.run_for(500)
  p.evaluate("""() => {
   const turn=document.querySelector('[data-conversation-transcript]').lastElementChild;
   const frame=document.createElement('iframe');frame.width='280';frame.height='160';
   frame.srcdoc='<html><body><canvas width="250" height="130"></canvas></body></html>';
   turn.append(frame);currentFinish({preserve:true});
  }""")
  p.clock.run_for(7500);s=status(p)
  assert s['hasOutput'] is True and s['visualOnly'] is True,s
  assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Current UI sibling iframe with empty markdown emits one completion',current_iframe)
 def current_late_completion_marker():
  p=current_page();p.click('#current-submit');p.clock.run_for(500)
  p.evaluate('currentFinish({mark:false})');p.clock.run_for(12000);s=status(p)
  assert s['busy'] is False and s['hasOutput'] is True and s['finalControls'] is True,s
  assert completions(p)==0;assert s['phase']=='waiting',s
  p.evaluate("document.querySelector('[data-conversation-transcript]').lastElementChild.setAttribute('data-message-complete','')")
  p.clock.run_for(4000);assert completions(p)==0
  p.clock.run_for(3500);assert completions(p)==1;p.close()
 check('Current UI waits a full settling interval after a late completion marker',current_late_completion_marker)
 def current_form_busy():
  p=current_page();p.click('#current-submit');p.clock.run_for(500)
  p.evaluate("""() => {
   currentToken('Still generating with the form marker');
   const button=document.querySelector('[data-composer-submit]');
   button.removeAttribute('data-stop-generating');button.type='submit';
   button.setAttribute('aria-label','メッセージを送信します');
  }""")
  p.clock.run_for(10000);assert status(p)['busy'] is True;assert completions(p)==0
  p.evaluate('currentFinish()');p.clock.run_for(7500);assert completions(p)==1;p.close()
 check('Current UI submitting form alone keeps generation active',current_form_busy)
 def current_scan_retry():
  p=current_page();before=status(p)
  p.evaluate("""() => {
   window.originalQuerySelector=document.querySelector;
   document.querySelector=function(selector) {
    if (selector==='[data-rail-chat-transcript],[data-conversation-transcript]') throw new Error('Synthetic transient DOM failure');
    return window.originalQuerySelector.call(this,selector);
   };
  }""")
  p.clock.run_for(1600);failed=status(p)
  assert failed['scanError'] is True and failed['lastEvent']=='snapshot-retry',failed
  assert failed['scanAttemptAt']>before['sampledAt'],failed
  assert failed['sampledAt']==before['sampledAt'],failed
  p.evaluate('document.querySelector=window.originalQuerySelector;delete window.originalQuerySelector')
  p.clock.run_for(1600);recovered=status(p)
  assert recovered['scanError'] is False and recovered['composerFound'] is True,recovered
  assert recovered['sampledAt']>failed['sampledAt'];assert completions(p)==0;p.close()
 check('Current UI reports a transient scan error and recovers on the next scan',current_scan_retry)
 def logged_discovery():
  p=logged_page();s=status(p)
  assert s['composerFound'] is True and s['assistantFound'] is True and s['userFound'] is True,s
  assert s['hasOutput'] is True and s['finalControls'] is True and s['afterUser'] is True,s
  assert s['completionRequired'] is True and s['completionMarked'] is True,s
  assert s['uiVariant']=='thread' and s['busy'] is False,s;p.close()
 check('Logged-in thread UI discovers nested response bodies, roles and composer',logged_discovery)
 def logged_old():
  p=logged_page();p.clock.run_for(20000);s=status(p)
  assert s['active'] is False and s['busy'] is False,s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI does not notify for an old completed answer',logged_old)
 def logged_empty():
  p=logged_page(setup="""() => {
   loggedFixture.activeRoot.querySelector('[data-dil-response]').textContent='';
  }""");p.clock.run_for(10000);s=status(p)
  assert s['assistantFound'] is True and s['finalControls'] is True,s
  assert s['hasOutput'] is False and s['active'] is False,s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI role headings and action labels are not answer output',logged_empty)
 def logged_inactive_scope():
  p=logged_page(setup="""() => {
   const {activeRoot,inactiveRoot}=loggedFixture;
   activeRoot.querySelector('[data-dil-response]').textContent='';
   inactiveRoot.style.display='block';document.body.prepend(inactiveRoot);
   inactiveRoot.querySelector('[data-dil-response]').className='result-streaming';
  }""");p.clock.run_for(10000);s=status(p)
  assert s['uiVariant']=='thread' and s['composerFound'] is True,s
  assert s['hasOutput'] is False and s['busy'] is False and s['active'] is False,s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI ignores an inactive page even when it is first and visible',logged_inactive_scope)
 def logged_virtualized_turn():
  p=logged_page()
  p.evaluate("""() => {
   const turn=loggedFixture.createTurn(loggedFixture.transcript,{
    userText:'Another historical fixture prompt',answerText:'Another historical fixture answer',complete:true
   });
   loggedFixture.transcript.replaceChildren(turn);
  }""");p.clock.run_for(15000);s=status(p)
  assert s['userFound'] is True and s['assistantFound'] is True and s['hasOutput'] is True,s
  assert s['active'] is False and s['busy'] is False,s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI historical turn replacement does not arm generation',logged_virtualized_turn)
 def logged_cloned_turn():
  p=logged_page()
  p.evaluate("""() => {
   const clone=loggedFixture.latestTurn().cloneNode(true);
   loggedFixture.transcript.replaceChildren(clone);
  }""");p.clock.run_for(15000);s=status(p)
  assert s['assistantFound'] is True and s['completionMarked'] is True,s
  assert s['active'] is False and s['busy'] is False,s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI cloned nodes with unchanged keys do not arm generation',logged_cloned_turn)
 def logged_no_active_page():
  p=logged_page(setup="""() => {
   loggedFixture.activeRoot.setAttribute('data-app-shell-active-page','false');
   loggedFixture.inactiveRoot.style.display='block';
  }""");p.clock.run_for(15000);s=status(p)
  assert s['composerFound'] is False and s['assistantFound'] is False and s['userFound'] is False,s
  assert s['hasOutput'] is False and s['busy'] is False and s['active'] is False,s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI finds no conversation when all app pages are inactive',logged_no_active_page)
 def logged_user_media():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate("""() => {
   const turn=loggedFixture.latestTurn();
   const bubble=turn.querySelector('[data-user-message-bubble]');
   bubble.insertAdjacentHTML('beforeend','<svg width="280" height="160"><circle cx="100" cy="70" r="50" fill="teal"/></svg>');
   loggedFinish({preserve:true});
  }""");p.clock.run_for(15000);s=status(p)
  assert s['assistantFound'] is True and s['finalControls'] is True,s
  assert s['hasOutput'] is False and s['phase']=='waiting',s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI excludes user media from an empty assistant answer in the same turn',logged_user_media)
 def logged_normal():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500);s=status(p)
  assert s['busy'] is True and s['completionMarked'] is False,s
  p.evaluate("loggedToken('Streaming logged-in fixture answer')");p.clock.run_for(10000)
  assert completions(p)==0
  p.evaluate('loggedFinish()');p.clock.run_for(4000);assert completions(p)==0
  p.clock.run_for(3500);assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Logged-in thread UI waits for completion and notifies once',logged_normal)
 def logged_fast():
  p=logged_page('fast');p.click('#logged-submit');p.clock.run_for(8000)
  assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Logged-in thread UI handles a reply completed within the submit event',logged_fast)
 def logged_enter():
  p=logged_page('fast');p.locator('[data-app-shell-active-page="true"] [data-composer-markdown]').press('Enter')
  p.clock.run_for(8000);assert completions(p)==1;p.close()
 check('Logged-in thread UI supports Enter in the contenteditable composer',logged_enter)
 def logged_svg():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate("""() => {
   loggedFixture.bodyOf(loggedFixture.latestTurn()).innerHTML='<svg width="280" height="160"><path d="M 20 120 L 140 20 L 260 120 Z" fill="teal"/></svg>';
  }""");p.clock.run_for(8000);assert completions(p)==0
  p.evaluate('loggedFinish({preserve:true})');p.clock.run_for(7500);s=status(p)
  assert s['visualOnly'] is True and s['finalControls'] is True,s
  assert completions(p)==1;p.close()
 check('Logged-in thread UI SVG-only reply uses its completed turn and action controls',logged_svg)
 def logged_iframe():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate("""() => {
   const response=loggedFixture.latestTurn().querySelector('[data-response-body]');
   const frame=document.createElement('iframe');frame.width='280';frame.height='160';
   frame.srcdoc='<html><body><svg width="250" height="130"><circle cx="100" cy="60" r="40" fill="teal"/></svg></body></html>';
   response.after(frame);loggedFinish({preserve:true});
  }""");p.clock.run_for(7500);s=status(p)
  assert s['visualOnly'] is True and s['hasOutput'] is True,s
  assert completions(p)==1;p.close()
 check('Logged-in thread UI recognizes an iframe beside the response body',logged_iframe)
 def logged_late_completion():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate('loggedFinish({mark:false})');p.clock.run_for(12000);s=status(p)
  assert s['busy'] is False and s['finalControls'] is True and s['hasOutput'] is True,s
  assert s['completionRequired'] is True and s['completionMarked'] is False,s
  assert s['phase']=='waiting' and completions(p)==0,s
  p.evaluate("loggedFixture.stateOf(loggedFixture.latestTurn()).setAttribute('data-talvt-turn-state','complete')")
  p.clock.run_for(4000);assert completions(p)==0
  p.clock.run_for(3500);assert completions(p)==1;p.close()
 check('Logged-in thread UI waits for a late explicit complete state',logged_late_completion)
 def logged_long_pending_without_stop():
  p=logged_page('no-stop');p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate("loggedToken('Long pending fixture response without a visible Stop control')")
  p.clock.run_for(130000);s=status(p)
  assert s['busy'] is False and s['sawBusy'] is False,s
  assert s['active'] is True and s['phase']=='waiting' and s['completionMarked'] is False,s
  assert completions(p)==0
  p.evaluate('loggedFinish()');p.clock.run_for(7500);assert completions(p)==1;p.close()
 check('Logged-in thread UI keeps a reply pending beyond two minutes without a Stop control',logged_long_pending_without_stop)
 def logged_pending_turn_virtualization():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate("loggedToken('Pending answer before virtual scrolling')");p.clock.run_for(500)
  assert status(p)['active'] is True
  p.evaluate("""() => {
   window.loggedPendingTurn=loggedFixture.latestTurn();
   const historical=loggedFixture.transcript.firstElementChild.cloneNode(true);
   document.getElementById('logged-stop').remove();
   document.getElementById('logged-submit').hidden=false;
   loggedFixture.transcript.replaceChildren(historical);
  }""");p.clock.run_for(10000);s=status(p)
  assert s['busy'] is False and s['completionMarked'] is True,s
  assert s['active'] is True and completions(p)==0,s
  p.evaluate("""() => {
   loggedFixture.transcript.append(window.loggedPendingTurn);
   delete window.loggedPendingTurn;loggedFinish();
  }""");p.clock.run_for(7500);assert completions(p)==1
  p.clock.run_for(10000);assert completions(p)==1;p.close()
 check('Logged-in thread UI pins a pending answer while historical turns replace the visible DOM',logged_pending_turn_virtualization)
 def logged_lost_completion():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500);p.evaluate('loggedFinish()')
  p.clock.run_for(4000);assert completions(p)==0
  p.evaluate("loggedFixture.stateOf(loggedFixture.latestTurn()).removeAttribute('data-talvt-turn-state')")
  p.clock.run_for(4000);assert completions(p)==0;assert status(p)['phase']=='waiting'
  p.evaluate("loggedFixture.stateOf(loggedFixture.latestTurn()).setAttribute('data-talvt-turn-state','complete')")
  p.clock.run_for(4000);assert completions(p)==0
  p.clock.run_for(3500);assert completions(p)==1;p.close()
 check('Logged-in thread UI restarts settling when the complete state disappears',logged_lost_completion)
 def logged_actions_only():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate('loggedFinish({preserve:true})');p.clock.run_for(15000);s=status(p)
  assert s['finalControls'] is True and s['completionMarked'] is True,s
  assert s['hasOutput'] is False and s['phase']=='waiting',s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI does not notify for only headings and action buttons',logged_actions_only)
 def logged_stopped():
  p=logged_page();p.click('#logged-submit');p.clock.run_for(500)
  p.evaluate("loggedToken('Partial logged-in fixture answer')");p.click('#logged-stop')
  p.clock.run_for(15000);s=status(p)
  assert s['lastEvent']=='manual-stop' and s['completionMarked'] is True,s
  assert completions(p)==0;p.close()
 check('Logged-in thread UI preserves manual-stop suppression through the known label fallback',logged_stopped)
 def popup_page(content_status=None):
  p=context.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
  html=(ROOT/'popup.html').read_text(encoding='utf-8')
  html=re.sub(r'<script src="[^"]+"></script>','',html)
  html=html.replace('<link rel="stylesheet" href="popup.css">','<style>'+(ROOT/'popup.css').read_text()+'</style>')
  icon=base64.b64encode((ROOT/'assets/icon48.png').read_bytes()).decode()
  html=html.replace('assets/icon48.png','data:image/png;base64,'+icon)
  p.set_content(html);p.evaluate(MOCK)
  if content_status is not None:p.evaluate('(value)=>{chrome.tabs.sendMessage=async()=>value}',content_status)
  inject(p,'shared.js');inject(p,'popup.js');p.wait_for_timeout(150)
  return p,errors
 def popup():
  p,errors=popup_page()
  assert p.locator('#enabled').is_checked();assert p.locator('#tabStatus').inner_text()=='接続済み・待機中'
  p.click('#testNotification');p.wait_for_timeout(150);assert '成功' in p.locator('#testResult').inner_text()
  assert not errors,errors
  if args.screenshot:p.screenshot(path=args.screenshot,full_page=True)
  p.close()
 check('Popup layout, defaults and test-button wiring (mocked APIs)',popup)
 def popup_status(content_status,expected):
  p,errors=popup_page(content_status)
  assert p.locator('#tabStatus').inner_text()==expected
  assert not errors,errors;p.close()
 popup_cases=[
  ('Popup reports a missing composer instead of connected idle',
   {'ok':True,'phase':'idle','enabled':True,'composerFound':False},'ChatGPT の入力欄を検出できません'),
  ('Popup accepts a new conversation with no assistant message',
   {'ok':True,'phase':'idle','enabled':True,'composerFound':True,'assistantFound':False},'接続済み・待機中'),
  ('Popup preserves the disabled state when the composer is absent',
   {'ok':True,'phase':'disabled','enabled':False,'composerFound':False},'通知は一時停止中'),
  ('Popup prioritizes scan failure over a missing composer',
   {'ok':True,'phase':'idle','enabled':True,'composerFound':False,'scanError':True},'画面の読み取りを再試行中'),
  ('Popup tolerates older content diagnostics without composerFound',
   {'ok':True,'phase':'idle','enabled':True},'接続済み・待機中')
 ]
 for name,content_status,expected in popup_cases:
  check(name,lambda content_status=content_status,expected=expected:popup_status(content_status,expected))
 def popup_version():
  p,errors=popup_page();diagnostic=json.loads(p.locator('#diagnostics').text_content())
  assert diagnostic['extension']=='1.0.3';assert not errors,errors;p.close()
 check('Popup diagnostics reports the manifest version 1.0.3',popup_version)
 report={'browser':browser.version,'test_type':'Offline fixture with mock Chrome APIs; NO native extension installation, Windows banner, or logged-in ChatGPT verification','results':results}
 if args.report:Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 browser.close()
print(json.dumps({'passed':len(results),'failed':0}))
