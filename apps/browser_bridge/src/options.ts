const input = document.querySelector<HTMLInputElement>("#token");
const discoveryMode = document.querySelector<HTMLInputElement>("#discovery-mode");
const result = document.querySelector<HTMLOutputElement>("#result");

void chrome.storage.local.get({ discoveryMode: false }).then((stored) => {
  if (discoveryMode) discoveryMode.checked = stored.discoveryMode === true;
});

document.querySelector("#save")?.addEventListener("click", async () => {
  const value = input?.value.trim() ?? "";
  const existing = await chrome.storage.local.get("bridgeToken");
  if (value.length > 0 && value.length < 32) {
    if (result) result.textContent = "Token is too short.";
    return;
  }
  if (value.length === 0 && typeof existing.bridgeToken !== "string") {
    if (result) result.textContent = "Enter the local bridge token.";
    return;
  }
  await chrome.storage.local.set({
    ...(value.length >= 32 ? { bridgeToken: value } : {}),
    discoveryMode: discoveryMode?.checked === true,
  });
  if (input) input.value = "";
  if (result) {
    result.textContent = `Saved. Binary discovery is ${
      discoveryMode?.checked === true ? "ON" : "OFF"
    }.`;
  }
});
