/* Manifest V3 service worker. Settings are local; click targets/logs are session-only. */
"use strict";
importScripts("shared.js");
const { settings: normalizeSettings, safeChatUrl } = CGN;
const STATE_KEY = "notificationState";
let queue = Promise.resolve();
let offscreenCreating = null;
function enqueue(job) {
  const result = queue.then(job);
  queue = result.catch(error => console.warn("CGN:", error?.message || "operation failed"));
  return result;
}
async function prefs() {
  return normalizeSettings((await chrome.storage.local.get("settings")).settings);
}
async function state() {
  const saved = (await chrome.storage.session.get(STATE_KEY))[STATE_KEY] || {};
  return { events: saved.events || [], targets: saved.targets || {}, log: saved.log || [] };
}
async function saveState(s) {
  s.events = s.events.slice(-200);
  s.log = s.log.slice(-20);
  const alive = Object.entries(s.targets).filter(([, target]) => Date.now() - target.at < 86400000);
  s.targets = Object.fromEntries(alive.slice(-100));
  await chrome.storage.session.set({ [STATE_KEY]: s });
}
function errorText(error) { return String(error?.message || error || "unknown error").slice(0, 180); }
async function badge(tabId, text, color = "#155B4E") {
  if (!Number.isInteger(tabId)) return;
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color });
    await chrome.action.setBadgeText({ tabId, text });
  } catch { /* The tab may have closed. */ }
}
async function ensureOffscreen() {
  if (offscreenCreating) return offscreenCreating;
  offscreenCreating = (async () => {
    const contexts = await chrome.runtime.getContexts({
      contextTypes: ["OFFSCREEN_DOCUMENT"], documentUrls: [chrome.runtime.getURL("offscreen.html")]
    });
    if (!contexts.length) {
      await chrome.offscreen.createDocument({
        url: "offscreen.html", reasons: ["AUDIO_PLAYBACK"],
        justification: "ユーザーが有効にした、回答終了時の短い通知音をローカルで再生します。"
      });
    }
  })();
  try { await offscreenCreating; } finally { offscreenCreating = null; }
}
async function chime(volume) {
  if (volume <= 0) return { ok: true, muted: true };
  // AUDIO_PLAYBACK documents are automatically closed after an idle period.
  // A document may close between getContexts and sendMessage, so retry once.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      await ensureOffscreen();
      const reply = await chrome.runtime.sendMessage({ target: "offscreen", type: "play", volume });
      if (!reply?.ok) throw new Error(reply?.error || "音声再生を開始できませんでした");
      return { ok: true };
    } catch (error) {
      if (attempt === 1) return { ok: false, error: errorText(error) };
    }
  }
}
async function targetFor(tabId, suppliedUrl) {
  const url = safeChatUrl(suppliedUrl);
  if (!Number.isInteger(tabId)) return url ? { url, at: Date.now() } : null;
  try {
    const tab = await chrome.tabs.get(tabId);
    return { tabId, windowId: tab.windowId, url: url || safeChatUrl(tab.url), at: Date.now() };
  } catch { return url ? { url, at: Date.now() } : null; }
}
async function isFrontmost(tabId) {
  try {
    const tab = await chrome.tabs.get(tabId);
    if (!tab.active) return false;
    const win = await chrome.windows.get(tab.windowId);
    return win.focused && win.state !== "minimized";
  } catch { return false; }
}
async function deliver({ test = false, tabId, url, eventId } = {}) {
  const p = await prefs();
  const s = await state();
  const unique = `${tabId}:${eventId}`;
  if (!test && s.events.includes(unique)) return { ok: true, result: "duplicate" };
  if (!test) s.events.push(unique);
  if (!test && (!p.enabled || (!p.notifyWhenFocused && await isFrontmost(tabId)))) {
    const result = p.enabled ? "suppressed-focused" : "disabled";
    s.log.push({ at: Date.now(), kind: "complete", result });
    await saveState(s);
    await badge(tabId, p.enabled ? "✓" : "");
    return { ok: true, result };
  }
  const record = { at: Date.now(), kind: test ? "test" : "complete", result: "sent", sound: "off" };
  let notificationId = null;
  let soundReply = null;
  // Audio is independent of OS banner delivery. Its failure never prevents a toast.
  const soundPromise = p.sound ? chime(p.volume) : Promise.resolve(null);
  try {
    const permission = await chrome.notifications.getPermissionLevel();
    if (permission !== "granted") {
      record.result = "permission-denied";
    } else {
      notificationId = `cgn-${crypto.randomUUID()}`;
      const target = await targetFor(tabId, url);
      if (target) s.targets[notificationId] = target;
      await chrome.notifications.create(notificationId, {
        type: "basic", iconUrl: chrome.runtime.getURL("assets/icon128.png"),
        title: test ? "ChatGPT 完了通知：テスト" : "ChatGPT の回答が終了しました",
        message: test ? "これは拡張機能からのテスト通知です。" : "クリックしてタブを開き、回答を確認してください。",
        priority: 1, requireInteraction: p.keepVisible,
        // Use the bundled chime rather than an additional OS sound.
        silent: true
      });
    }
  } catch (error) {
    record.result = "notification-error";
    record.error = errorText(error);
    if (notificationId) delete s.targets[notificationId];
  }
  soundReply = await soundPromise;
  if (soundReply) {
    record.sound = soundReply.ok ? (soundReply.muted ? "muted" : "played") : "failed";
    if (!soundReply.ok) record.soundError = soundReply.error;
  }
  s.log.push(record);
  await saveState(s);
  await badge(tabId, record.result === "sent" ? "✓" : "!", record.result === "sent" ? "#155B4E" : "#9A421B");
  // 'sent' is acknowledgement from Chrome, NOT proof that Windows showed a banner.
  return { ok: record.result === "sent", ...record, notificationId };
}
async function focusTarget(id) {
  const s = await state();
  const target = s.targets[id];
  if (!target) return;
  let focused = false;
  if (Number.isInteger(target.tabId)) {
    try {
      const tab = await chrome.tabs.get(target.tabId);
      const currentUrl = safeChatUrl(tab.url);
      // Do not replace another conversation that the user has since opened.
      if (currentUrl && (!target.url || currentUrl === target.url)) {
        await chrome.tabs.update(tab.id, { active: true });
        const win = await chrome.windows.get(tab.windowId);
        await chrome.windows.update(tab.windowId, win.state === "minimized" ? { focused: true, state: "normal" } : { focused: true });
        await badge(tab.id, "");
        focused = true;
      }
    } catch { /* A closed/moved tab can be reopened from the saved session URL. */ }
  }
  if (!focused && safeChatUrl(target.url)) {
    const tab = await chrome.tabs.create({ url: target.url, active: true });
    await chrome.windows.update(tab.windowId, { focused: true });
  }
  await chrome.notifications.clear(id);
  delete s.targets[id];
  await saveState(s);
}
function isContentSender(sender) {
  return sender.id === chrome.runtime.id && Number.isInteger(sender.tab?.id)
    && sender.frameId === 0 && Boolean(safeChatUrl(sender.url));
}
function isPopupSender(sender) {
  return sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL("popup.html");
}
async function route(message, sender) {
  if (["complete", "status"].includes(message.type)) {
    if (!isContentSender(sender)) throw new Error("許可されていない送信元です");
    const tabId = sender.tab.id;
    if (message.type === "complete") {
      if (typeof message.eventId !== "string" || message.eventId.length > 100) throw new Error("不正なイベントIDです");
      const url = safeChatUrl(message.url) || safeChatUrl(sender.tab.url) || safeChatUrl(sender.url);
      return deliver({ tabId, url, eventId: message.eventId });
    }
    const phase = String(message.status?.phase || "idle");
    if (!["idle", "disabled", "waiting", "generating", "settling", "complete", "cancelled", "no-signal", "error"].includes(phase)) throw new Error("不正な状態です");
    await chrome.storage.session.set({ [`tab:${tabId}`]: { phase, at: Date.now() } });
    if (phase !== "complete") await badge(tabId, ["generating", "settling", "waiting"].includes(phase) ? "…" : phase === "error" ? "!" : "");
    return { ok: true };
  }
  if (!isPopupSender(sender)) throw new Error("拡張機能の画面から操作してください");
  if (message.type === "test-notification") {
    return deliver({ test: true, tabId: Number.isInteger(message.tabId) ? message.tabId : undefined });
  }
  if (message.type === "test-sound") {
    const p = await prefs();
    const reply = await chime(p.volume);
    const s = await state();
    s.log.push({ at: Date.now(), kind: "sound-test", result: reply.ok ? (reply.muted ? "muted" : "played") : "failed", ...(reply.error ? { error: reply.error } : {}) });
    await saveState(s);
    return reply;
  }
  if (message.type === "diagnostics") {
    const s = await state();
    return { ok: true, permission: await chrome.notifications.getPermissionLevel(), recent: s.log.slice(-8) };
  }
  if (message.type === "clear-log") {
    const s = await state(); s.log = []; await saveState(s); return { ok: true };
  }
  throw new Error("未対応の操作です");
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.target !== "background") return false;
  enqueue(() => route(message, sender)).then(respond, error => respond({ ok: false, error: errorText(error) }));
  return true; // Keep the MV3 message channel open for asynchronous work.
});
chrome.runtime.onInstalled.addListener(() => {
  void enqueue(async () => {
    // Prevent content scripts from reading session-only click targets.
    await chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" });
    const p = await prefs();
    await chrome.storage.local.set({ settings: p });
  });
});
chrome.notifications.onClicked.addListener(id => { void enqueue(() => focusTarget(id)); });
chrome.notifications.onClosed.addListener((id, byUser) => {
  if (byUser) void enqueue(async () => {
    const s = await state(); delete s.targets[id]; await saveState(s);
  });
});
chrome.tabs.onRemoved.addListener(tabId => {
  void chrome.storage.session.remove(`tab:${tabId}`).catch(() => {});
});
