// Data Sentinel AI - background service worker.
// The only part of the extension that talks to the local agent (content scripts cannot,
// because the agent sends no CORS headers on purpose).

const DEFAULTS = {
  agentUrl: "http://127.0.0.1:8765",
  token: "",
  blockWhenOffline: false,
  skipSites: "localhost:8501\n127.0.0.1:8501",
};
const TIMEOUT_MS = 30000;

function settings() {
  return chrome.storage.local.get(DEFAULTS);
}

function baseUrl(s) {
  return (s.agentUrl || DEFAULTS.agentUrl).replace(/\/+$/, "");
}

function offlineVerdict(s, why) {
  if (s.blockWhenOffline) {
    return {
      decision: "BLOCK", allow: false, offline: true,
      message: `Blocked by Data Sentinel: ${why}. Transfers are blocked while the agent is unavailable.`,
    };
  }
  return {
    decision: "ALLOW", allow: true, offline: true,
    message: `Data Sentinel: ${why} - this transfer was NOT checked.`,
  };
}

async function scan(request) {
  const s = await settings();
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const resp = await fetch(baseUrl(s) + "/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Sentinel-Token": s.token || "" },
      body: JSON.stringify(request),
      signal: ctl.signal,
    });
    if (resp.status === 401) return offlineVerdict(s, "the agent rejected the token (check the extension options)");
    if (!resp.ok) return offlineVerdict(s, `the agent returned error ${resp.status}`);
    const v = await resp.json();
    // In --dry-run the agent still says BLOCK but enforce=false: let it through.
    v.allow = !(v.decision === "BLOCK" && v.enforce !== false);
    return v;
  } catch (err) {
    return offlineVerdict(s, "the agent is offline");
  } finally {
    clearTimeout(timer);
  }
}

async function test(override) {
  const s = Object.assign(await settings(), override || {});
  try {
    const resp = await fetch(baseUrl(s) + "/health", { headers: { "X-Sentinel-Token": s.token || "" } });
    const body = await resp.json();
    return { reachable: resp.ok, tokenOk: body.token_ok === true, dryRun: !!body.dry_run };
  } catch (err) {
    return { reachable: false, tokenOk: false, error: String(err) };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "scan") {
    scan(msg.request).then(sendResponse);
    return true; // async response
  }
  if (msg && msg.type === "test") {
    test(msg.settings).then(sendResponse);
    return true;
  }
  return false;
});

chrome.runtime.onInstalled.addListener(async (details) => {
  const s = await chrome.storage.local.get(null);
  await chrome.storage.local.set(Object.assign({}, DEFAULTS, s));
  if (details.reason === "install" && !s.token) chrome.runtime.openOptionsPage();
});
