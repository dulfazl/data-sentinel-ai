const DEFAULTS = {
  agentUrl: "http://127.0.0.1:8765",
  token: "",
  blockWhenOffline: false,
  skipSites: "localhost:8501\n127.0.0.1:8501",
};
const $ = (id) => document.getElementById(id);

async function load() {
  const s = await chrome.storage.local.get(DEFAULTS);
  $("agentUrl").value = s.agentUrl;
  $("token").value = s.token;
  $("blockWhenOffline").checked = !!s.blockWhenOffline;
  $("skipSites").value = s.skipSites;
}

function show(text, ok) {
  $("status").textContent = text;
  $("status").className = ok ? "ok" : "bad";
}

async function saveAndTest() {
  const s = {
    agentUrl: $("agentUrl").value.trim() || DEFAULTS.agentUrl,
    token: $("token").value.trim(),
    blockWhenOffline: $("blockWhenOffline").checked,
    skipSites: $("skipSites").value,
  };
  await chrome.storage.local.set(s);
  show("Saved. Testing the agent...", true);
  const r = await chrome.runtime.sendMessage({ type: "test" });
  if (!r.reachable) show(`Saved, but the agent is not reachable at ${s.agentUrl}. Is it running?`, false);
  else if (!r.tokenOk) show("Saved. The agent is running but rejected the token - copy it again from .sentinel_token.", false);
  else show("Saved. Connected to the agent - token accepted." + (r.dryRun ? " (agent is in dry-run mode)" : ""), true);
}

$("save").addEventListener("click", saveAndTest);
load();
