const input = document.querySelector<HTMLInputElement>("#token");
const result = document.querySelector<HTMLOutputElement>("#result");
document.querySelector("#save")?.addEventListener("click", async () => {
  const value = input?.value.trim() ?? "";
  if (value.length < 32) {
    if (result) result.textContent = "Token is too short.";
    return;
  }
  await chrome.storage.local.set({ bridgeToken: value });
  if (input) input.value = "";
  if (result) result.textContent = "Saved in extension-local storage.";
});

