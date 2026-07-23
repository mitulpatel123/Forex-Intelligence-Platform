const statusElement = document.querySelector("#status");
void chrome.runtime.sendMessage({ type: "GET_STATUS" }).then((response: unknown) => {
  if (statusElement && typeof response === "object" && response !== null && "state" in response) {
    statusElement.textContent = String(response.state);
  }
});

