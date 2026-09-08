"use strict";
const $ = id => document.getElementById(id);
const BOOL_IDS = ["enabled", "notifyWhenFocused", "sound", "keepVisible"];
const PHASES = {
  idle: ["接続済み・待機中", "このタブで次に生成する回答を監視します。"],
  waiting: ["応答の開始／出力を確認中", "生成の開始、または終了を示す画面表示を待っています。"],
  generating: ["回答を生成中", "生成中の表示を検出しています。"],
  settling: ["終了を確認中", "回答の更新が止まったことを確認してから通知します。"],
  complete: ["回答の終了を検知", "次の回答も自動で監視します。"],
  cancelled: ["停止操作を検出", "手動停止した回答には完了通知を出しません。"],
  disabled: ["通知は一時停止中", "「通知を有効にする」で再開できます。"],
  "no-signal": ["生成を確認できませんでした", "送信が成功したか、ChatGPT の画面を確認してください。"],
  error: ["エラー表示を検出", "完了通知は出さずに停止しました。ChatGPT の画面を確認してください。"]
};
let tabId;
let contentStatus = null;
let prefs = CGN.settings();
let saving = Promise.resolve();
let refreshing = false;
function readForm() {
  const value = {};
  for (const key of BOOL_IDS) value[key] = $(key).checked;
  value.volume = Number($("volume").value) / 100;
  value.settleMs = Number($("settleMs").value);
  return CGN.settings(value);
}
function fillForm() {
  for (const key of BOOL_IDS) $(key).checked = prefs[key];
  $("volume").value = String(Math.round(prefs.volume * 100));
  $("volumeValue").textContent = `${Math.round(prefs.volume * 100)}%`;
  $("settleMs").value = String(prefs.settleMs);
}
function save() {
  prefs = readForm();
  const pending = { ...prefs };
  saving = saving.catch(() => {}).then(() => chrome.storage.local.set({ settings: pending }));
  saving.then(() => { $("saved").textContent = "保存しました。"; }, () => { $("saved").textContent = "保存できませんでした。拡張機能を開き直してください。"; });
}
async function request(message) {
  return chrome.runtime.sendMessage({ target: "background", ...message });
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    tabId = CGN.safeChatUrl(tab?.url) ? tab.id : undefined;
    if (tabId !== undefined) {
      try {
        contentStatus = await chrome.tabs.sendMessage(tabId, { target: "content", type: "get-status" });
        const [title, hint] = PHASES[contentStatus?.phase] || ["状態を確認できません", "ChatGPT のタブを再読み込みしてください。"];
        $("tabStatus").textContent = title; $("tabHint").textContent = hint;
      } catch {
        contentStatus = { connected: false };
        $("tabStatus").textContent = "ChatGPT の再読み込みが必要です";
        $("tabHint").textContent = "拡張機能を入れた後に、このタブを F5 で再読み込みしてください。";
      }
    } else {
      contentStatus = null;
      $("tabStatus").textContent = "ChatGPT 以外のタブです";
      $("tabHint").textContent = "ChatGPT のタブでこの画面を開くと、監視状態を確認できます。通知テストはここでも使えます。";
    }
    const diagnostic = await request({ type: "diagnostics" });
    $("permission").textContent = diagnostic?.permission === "granted"
      ? "拡張の通知権限：許可（Windows 側は別設定）" : "拡張の通知権限：拒否／取得できませんでした";
    $("diagnostics").textContent = JSON.stringify({
      extension: "1.0.0", settings: prefs, currentTab: contentStatus,
      notificationPermission: diagnostic?.permission, recent: diagnostic?.recent || []
    }, null, 2);
  } catch (error) {
    $("permission").textContent = `状態取得エラー：${String(error.message || error)}`;
  } finally { refreshing = false; }
}
function showResult(text, error = false) {
  $("testResult").textContent = text;
  $("testResult").classList.toggle("error", error);
}
async function runTest(type, button) {
  button.disabled = true;
  try {
    await saving;
    const result = await request({ type, tabId });
    if (type === "test-sound") {
      showResult(result?.ok ? (result.muted ? "音量が 0% です。音量を上げて再試行してください。" : "音声再生を開始しました。聞こえない場合は Windows の音量ミキサーを確認してください。")
        : `音声再生に失敗しました：${result?.error || "不明なエラー"}`, !result?.ok);
    } else if (result?.ok) {
      showResult("通知 API への送信：成功。\n表示されない場合は Windows の Chrome 通知・応答不可を確認してください。"
        + (result.sound === "failed" ? `\nチャイムの再生に失敗しました：${result.soundError}` : ""), result.sound === "failed");
    } else {
      showResult(result?.result === "permission-denied" ? "拡張機能の通知が許可されていません。Chrome の拡張機能と Windows の通知設定を確認してください。"
        : `通知を送信できませんでした：${result?.error || result?.result || "不明なエラー"}`, true);
    }
    await refresh();
  } catch (error) { showResult(`エラー：${String(error.message || error)}`, true); }
  finally { button.disabled = false; }
}
for (const key of [...BOOL_IDS, "settleMs"]) $(key).addEventListener("change", save);
$("volume").addEventListener("input", () => { $("volumeValue").textContent = `${$("volume").value}%`; });
$("volume").addEventListener("change", save);
$("testNotification").addEventListener("click", event => { void runTest("test-notification", event.currentTarget); });
$("testSound").addEventListener("click", event => { void runTest("test-sound", event.currentTarget); });
$("clearLog").addEventListener("click", async () => {
  try { await request({ type: "clear-log" }); await refresh(); }
  catch (error) { showResult(String(error.message || error), true); }
});
$("openGuide").addEventListener("click", () => {
  void chrome.tabs.create({ url: chrome.runtime.getURL("guide.html") });
});
async function start() {
  try { prefs = CGN.settings((await chrome.storage.local.get("settings")).settings); }
  catch { showResult("設定を読み込めなかったため標準設定を表示しています。", true); }
  fillForm();
  await refresh();
  setInterval(refresh, 2000);
}
void start();
