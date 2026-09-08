"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const vm=require("node:vm");
const fs=require("node:fs");
const path=require("node:path");
const {webcrypto}=require("node:crypto");
const ROOT=path.resolve(__dirname,"..");
const clone=x=>structuredClone(x);
const event=()=>({listeners:[],addListener(fn){this.listeners.push(fn);}});
function storageArea(backing) {
  return {
    async get(key){if(key===null)return clone(backing);if(typeof key==="string")return {[key]:clone(backing[key])};return {};},
    async set(value){Object.assign(backing,clone(value));},
    async remove(key){delete backing[key];},async setAccessLevel(){}
  };
}
function harness(options={}) {
  const local=options.local||{settings:{sound:false,...options.settings}};
  const session=options.session||{};
  const calls={notifications:[],badges:[],focus:[],tabs:[],sound:0};
  const tabs=new Map([[10,{id:10,windowId:1,active:true,url:"https://chatgpt.com/c/a"}], [11,{id:11,windowId:1,active:false,url:"https://chatgpt.com/c/b"}]]);
  const windows=new Map([[1,{id:1,focused:true,state:options.minimized?"minimized":"normal"}]]);
  const chrome={
    storage:{local:storageArea(local),session:storageArea(session)},
    runtime:{id:"test-extension",getURL:p=>`chrome-extension://test-extension/${p}`,onMessage:event(),onInstalled:event(),
      async getContexts(){return [{contextType:"OFFSCREEN_DOCUMENT"}];},
      async sendMessage(){calls.sound++;return options.soundFailure?{ok:false,error:"audio failed"}:{ok:true};}},
    offscreen:{async createDocument(){}},
    notifications:{onClicked:event(),onClosed:event(),
      async getPermissionLevel(){return options.denied?"denied":"granted";},
      async create(id,value){if(options.notificationFailure)throw Error("simulated notification failure");calls.notifications.push({id,...value});return id;},
      async clear(){return true;}},
    action:{async setBadgeBackgroundColor(){},async setBadgeText(v){calls.badges.push(v);}},
    windows:{async get(id){if(!windows.has(id))throw Error("closed window");return clone(windows.get(id));},async update(id,value){calls.focus.push({id,...value});Object.assign(windows.get(id),value);}},
    tabs:{onRemoved:event(),async get(id){if(!tabs.has(id))throw Error("closed tab");return clone(tabs.get(id));},
      async update(id,value){calls.tabs.push({kind:"update",id,...value});Object.assign(tabs.get(id),value);return clone(tabs.get(id));},
      async create(value){const tab={id:20+calls.tabs.length,windowId:1,...value};calls.tabs.push({kind:"create",...tab});tabs.set(tab.id,tab);return tab;}}
  };
  const context=vm.createContext({chrome,console:{warn(){}},URL,Date,crypto:webcrypto});
  context.importScripts=(file)=>vm.runInContext(fs.readFileSync(path.join(ROOT,file),"utf8"),context,{filename:file});
  vm.runInContext(fs.readFileSync(path.join(ROOT,"background.js"),"utf8"),context,{filename:"background.js"});
  const sender=(id=10)=>({id:chrome.runtime.id,frameId:0,url:tabs.get(id)?.url||"https://chatgpt.com/c/a",tab:tabs.get(id)||{id}});
  const popup={id:chrome.runtime.id,url:chrome.runtime.getURL("popup.html")};
  function message(data,from=sender()) {
    return new Promise((resolve,reject)=>{
      const accepted=chrome.runtime.onMessage.listeners[0]({target:"background",...data},from,resolve);
      if(!accepted)reject(Error("message not handled"));
    });
  }
  async function click(id){for(const fn of chrome.notifications.onClicked.listeners)fn(id);await vm.runInContext("queue",context);}
  return {local,session,calls,tabs,windows,chrome,message,sender,popup,click};
}
const complete=(eventId="doc:1")=>({type:"complete",eventId,url:"https://chatgpt.com/c/a"});

test("completion calls the native notification API without conversation content",async()=>{
  const h=harness();const r=await h.message({...complete(),text:"SECRET",title:"PRIVATE"});assert.equal(r.ok,true);assert.equal(h.calls.notifications.length,1);
  assert.ok(h.calls.notifications[0].title.includes("終了"));assert.ok(!JSON.stringify(h.calls).includes("SECRET"));assert.ok(!JSON.stringify(h.session).includes("PRIVATE"));
});
test("repeated event delivery is deduplicated",async()=>{
  const h=harness();await Promise.all([h.message(complete()),h.message(complete())]);assert.equal(h.calls.notifications.length,1);
});
test("simultaneous events from separate tabs retain both click targets",async()=>{
  const h=harness();await Promise.all([h.message(complete()),h.message({...complete(),url:"https://chatgpt.com/c/b"},h.sender(11))]);
  assert.equal(h.calls.notifications.length,2);assert.equal(Object.keys(h.session.notificationState.targets).length,2);
});
test("foreground suppression is optional",async()=>{
  const h=harness({settings:{notifyWhenFocused:false}});const r=await h.message(complete());assert.equal(r.result,"suppressed-focused");assert.equal(h.calls.notifications.length,0);
});
test("a minimized window is treated as background",async()=>{
  const h=harness({settings:{notifyWhenFocused:false},minimized:true});assert.equal((await h.message(complete())).ok,true);assert.equal(h.calls.notifications.length,1);
});
test("disabled monitoring suppresses automatic, but not manual test notifications",async()=>{
  const h=harness({settings:{enabled:false}});assert.equal((await h.message(complete())).result,"disabled");
  assert.equal((await h.message({type:"test-notification"},h.popup)).ok,true);assert.equal(h.calls.notifications.length,1);
});
test("denied notification permission can still use explicitly enabled audio",async()=>{
  const h=harness({denied:true,settings:{sound:true}});const r=await h.message(complete());assert.equal(r.ok,false);assert.equal(r.result,"permission-denied");assert.equal(h.calls.sound,1);
});
test("notification API errors are reported, not silently treated as success",async()=>{
  const h=harness({notificationFailure:true});const r=await h.message(complete());assert.equal(r.ok,false);assert.equal(r.result,"notification-error");assert.equal(Object.keys(h.session.notificationState.targets).length,0);
});
test("audio failure does not suppress a desktop notification",async()=>{
  const h=harness({settings:{sound:true},soundFailure:true});const r=await h.message(complete());assert.equal(r.ok,true);assert.equal(r.sound,"failed");assert.equal(h.calls.notifications.length,1);
});
test("non-ChatGPT senders and subframes are rejected",async()=>{
  const h=harness();const malicious={...h.sender(),url:"https://untrusted.example/"};assert.equal((await h.message(complete(),malicious)).ok,false);
  assert.equal((await h.message(complete(),{...h.sender(),frameId:1})).ok,false);assert.equal(h.calls.notifications.length,0);
});
test("clicking a notification focuses the original chat",async()=>{
  const h=harness();const r=await h.message(complete());await h.click(r.notificationId);
  assert.ok(h.calls.tabs.some(v=>v.kind==="update"&&v.id===10&&v.active));assert.equal(h.calls.focus[0].id,1);
});
test("click metadata survives service worker recreation",async()=>{
  const h=harness();const r=await h.message(complete());const revived=harness({local:h.local,session:h.session});await revived.click(r.notificationId);
  assert.ok(revived.calls.tabs.some(v=>v.kind==="update"&&v.id===10));
});
test("click after navigation opens the saved conversation without replacing current tab",async()=>{
  const h=harness();const r=await h.message(complete());h.tabs.get(10).url="https://chatgpt.com/c/different";await h.click(r.notificationId);
  assert.ok(h.calls.tabs.some(v=>v.kind==="create"&&v.url==="https://chatgpt.com/c/a"));assert.equal(h.tabs.get(10).url,"https://chatgpt.com/c/different");
});
test("click after tab closure can reopen the saved conversation",async()=>{
  const h=harness();const r=await h.message(complete());h.tabs.delete(10);await h.click(r.notificationId);
  assert.ok(h.calls.tabs.some(v=>v.kind==="create"&&v.url==="https://chatgpt.com/c/a"));
});
test("stored navigation URLs drop query strings",async()=>{
  const h=harness();await h.message({...complete(),url:"https://chatgpt.com/c/a?private=value#x"});
  assert.ok(!JSON.stringify(h.session).includes("private=value"));
});
