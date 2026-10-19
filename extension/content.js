// Data Sentinel AI - content script (isolated world), on every site.
// Holds file-input uploads, drag-and-drop and pastes of 20+ characters, asks the local agent
// (through the background worker), then replays the event on ALLOW/WARN or drops it on BLOCK.
(() => {
  if (window.__dataSentinelContent) return;
  window.__dataSentinelContent = true;

  const MIN_PASTE = 20;
  const MAX_INSPECT = 20 * 1024 * 1024; // larger files are sent as name + size only
  const RANK = { ALLOW: 0, WARN: 1, BLOCK: 2 };
  let replaying = false; // true while we re-dispatch an event we already checked
  let skipList = ["localhost:8501", "127.0.0.1:8501"];

  try {
    chrome.storage.local.get({ skipSites: skipList.join("\n") }).then((s) => (skipList = parseSkip(s.skipSites)));
    chrome.storage.onChanged.addListener((c) => {
      if (c.skipSites) skipList = parseSkip(c.skipSites.newValue || "");
    });
  } catch (e) { /* extension reloaded */ }

  function parseSkip(text) {
    return String(text || "").split(/[\s,]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);
  }

  function skipped() {
    const host = location.host.toLowerCase();
    return skipList.some((s) => host === s || host.endsWith("." + s));
  }

  // ------------------------------------------------------------------ agent
  function readAsBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",", 2)[1] || "");
      r.onerror = () => reject(r.error);
      r.readAsDataURL(file);
    });
  }

  async function ask(request) {
    request.host = location.hostname;
    request.url = location.origin;
    try {
      return await chrome.runtime.sendMessage({ type: "scan", request });
    } catch (e) {
      return { decision: "ALLOW", allow: true, offline: true,
               message: "Data Sentinel extension was updated - reload this page so transfers are checked." };
    }
  }

  async function scanFile(file, kind) {
    const meta = { name: file.name || "unnamed file", size: file.size, type: file.type };
    if (file.size <= MAX_INSPECT) {
      try {
        meta.content_b64 = await readAsBase64(file);
      } catch (e) { /* unreadable: judged by name and size */ }
    }
    return ask({ kind, file: meta });
  }

  function scanText(text, kind) {
    return ask({ kind, text });
  }

  function combine(verdicts) {
    let worst = null;
    for (const v of verdicts) {
      if (!v) continue;
      const a = RANK[v.decision] || 0, b = worst ? RANK[worst.decision] || 0 : -1;
      if (a > b || (a === b && v.offline && !worst.offline)) worst = v;
    }
    worst = worst || { decision: "ALLOW", allow: true };
    worst.allow = verdicts.every((v) => !v || v.allow);
    return worst;
  }

  // ------------------------------------------------------------------ banner
  let bannerHost = null;
  function banner(v) {
    if (!v || !v.message) return;
    const blocked = !v.allow;
    const kind = blocked ? "block" : v.decision === "BLOCK" || v.decision === "WARN" || v.offline ? "warn" : null;
    if (!kind) return;
    const root = document.documentElement || document.body;
    if (!root) return;
    if (bannerHost) bannerHost.remove();
    bannerHost = document.createElement("data-sentinel-banner");
    const shadow = bannerHost.attachShadow({ mode: "closed" });
    const bg = kind === "block" ? "#d03b3b" : "#fab219";
    const fg = kind === "block" ? "#ffffff" : "#0b0b0b";
    shadow.innerHTML = `
      <style>
        .bar { position: fixed; top: 12px; left: 50%; transform: translateX(-50%); z-index: 2147483647;
               max-width: min(720px, calc(100vw - 32px)); box-sizing: border-box; display: flex; gap: 12px;
               align-items: flex-start; padding: 12px 16px; border-radius: 10px; background: ${bg}; color: ${fg};
               font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif;
               box-shadow: 0 6px 24px rgba(0,0,0,.25); }
        .title { font-weight: 700; margin-right: 4px; }
        button { all: unset; cursor: pointer; font-weight: 700; padding: 0 4px; color: ${fg}; }
      </style>
      <div class="bar" role="alert">
        <div><span class="title">${kind === "block" ? "⛔ Blocked" : "⚠ Warning"}</span><span class="msg"></span></div>
        <button aria-label="Dismiss">✕</button>
      </div>`;
    shadow.querySelector(".msg").textContent = " " + v.message;
    shadow.querySelector("button").addEventListener("click", () => bannerHost && bannerHost.remove());
    bannerHost.dataset.kind = kind;
    bannerHost.dataset.message = v.message;
    root.appendChild(bannerHost);
    const mine = bannerHost;
    setTimeout(() => { if (bannerHost === mine) { mine.remove(); bannerHost = null; } }, kind === "block" ? 12000 : 8000);
  }

  function replayWith(fn) {
    replaying = true;
    try { return fn(); } finally { replaying = false; }
  }

  // ------------------------------------------------------------------ file inputs
  async function checkFileInput(input) {
    const verdict = combine(await Promise.all(Array.from(input.files).map((f) => scanFile(f, "upload"))));
    if (verdict.allow) {
      replayWith(() => {
        input.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    } else {
      input.value = ""; // the site never receives the files
    }
    banner(verdict);
  }

  function onFileInputEvent(e) {
    const t = e.target;
    if (replaying || !(t instanceof HTMLInputElement) || t.type !== "file") return;
    if (!t.files || !t.files.length || skipped()) return;
    e.stopImmediatePropagation(); // hold the event: the page's handlers do not see it yet
    if (e.type === "change") checkFileInput(t);
  }
  window.addEventListener("input", onFileInputEvent, true);
  window.addEventListener("change", onFileInputEvent, true);

  // Detached inputs (Google Drive) are reported by page_hook.js in the page world.
  window.addEventListener("message", async (e) => {
    const d = e.data;
    if (e.source !== window || !d || d.__dataSentinel !== "detached-files") return;
    let verdict = { allow: true };
    if (!skipped()) {
      verdict = combine(await Promise.all((d.files || []).map((f) => scanFile(f, "upload"))));
      banner(verdict);
    }
    window.postMessage({ __dataSentinel: "verdict", id: d.id, allow: verdict.allow }, "*");
  });

  // ------------------------------------------------------------------ text helpers
  function isEditable(el) {
    return el && (el.isContentEditable || el instanceof HTMLTextAreaElement ||
      (el instanceof HTMLInputElement && /^(text|search|url|email|tel|password|)$/i.test(el.type)));
  }

  function saveSelection(el) {
    if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
      return { el, start: el.selectionStart, end: el.selectionEnd };
    }
    const sel = window.getSelection();
    return { el, range: sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null };
  }

  function restoreSelection(s) {
    if (!s || !s.el) return;
    try {
      s.el.focus({ preventScroll: true });
      if (s.range) {
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(s.range);
      } else if (s.start != null) {
        s.el.setSelectionRange(s.start, s.end);
      }
    } catch (e) { /* element gone */ }
  }

  function insertText(target, text) {
    if (!isEditable(target)) return;
    if (!document.execCommand("insertText", false, text) &&
        (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement)) {
      target.setRangeText(text, target.selectionStart, target.selectionEnd, "end");
      target.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function copyData(dt) {
    const data = {};
    for (const type of Array.from(dt.types || [])) {
      if (type === "Files") continue;
      try { data[type] = dt.getData(type); } catch (e) { /* protected */ }
    }
    return data;
  }

  function rebuild(files, data) {
    const dt = new DataTransfer();
    for (const f of files) dt.items.add(f);
    for (const [type, value] of Object.entries(data)) {
      try { dt.setData(type, value); } catch (e) { /* ignore */ }
    }
    return dt;
  }

  // ------------------------------------------------------------------ paste
  function onPaste(e) {
    if (replaying || skipped() || !e.clipboardData) return;
    const files = Array.from(e.clipboardData.files || []);
    const text = e.clipboardData.getData("text/plain") || "";
    if (!files.length && text.trim().length < MIN_PASTE) return; // short pastes pass untouched
    e.preventDefault();
    e.stopImmediatePropagation();
    const data = copyData(e.clipboardData);
    const target = e.target;
    const sel = saveSelection(document.activeElement && isEditable(document.activeElement) ? document.activeElement : target);
    (async () => {
      const checks = files.map((f) => scanFile(f, "paste"));
      if (text.trim().length >= MIN_PASTE) checks.push(scanText(text, "paste"));
      const verdict = combine(await Promise.all(checks));
      if (verdict.allow) {
        restoreSelection(sel);
        const ev = new ClipboardEvent("paste", { clipboardData: rebuild(files, data), bubbles: true, cancelable: true, composed: true });
        const notHandled = replayWith(() => target.dispatchEvent(ev));
        if (notHandled && text) insertText(sel.el || target, text); // the browser's own paste does not run for replays
      }
      banner(verdict);
    })();
  }
  window.addEventListener("paste", onPaste, true);

  // ------------------------------------------------------------------ drag and drop
  function onDrop(e) {
    if (replaying || skipped() || !e.dataTransfer) return;
    const files = Array.from(e.dataTransfer.files || []);
    const text = files.length ? "" : e.dataTransfer.getData("text/plain") || "";
    if (!files.length && text.trim().length < MIN_PASTE) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const data = copyData(e.dataTransfer);
    const target = e.target;
    const init = { bubbles: true, cancelable: true, composed: true, clientX: e.clientX, clientY: e.clientY,
                   screenX: e.screenX, screenY: e.screenY, ctrlKey: e.ctrlKey, shiftKey: e.shiftKey,
                   altKey: e.altKey, metaKey: e.metaKey };
    (async () => {
      const checks = files.length ? files.map((f) => scanFile(f, "drop")) : [scanText(text, "drop")];
      const verdict = combine(await Promise.all(checks));
      if (verdict.allow) {
        const ev = new DragEvent("drop", Object.assign({ dataTransfer: rebuild(files, data) }, init));
        const notHandled = replayWith(() => target.dispatchEvent(ev));
        if (notHandled && !files.length && isEditable(target)) {
          target.focus();
          insertText(target, text);
        }
      }
      banner(verdict);
    })();
  }
  window.addEventListener("drop", onDrop, true);
})();
