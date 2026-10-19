document.getElementById("opts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

chrome.runtime.sendMessage({ type: "test" }).then((r) => {
  const dot = document.getElementById("dot");
  const state = document.getElementById("state");
  if (r.reachable && r.tokenOk) {
    dot.className = "dot ok";
    state.textContent = "Protected - agent connected" + (r.dryRun ? " (dry-run)" : "");
  } else {
    dot.className = "dot bad";
    state.textContent = r.reachable ? "Agent running, but the token is wrong" : "Agent offline";
  }
});
