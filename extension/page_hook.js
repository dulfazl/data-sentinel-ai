// Data Sentinel AI - runs in the page's own JavaScript world (MAIN).
// Some sites (Google Drive) open the file picker with an <input type=file> that is never added
// to the page. Its change event never reaches window, so the content script cannot see it.
// We guard every file input that is opened with .click()/.showPicker() and hold its
// input/change events until the content script has the agent's verdict.
(() => {
  if (window.__dataSentinelHook) return;
  Object.defineProperty(window, "__dataSentinelHook", { value: true });

  const proto = HTMLInputElement.prototype;
  const origClick = proto.click;
  const origShowPicker = proto.showPicker;
  const guarded = new WeakSet();
  const pending = new Map();
  let seq = 0;
  let replaying = false;

  function guard(input) {
    if (!input || input.type !== "file" || guarded.has(input)) return;
    guarded.add(input);
    const hold = (e) => {
      // Inputs inside the page bubble to window and are handled by the content script.
      if (replaying || input.isConnected || !input.files || !input.files.length) return;
      e.stopImmediatePropagation();
      if (e.type !== "change") return; // 'input' fires first: just hold it
      const id = ++seq;
      pending.set(id, input);
      window.postMessage({ __dataSentinel: "detached-files", id, files: Array.from(input.files) }, "*");
    };
    input.addEventListener("input", hold, true);
    input.addEventListener("change", hold, true);
  }

  proto.click = function () {
    guard(this);
    return origClick.apply(this, arguments);
  };
  if (origShowPicker) {
    proto.showPicker = function () {
      guard(this);
      return origShowPicker.apply(this, arguments);
    };
  }

  window.addEventListener("message", (e) => {
    const d = e.data;
    if (e.source !== window || !d || d.__dataSentinel !== "verdict") return;
    const input = pending.get(d.id);
    if (!input) return;
    pending.delete(d.id);
    if (d.allow) {
      replaying = true;
      try {
        input.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      } finally {
        replaying = false;
      }
    } else {
      input.value = ""; // drop the selected files
    }
  });
})();
