/*
 * Pure state machine: input is a DOM-derived snapshot; output is state events.
 * No network, browser APIs, or conversation text. Unit tests use synthetic time.
 * Completion is a UI heuristic, not an official ChatGPT server event.
 */
(() => {
  "use strict";
  const chatId = route => String(route).match(/(?:^|\/)c\/([^/?#]+)/)?.[1] || null;
  class CompletionDetector {
    constructor({ settleMs = 5000, enabled = true } = {}) {
      this.settleMs = settleMs;
      this.enabled = enabled;
      this.last = null;
      this.run = null;
      this.phase = enabled ? "idle" : "disabled";
      this.ignoreUntil = 0;
      this.cancelLatch = false;
      this.cancelQuietAt = null;
      this.sequence = 0;
      this.events = [];
    }
    configure({ settleMs, enabled }, now) {
      if (Number.isFinite(settleMs)) this.settleMs = Math.max(1000, settleMs);
      if (typeof enabled === "boolean" && enabled !== this.enabled) {
        this.enabled = enabled;
        this.run = null;
        this.cancelLatch = false;
        this.ignoreUntil = now + 1500;
        this._phase(enabled ? "idle" : "disabled", now);
      }
    }
    _phase(value, now) {
      if (this.phase !== value) {
        this.phase = value;
        this.events.push({ type: "phase", phase: value, at: now });
      }
    }
    _start(base, snapshot, now, source, adopted = false) {
      this.run = {
        id: ++this.sequence, source, startedAt: now,
        baselineSignature: base.signature,
        baselineAssistantKey: base.assistantKey,
        lastSignature: snapshot.signature,
        outputChangedAt: now, quietSince: snapshot.busy ? null : now, readySince: null,
        sawBusy: Boolean(snapshot.busy),
        sawOutput: Boolean(adopted && snapshot.hasOutput && snapshot.afterUser),
        allowAssignment: source === "submit" && !chatId(base.route)
      };
      this._phase(snapshot.busy ? "generating" : "waiting", now);
    }
    submit(snapshot, now) {
      if (!this.enabled) return;
      this.cancelLatch = false;
      this.cancelQuietAt = null;
      this.ignoreUntil = 0;
      this._start(snapshot, snapshot, now, "submit");
      this.last = snapshot;
    }
    cancel(now) {
      if (!this.enabled) return;
      this.run = null;
      this.cancelLatch = true;
      this.cancelQuietAt = null;
      this._phase("cancelled", now);
    }
    navigate(now) {
      this.run = null;
      this.cancelLatch = false;
      this.ignoreUntil = now + 1800;
      this._phase(this.enabled ? "idle" : "disabled", now);
    }
    tick(s, now) {
      if (!this.last) {
        this.last = s;
        this.ignoreUntil = now + 1500;
        if (this.enabled && s.busy) this._start(s, s, now, "busy", true);
        return this.drain();
      }
      const previous = this.last;
      if (s.route !== previous.route) {
        // The initial send often replaces / (or /g/...) with /c/<new-id>.
        // A user-initiated navigation calls navigate() first and cannot use this path.
        const assignment = this.run?.allowAssignment && !chatId(previous.route) && chatId(s.route);
        if (assignment) this.run.allowAssignment = false;
        else this.navigate(now);
      }
      this.last = s;
      if (!this.enabled) return this.drain();
      if (this.cancelLatch) {
        if (s.busy) this.cancelQuietAt = null;
        else if (this.cancelQuietAt === null) this.cancelQuietAt = now;
        else if (now - this.cancelQuietAt >= this.settleMs) this.cancelLatch = false;
        return this.drain();
      }
      if (now < this.ignoreUntil) return this.drain();
      if (!this.run) {
        if (s.busy) this._start(previous, s, now, "busy", true);
        else if (s.userKey && previous.userKey && s.userKey !== previous.userKey) {
          this._start(previous, s, now, "user-message");
        }
      }
      const run = this.run;
      if (!run) return this.drain();
      if (s.signature !== run.lastSignature) {
        run.lastSignature = s.signature;
        run.outputChangedAt = now;
      }
      if (s.hasOutput && s.afterUser &&
          (s.signature !== run.baselineSignature || s.assistantKey !== run.baselineAssistantKey)) {
        run.sawOutput = true;
      }
      if (s.busy) {
        run.sawBusy = true;
        run.quietSince = null;
        run.readySince = null;
        this._phase("generating", now);
        return this.drain(); // Text pauses never imply completion while a busy marker remains.
      }
      if (run.quietSince === null) run.quietSince = now;
      if (s.error) {
        this.run = null;
        this._phase("error", now);
        this.events.push({ type: "error", at: now });
        return this.drain();
      }
      // Fast replies without an observed stop button require both the composer
      // and final answer controls. Visual-only replies also require both: an
      // embedded preview can exist long before the parent answer finishes.
      const ready = run.sawBusy && !s.visualOnly ? (s.composerReady || s.finalControls) : (s.composerReady && s.finalControls);
      const hasCurrentOutput = s.hasOutput && s.afterUser && run.sawOutput;
      if (hasCurrentOutput && ready) {
        if (run.readySince === null) run.readySince = now;
        this._phase("settling", now);
      } else {
        run.readySince = null;
        this._phase("waiting", now);
      }
      if (hasCurrentOutput && ready && now - run.quietSince >= this.settleMs
          && now - run.readySince >= this.settleMs
          && now - run.outputChangedAt >= this.settleMs) {
        this.run = null;
        this._phase("complete", now);
        this.events.push({ type: "complete", id: run.id, source: run.source, at: now });
      } else if (!run.sawBusy && now - run.startedAt > 120000) {
        // Failed submit / no output. Never emit a completion merely on timeout.
        this.run = null;
        this._phase("no-signal", now);
      }
      return this.drain();
    }
    drain() { const events = this.events; this.events = []; return events; }
    status() {
      return { phase: this.phase, active: Boolean(this.run), sawBusy: this.run?.sawBusy || false };
    }
  }
  globalThis.CgnCompletionDetector = CompletionDetector;
  if (typeof module !== "undefined" && module.exports) module.exports = { CompletionDetector };
})();
