"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { CompletionDetector } = require("../detector-core.js");
const { settings, safeChatUrl } = require("../shared.js");
const base = (patch = {}) => ({
  route: "/c/one", userKey: "u1", assistantKey: "a1", signature: "old-answer",
  hasOutput: true, afterUser: true, busy: false, composerReady: true,
  finalControls: true, error: false, ...patch
});
const completes = events => events.filter(e => e.type === "complete");
function fresh(options) {
  const d = new CompletionDetector(options); d.tick(base(), 0); d.tick(base(), 2000); return d;
}
function stream(d, at = 3000) {
  d.submit(base(), at);
  return base({ userKey: "u2", assistantKey: "a2", signature: "new-answer", busy: true, composerReady: false, finalControls: false });
}
function done(s) { return { ...s, busy: false, composerReady: true, finalControls: true }; }

test("old completed conversations never notify merely on load", () => {
  const d = fresh(); for (const t of [3000,10000,600000]) assert.equal(completes(d.tick(base(),t)).length,0);
});
test("normal streaming ends once, after the quiet period", () => {
  const d = fresh(); const s = stream(d);
  d.tick(s,3100); d.tick(s,20000);
  assert.equal(completes(d.tick(done(s),21000)).length,0);
  assert.equal(completes(d.tick(done(s),25999)).length,0);
  assert.equal(completes(d.tick(done(s),26000)).length,1);
  assert.equal(completes(d.tick(done(s),40000)).length,0);
});
test("long thinking with no text updates does not complete", () => {
  const d=fresh(); const s=stream(d);
  for (const t of [3100,30000,900000,3600000]) assert.equal(completes(d.tick(s,t)).length,0);
  assert.equal(d.phase,"generating");
});
test("transient loss of stop button resets its quiet period on return", () => {
  const d=fresh(); const s=stream(d); d.tick(s,3100); d.tick(done(s),4000); d.tick(s,6000); d.tick(done(s),10000);
  assert.equal(completes(d.tick(done(s),14999)).length,0);
  assert.equal(completes(d.tick(done(s),15000)).length,1);
});
test("late text updates postpone completion", () => {
  const d=fresh(); const s=stream(d); d.tick(s,3100); d.tick(done(s),4000);
  const late={...done(s),signature:"last tokens"}; d.tick(late,8000);
  assert.equal(completes(d.tick(late,9000)).length,0);
  assert.equal(completes(d.tick(late,13000)).length,1);
});
test("manual stop is suppressed, including busy marker remnants", () => {
  const d=fresh(); const s=stream(d); d.tick(s,3100); d.cancel(3500);
  for (const [s2,t] of [[s,4000],[done(s),6000],[done(s),14000],[done(s),30000]]) assert.equal(completes(d.tick(s2,t)).length,0);
});
test("a fresh submit after manual stop can notify", () => {
  const d=fresh(); const s=stream(d); d.tick(s,3100); d.cancel(3500);
  const old=done(s);d.submit(old,4000);
  const newer={...s,assistantKey:"a3",userKey:"u3",signature:"third"};d.tick(newer,4100);d.tick(done(newer),5000);
  assert.equal(completes(d.tick(done(newer),10000)).length,1);
});
test("navigation to another completed chat cancels pending completion", () => {
  const d=fresh();const s=stream(d);d.tick(s,3100);d.tick(done(s),4000);
  const other=base({route:"/c/other",userKey:"u9",assistantKey:"a9",signature:"other"});
  assert.equal(completes(d.tick(other,4500)).length,0);
  assert.equal(completes(d.tick(other,20000)).length,0);
});
test("first submit preserves a new conversation URL even in one DOM update", () => {
  const d=new CompletionDetector(); const empty=base({route:"/",userKey:"",assistantKey:"",signature:"",hasOutput:false});
  d.tick(empty,0);d.submit(empty,2000);
  const fast=base({route:"/c/new",userKey:"new-u",assistantKey:"new-a",signature:"fast"});
  d.tick(fast,2100);assert.equal(completes(d.tick(fast,7100)).length,1);
});
test("explicit navigation cannot use the new-URL assignment exception", () => {
  const d=new CompletionDetector();const empty=base({route:"/",userKey:"",hasOutput:false});
  d.tick(empty,0);d.submit(empty,2000);d.navigate(2050);
  const old=base({route:"/c/old"});d.tick(old,2100);
  assert.equal(completes(d.tick(old,20000)).length,0);
});
test("fast output without a sampled stop button uses final controls", () => {
  const d=fresh();d.submit(base(),3000);const fast=base({userKey:"u2",assistantKey:"a2",signature:"fast"});
  d.tick(fast,3100);assert.equal(completes(d.tick(fast,8100)).length,1);
});
test("text stability alone cannot complete a run without busy or final controls", () => {
  const d=fresh();d.submit(base(),3000);const s=base({signature:"new",finalControls:false});d.tick(s,3100);
  assert.equal(completes(d.tick(s,60000)).length,0);
});
test("the reported empty-output diagnostic stays waiting despite final controls", () => {
  const d=fresh();const s={...stream(d),hasOutput:false,signature:"empty-answer"};d.tick(s,3100);
  const diagnostic={...done(s),assistantFound:true,stopDetected:false,streamingDetected:false};
  for (const at of [4000,9000,20000,60000]) {
    assert.equal(completes(d.tick(diagnostic,at)).length,0);
    assert.equal(d.phase,"waiting");
    assert.equal(d.status().active,true);
  }
});
test("a visual-only reply waits five seconds after late final controls and emits once", () => {
  const d=fresh();const s={...stream(d),visualOnly:true};d.tick(s,3100);
  const waiting={...done(s),finalControls:false};
  for (const at of [4000,10000]) {
    assert.equal(completes(d.tick(waiting,at)).length,0);
    assert.equal(d.phase,"waiting");
  }
  const ready=done(s);
  assert.equal(completes(d.tick(ready,13000)).length,0);
  assert.equal(d.phase,"settling");
  assert.equal(completes(d.tick(ready,17999)).length,0);
  assert.equal(completes(d.tick(ready,18000)).length,1);
  assert.equal(completes(d.tick(ready,40000)).length,0);
});
test("a visual-only reply requires the composer as well as final controls", () => {
  const d=fresh();const s={...stream(d),visualOnly:true};d.tick(s,3100);
  const waiting={...done(s),composerReady:false};
  for (const at of [4000,10000]) {
    assert.equal(completes(d.tick(waiting,at)).length,0);
    assert.equal(d.phase,"waiting");
  }
  d.tick(done(s),12000);
  assert.equal(completes(d.tick(done(s),16999)).length,0);
  assert.equal(completes(d.tick(done(s),17000)).length,1);
});
test("temporary loss of visual readiness restarts the full settling interval", () => {
  const d=fresh();const s={...stream(d),visualOnly:true};d.tick(s,3100);
  const ready=done(s);d.tick(ready,4000);assert.equal(d.phase,"settling");
  assert.equal(completes(d.tick({...ready,finalControls:false},8000)).length,0);
  assert.equal(d.phase,"waiting");
  assert.equal(completes(d.tick(ready,10000)).length,0);
  assert.equal(d.phase,"settling");
  assert.equal(completes(d.tick(ready,14999)).length,0);
  assert.equal(completes(d.tick(ready,15000)).length,1);
  assert.equal(completes(d.tick(ready,25000)).length,0);
});
test("visible error ends the run without a success notification", () => {
  const d=fresh();const s=stream(d);d.tick(s,3100);
  assert.equal(completes(d.tick({...done(s),error:true},4000)).length,0);assert.equal(d.phase,"error");
});
test("disabled detector neither starts nor completes", () => {
  const d=fresh({enabled:false});const s=stream(d);d.tick(s,3100);d.tick(done(s),4000);
  assert.equal(completes(d.tick(done(s),20000)).length,0);assert.equal(d.phase,"disabled");
});
test("disabling an active run discards it", () => {
  const d=fresh();const s=stream(d);d.tick(s,3100);d.configure({enabled:false},3200);d.tick(done(s),4000);
  assert.equal(completes(d.tick(done(s),20000)).length,0);
});
test("output must belong after the newest user message", () => {
  const d=fresh();const s=stream(d);d.tick(s,3100);
  const old={...done(s),afterUser:false};d.tick(old,4000);
  assert.equal(completes(d.tick(old,20000)).length,0);
});
test("no-output timeout is not completion", () => {
  const d=fresh();d.submit(base(),3000);
  const s=base({hasOutput:false,afterUser:false});d.tick(s,3100);
  assert.equal(completes(d.tick(s,124000)).length,0);assert.equal(d.phase,"no-signal");
});
test("a 12-second settling preference is honored", () => {
  const d=fresh({settleMs:12000});const s=stream(d);d.tick(s,3100);d.tick(done(s),4000);
  assert.equal(completes(d.tick(done(s),15999)).length,0);
  assert.equal(completes(d.tick(done(s),16000)).length,1);
});
test("an already-streaming page can be adopted on first attachment", () => {
  const d=new CompletionDetector();const s=base({busy:true,composerReady:false});d.tick(s,0);
  d.tick(done(s),3000);assert.equal(completes(d.tick(done(s),8000)).length,1);
});
test("newly observed user messages can arm the conservative fallback", () => {
  const d=fresh();const s=base({userKey:"u2",assistantKey:"a2",signature:"new"});d.tick(s,3000);
  assert.equal(completes(d.tick(s,8000)).length,1);
});
test("settings are bounded and reject non-boolean values", () => {
  assert.deepEqual(settings({volume:12,enabled:"yes",settleMs:1}).volume,1);
  assert.equal(settings({enabled:"false"}).enabled,true);
  assert.equal(settings({settleMs:1}).settleMs,5000);
  assert.equal(settings({volume:NaN}).volume,0.5);
});
test("navigation targets are https-only, exact-host, credential-free and query-free", () => {
  for(const s of ["javascript:alert(1)","https://chatgpt.com.evil.test/c/a","http://chatgpt.com/","https://user:secret@chatgpt.com/","https://chatgpt.com:9999/","file:///tmp/a"])assert.equal(safeChatUrl(s),null);
  assert.equal(safeChatUrl("https://chatgpt.com/c/a?secret=1#abc"),"https://chatgpt.com/c/a");
});
