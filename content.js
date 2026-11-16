/* Runs only in ChatGPT's top frame, in Chrome's isolated extension world. */
(() => {
  "use strict";
  if (globalThis.__cgnLoaded) return;
  globalThis.__cgnLoaded = true;
  const { settings: sanitizeSettings } = CGN;
  const VERSION = chrome.runtime.getManifest().version;
  const COMPOSER_SELECTOR = '#prompt-textarea,[data-testid="prompt-textarea"],textarea[name="prompt-textarea"],#mobile-composer-prompt,textarea[data-mobile-composer-prompt],form[data-chatgpt-composer] [data-composer-markdown][contenteditable]';
  const STOP_SELECTOR = 'button[data-testid="stop-button"],button[data-testid="stop-generation-button"],button[data-testid="stop-response-button"],button[data-stop-generating]';
  const SEND_SELECTOR = 'button[data-testid="send-button"],button[data-testid="composer-send-button"],button[data-composer-submit]:not([data-stop-generating])';
  const STREAM_SELECTOR = '.result-streaming,[data-is-streaming="true"],[data-is-generating="true"]';
  const CURRENT_STREAM_SELECTOR = '[data-assistant-markdown] [aria-busy="true"]';
  const STOP_LABEL = /^(?:stop(?: generating| generation| streaming| response)?|生成を停止|生成を中止|応答を停止|回答を停止|回答の生成を停止|停止する|停止)$/i;
  const SEND_LABEL = /^(?:send(?: prompt| message)?|送信|メッセージを送信(?:します)?|プロンプトを送信)$/i;
  const FINAL_LABEL = /^(?:copy(?: response| message)?|good response|bad response|read aloud|コピー|回答をコピー(?:する)?|メッセージをコピー|良い回答|悪い回答|読み上げる)$/i;
  const FINAL_VISUAL_LABEL = /^(?:copy (?:response|message)|good response|bad response|read aloud|回答をコピー(?:する)?|メッセージをコピー|良い回答|悪い回答|読み上げる)$/i;
  const THREAD_FINAL_LABEL = /^(?:copy(?: response| message)?|read aloud|コピーする|読み上げ)$/i;
  const REGEN_LABEL = /^(?:regenerate(?: response)?|try again|再生成|回答を再生成|もう一度試す)$/i;
  const TURN_SELECTOR = 'article,[data-testid^="conversation-turn-"],[data-message-role],[data-chatgpt-search-unit-key]';
  const NON_OUTPUT_SELECTOR = 'button,[role="button"],script,style,template,[hidden],[aria-hidden="true"],[data-message-attribution],[data-message-actions],[data-conversation-role],[data-markdown-copy="exclude"]';
  const emptyScope = document.createDocumentFragment();
  let prefs = sanitizeSettings();
  const detector = new CgnCompletionDetector(prefs);
  const documentId = crypto.randomUUID();
  let stopped = false;
  let scheduled = null;
  let heartbeat = null;
  let lastSentPhase = "";
  let lastStatus = {};
  let lastEvent = "loaded";
  let lastSubmitAt = -Infinity;
  const nodeIds = new WeakMap();
  let nodeSequence = 0;
  const observer = new MutationObserver(() => schedule(250));

  function visible(el) {
    if (!el || el.closest('[hidden],[aria-hidden="true"],[data-app-shell-active-page="false"]')) return false;
    if (!el.getClientRects().length) return false;
    const style = getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden";
  }
  function labelled(el, pattern) {
    return [el?.getAttribute("aria-label"), el?.getAttribute("title"), el?.getAttribute("data-tooltip")]
      .some(value => value && pattern.test(value.trim()));
  }
  function nodeKey(el) {
    if (!el) return "";
    const unit = el.getAttribute("data-chatgpt-search-unit-key");
    if (unit) return `${el.closest('[data-turn-key]')?.getAttribute('data-turn-key') || ""}:${unit}`;
    const stable = el.getAttribute("data-message-id") || el.id;
    if (stable) return stable;
    if (!nodeIds.has(el)) nodeIds.set(el, `node-${++nodeSequence}`);
    return nodeIds.get(el);
  }
  function hashText(text) {
    // Ephemeral local fingerprint only: neither text nor this hash leaves this script.
    let hash = 2166136261;
    for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
    return `${text.length}:${hash >>> 0}`;
  }
  function pageScope() {
    // Cached pages remain in the document, sometimes with visible geometry.
    // During a page switch, wait instead of falling back to an inactive chat.
    return document.querySelector('[data-app-shell-active-page="true"]')
      || (document.querySelector('[data-app-shell-active-page]') ? emptyScope : document);
  }
  function composer(page = pageScope()) {
    return [...page.querySelectorAll(COMPOSER_SELECTOR)].find(visible) || null;
  }
  function latestMessage(scope, role) {
    // Mix both formats in document order: older text replies must not hide a
    // newer tool/visual turn which only exposes data-turn.
    const matches = scope.querySelectorAll(`[data-message-author-role="${role}"],[data-message-role="${role}"],article[data-turn="${role}"],[data-testid^="conversation-turn-"][data-turn="${role}"],[data-chatgpt-search-unit-key$=":${role}"]`);
    return matches[matches.length - 1] || null;
  }
  function responseText(assistant) {
    if (!assistant) return "";
    const source = assistant.matches('[data-chatgpt-search-unit-key]')
      ? assistant.querySelector('[data-response-body]')
      : assistant.querySelector('[data-assistant-markdown]') || assistant;
    if (!source) return "";
    const copy = source.cloneNode(true);
    // A fallback assistant can itself be the article. Its action labels and
    // SVG labels are not prose and must not turn an empty reply into output.
    copy.querySelectorAll(`${NON_OUTPUT_SELECTOR},svg,iframe,canvas,video,audio`).forEach(el => el.remove());
    return copy.textContent || "";
  }
  function responseMedia(turn) {
    if (!turn) return [];
    return [...turn.querySelectorAll("img,video,audio,canvas,svg,iframe")].filter(el => {
      if (!visible(el) || el.closest('script,style,template,[hidden],[aria-hidden="true"]')
          || el.closest('[data-message-author-role="user"],[data-message-role="user"],[data-turn="user"],[data-chatgpt-search-unit-key$=":user"]')) return false;
      const owner = el.closest(TURN_SELECTOR);
      if (owner && owner !== turn) return false;
      const tag = el.tagName.toLowerCase();
      const bounds = el.getBoundingClientRect();
      // Exclude small avatars/status icons, including images outside buttons.
      if (bounds.width < 48 || bounds.height < 48) return false;
      const control = el.closest('button,[role="button"]');
      if (control) {
        // A large result image may itself be an expand/open button. Ordinary
        // action icons are not outputs, even when their CSS makes them large.
        if (tag !== "img" || control.matches('[data-testid$="-turn-action-button"]')
            || labelled(control, FINAL_LABEL) || labelled(control, REGEN_LABEL)
            || labelled(control, STOP_LABEL) || labelled(control, SEND_LABEL)) return false;
      }
      if (tag === "svg" && !el.querySelector("path,rect,circle,ellipse,line,polyline,polygon,text,image,use,foreignObject")) return false;
      if (tag === "iframe" && !el.getAttribute("srcdoc")?.trim()) {
        const src = el.getAttribute("src")?.trim();
        if (!src || src === "about:blank") return false;
      }
      return true;
    });
  }
  function snapshot() {
    const page = pageScope();
    const transcript = page.querySelector('[data-rail-chat-transcript],[data-conversation-transcript]');
    const scope = transcript || page.querySelector('main[data-slot="conversation"]') || page.querySelector("main") || page;
    const assistant = latestMessage(scope, "assistant");
    const user = latestMessage(scope, "user");
    const turn = assistant?.closest(TURN_SELECTOR) || assistant;
    const threadUI = Boolean(transcript?.matches('[data-rail-chat-transcript]') || page.querySelector('form[data-chatgpt-composer]'));
    const threadState = threadUI ? assistant?.closest('[data-talvt-turn-state]') : null;
    // Current transcript turns expose an explicit completion attribute. An
    // enabled composer or temporarily missing Stop button is not enough there.
    const completionRequired = threadUI || Boolean(turn?.matches('[data-message-role="assistant"]'));
    const completionMarked = threadUI ? threadState?.getAttribute('data-talvt-turn-state') === 'complete'
      : completionRequired && turn.hasAttribute('data-message-complete');
    const editor = composer(page);
    // Restrict language fallbacks to the composer area, never arbitrary response prose.
    const editorArea = editor?.closest('form,[data-type="unified-composer"]') || editor?.parentElement?.parentElement;
    const explicitStop = [...page.querySelectorAll(STOP_SELECTOR)].some(visible);
    const labelledStop = editorArea ? [...editorArea.querySelectorAll('button[aria-label],button[title]')]
      .some(button => visible(button) && labelled(button, STOP_LABEL)) : false;
    // Loading widgets inside an old completed answer do not start a new run.
    // The current UI's generic aria-busy signal belongs only to the latest,
    // unfinished assistant turn; Stop and form-submission signals stay global.
    const currentStreaming = !threadUI && completionRequired && !completionMarked
      && [...turn.querySelectorAll(CURRENT_STREAM_SELECTOR)].some(visible);
    const streaming = currentStreaming
      || Boolean(turn && (turn.matches(STREAM_SELECTOR) || turn.querySelector(STREAM_SELECTOR)))
      || [...scope.querySelectorAll(STREAM_SELECTOR)].some(visible);
    const submitting = Boolean(editorArea?.matches('form[data-mobile-composer][data-octane-followup-submitting]'));
    const busy = explicitStop || labelledStop || streaming || submitting;
    // Visual results may be siblings of the text node within the same answer.
    // Never read iframe documents or transmit prose, markup, media URLs or hashes.
    const text = responseText(assistant);
    const mediaElements = responseMedia(turn);
    const media = mediaElements.map(el => `${nodeKey(el)}:${el.outerHTML}`).join("|");
    const hasTextOutput = Boolean(text.trim());
    const visualOnly = !hasTextOutput && mediaElements.length > 0;
    const signature = assistant ? `${nodeKey(assistant)}:${hashText(text)}:${hashText(media)}` : "";
    const afterUser = Boolean(assistant && (!user || (user.compareDocumentPosition(assistant) & Node.DOCUMENT_POSITION_FOLLOWING)));
    const finalControls = threadUI ? Boolean(threadState && [...threadState.querySelectorAll('button')].some(button =>
      visible(button) && button.closest('[data-talvt-turn-state]') === threadState
      && !button.closest('[data-spacing="activity"],[data-chatgpt-search-unit-key],[data-response-body]')
      && labelled(button, THREAD_FINAL_LABEL)))
      : Boolean(turn && [...turn.querySelectorAll("button")].some(button => visible(button) && (
      button.matches('[data-testid="copy-turn-action-button"],[data-testid="good-response-turn-action-button"],[data-testid="bad-response-turn-action-button"]')
      || (button.matches('[data-copy-message]') && button.closest('[data-assistant-message-actions]'))
      || labelled(button, visualOnly ? FINAL_VISUAL_LABEL : FINAL_LABEL)
    )));
    const error = Boolean(turn?.querySelector('[data-testid="conversation-turn-error"],[data-testid="regenerate-thread-error-button"],[role="alert"]'));
    const editorReady = Boolean(editor && visible(editor) && !editor.disabled
      && editor.getAttribute("contenteditable") !== "false" && editor.getAttribute("aria-disabled") !== "true");
    return {
      route: location.pathname,
      userKey: nodeKey(user), assistantKey: nodeKey(assistant), signature,
      hasOutput: hasTextOutput || mediaElements.length > 0, afterUser, busy,
      // Virtual scrolling can mount an older user turn without a new send.
      allowUserFallback: !threadUI,
      composerReady: editorReady && !busy, finalControls, error,
      completionRequired, completionMarked,
      hasTextOutput, visualOnly, mediaCount: mediaElements.length,
      mediaKinds: [...new Set(mediaElements.map(el => el.tagName.toLowerCase()))],
      stopDetected: explicitStop || labelledStop, streamingDetected: streaming,
      assistantFound: Boolean(assistant), userFound: Boolean(user), composerFound: Boolean(editor),
      uiDetected: Boolean(editor),
      uiVariant: threadUI ? "thread" : transcript || editor?.matches('#mobile-composer-prompt,[data-mobile-composer-prompt]') ? "current" : editor ? "legacy" : "unknown"
    };
  }
  function dispose() {
    stopped = true;
    observer.disconnect();
    clearTimeout(scheduled);
    clearInterval(heartbeat);
  }
  async function send(message) {
    if (stopped) return null;
    try {
      return await chrome.runtime.sendMessage({ target: "background", ...message });
    } catch (error) {
      if (/context invalidated|Extension context/i.test(String(error))) dispose();
      return null;
    }
  }
  function buildStatus(s) {
    return {
      version: VERSION, phase: detector.phase, enabled: prefs.enabled,
      stopDetected: s.stopDetected, streamingDetected: s.streamingDetected,
      assistantFound: s.assistantFound, hasOutput: s.hasOutput,
      finalControls: s.finalControls, composerFound: s.composerFound,
      hasTextOutput: s.hasTextOutput, visualOnly: s.visualOnly,
      mediaCount: s.mediaCount, mediaKinds: s.mediaKinds,
      afterUser: s.afterUser, composerReady: s.composerReady,
      userFound: s.userFound, uiDetected: s.uiDetected, uiVariant: s.uiVariant,
      completionRequired: s.completionRequired, completionMarked: s.completionMarked,
      sawBusy: detector.status().sawBusy,
      busy: s.busy, active: Boolean(detector.run), lastEvent,
      documentReady: document.readyState, scanError: false,
      sampledAt: Date.now(), scanAttemptAt: Date.now()
    };
  }
  function handle(events, s) {
    for (const event of events) {
      if (event.type === "complete") {
        lastEvent = "complete";
        const payload = { type: "complete", eventId: `${documentId}:${event.id}`, url: CGN.safeChatUrl(location.href) };
        // Retry an unacknowledged delivery once; worker deduplicates event IDs.
        send(payload).then(result => {
          if (result === null && !stopped) setTimeout(() => { void send(payload); }, 1800);
        });
      } else if (event.type === "error") lastEvent = "page-error";
    }
    lastStatus = buildStatus(s);
    if (lastSentPhase !== detector.phase) {
      lastSentPhase = detector.phase;
      void send({ type: "status", status: lastStatus });
    }
  }
  function scan() {
    scheduled = null;
    if (stopped) return;
    try {
      const s = snapshot();
      handle(detector.tick(s, Date.now()), s);
    } catch {
      // A transitioning DOM must not break monitoring. The next mutation retries.
      lastEvent = "snapshot-retry";
      lastStatus = { ...lastStatus, version: VERSION, phase: detector.phase, enabled: prefs.enabled,
        scanError: true, lastEvent, documentReady: document.readyState, scanAttemptAt: Date.now() };
    }
  }
  function schedule(delay = 250) {
    if (!stopped && scheduled === null) scheduled = setTimeout(scan, delay);
  }
  function arm() {
    const now = Date.now();
    if (!prefs.enabled || now - lastSubmitAt < 350) return;
    lastSubmitAt = now;
    lastEvent = "submit";
    const s = snapshot();
    detector.submit(s, now);
    handle(detector.drain(), s);
    schedule(100);
  }
  document.addEventListener("click", event => {
    if (stopped || !event.isTrusted) return;
    const el = event.target instanceof Element ? event.target : event.target?.parentElement;
    if (!el) return;
    const link = el.closest("a[href]");
    if (link && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0 && link.target !== "_blank") {
      try {
        const dest = new URL(link.href);
        if (dest.origin === location.origin && dest.pathname !== location.pathname) {
          detector.navigate(Date.now());
          lastEvent = "navigation";
        }
      } catch { /* Not a navigable URL. */ }
    }
    const button = el.closest("button");
    if (!button || button.disabled || !pageScope().contains(button)) return;
    if (button.matches(STOP_SELECTOR) || labelled(button, STOP_LABEL)) {
      lastEvent = "manual-stop";
      detector.cancel(Date.now());
      handle(detector.drain(), snapshot());
    } else if (button.matches(SEND_SELECTOR) || labelled(button, SEND_LABEL)
        || button.matches('[data-testid="regenerate-thread-action-button"]') || labelled(button, REGEN_LABEL)) {
      arm();
    }
  }, true);
  document.addEventListener("keydown", event => {
    if (stopped || !event.isTrusted || event.key !== "Enter" || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || event.isComposing || event.keyCode === 229) return;
    const editor = composer();
    if (editor?.contains(event.target) && String(editor.value ?? editor.textContent ?? "").trim()) arm();
  }, true);
  document.addEventListener("submit", event => {
    if (!stopped && event.isTrusted && event.target?.contains(composer())) arm();
  }, true);
  window.addEventListener("popstate", () => {
    if (stopped) return;
    detector.navigate(Date.now()); lastEvent = "navigation"; schedule(0);
  });
  document.addEventListener("visibilitychange", () => schedule(0));
  window.addEventListener("pageshow", () => schedule(0));

  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (stopped || sender.id !== chrome.runtime.id || message?.target !== "content") return false;
    if (message.type === "get-status") {
      scan();
      respond({ ok: true, ...lastStatus });
    }
    return false;
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (stopped || area !== "local" || !changes.settings) return;
    prefs = sanitizeSettings(changes.settings.newValue);
    detector.configure(prefs, Date.now());
    schedule(0);
  });
  async function start() {
    try { prefs = sanitizeSettings((await chrome.storage.local.get("settings")).settings); }
    catch { /* Defaults remain usable. */ }
    detector.configure(prefs, Date.now());
    observer.observe(document.documentElement, {
      childList: true, subtree: true, characterData: true, attributes: true,
      attributeFilter: ["class", "style", "hidden", "aria-label", "aria-busy", "aria-hidden", "aria-disabled", "data-testid", "data-message-author-role", "data-message-role", "data-message-complete", "data-stop-generating", "data-octane-followup-submitting", "data-app-shell-active-page", "data-talvt-turn-state", "data-chatgpt-search-unit-key", "data-response-body", "data-turn-key", "contenteditable", "data-turn", "data-is-streaming", "data-is-generating", "disabled", "src", "srcdoc", "width", "height", "d", "points", "viewBox", "transform"]
    });
    scan();
    // Backup scan for missed attribute changes and SPA URLs. Background tabs can
    // be throttled or frozen by Chrome; no attempt is made to evade that policy.
    heartbeat = setInterval(scan, 1500);
  }
  void start();
})();
