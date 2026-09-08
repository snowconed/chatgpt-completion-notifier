/* Shared, dependency-free helpers. No remote requests or conversation storage. */
(() => {
  "use strict";
  const DEFAULTS = Object.freeze({
    enabled: true,
    notifyWhenFocused: true,
    sound: true,
    volume: 0.5,
    settleMs: 5000,
    keepVisible: false
  });
  function settings(value = {}) {
    const s = { ...DEFAULTS };
    for (const k of ["enabled", "notifyWhenFocused", "sound", "keepVisible"]) {
      if (typeof value?.[k] === "boolean") s[k] = value[k];
    }
    if (typeof value?.volume === "number" && Number.isFinite(value.volume)) {
      s.volume = Math.min(1, Math.max(0, value.volume));
    }
    if ([5000, 8000, 12000].includes(value?.settleMs)) s.settleMs = value.settleMs;
    return s;
  }
  function safeChatUrl(input) {
    try {
      const url = new URL(input);
      if (url.protocol !== "https:" || !["chatgpt.com", "chat.openai.com"].includes(url.hostname) || url.port || url.username || url.password) return null;
      // Keep only the origin/path for notification navigation; drop queries/fragments.
      return `${url.origin}${url.pathname}`;
    } catch { return null; }
  }
  function conversationKey(route) {
    return String(route).match(/(?:^|\/)c\/([^/?#]+)/)?.[1] || null;
  }
  const api = Object.freeze({ DEFAULTS, settings, safeChatUrl, conversationKey });
  globalThis.CGN = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})();
