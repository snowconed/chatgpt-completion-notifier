"use strict";
const audio = new Audio(chrome.runtime.getURL("assets/chime.wav"));
audio.preload = "auto";
let playing = Promise.resolve();
async function play(volume) {
  audio.pause();
  audio.currentTime = 0;
  audio.volume = Math.max(0, Math.min(1, Number(volume) || 0));
  await audio.play();
  return { ok: true };
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || message?.target !== "offscreen" || message.type !== "play") return false;
  playing = playing.catch(() => {}).then(() => play(message.volume));
  playing.then(respond, error => respond({ ok: false, error: String(error.message || error).slice(0, 180) }));
  return true;
});
