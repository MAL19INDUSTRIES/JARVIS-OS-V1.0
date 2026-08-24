(() => {
  const storageKey = "jarvis.phone-link.token.v1";
  const appShell = document.querySelector("#app-shell");
  const safariRequired = document.querySelector("#safari-required");
  const copySafariLink = document.querySelector("#copy-safari-link");
  const copyStatus = document.querySelector("#copy-status");
  const transcript = document.querySelector("#transcript");
  const opening = document.querySelector("#opening");
  const connection = document.querySelector("#connection");
  const persona = document.querySelector("#persona");
  const form = document.querySelector("#composer");
  const input = document.querySelector("#message");
  const send = document.querySelector("#send");
  const handoff = document.querySelector("#handoff");
  const handoffTitle = document.querySelector("#handoff-title");
  const handoffCopy = document.querySelector("#handoff-copy");
  const handoffButton = document.querySelector("#handoff-button");
  const installTip = document.querySelector("#install-tip");
  const installTipClose = document.querySelector("#install-tip-close");
  let token = localStorage.getItem(storageKey) || "";
  let lastSequence = 0;
  let polling = false;
  let handoffData = null;
  let pollTimer = null;

  const authHeaders = () => ({
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token}`,
  });

  function requiresSafari() {
    const userAgent = navigator.userAgent || "";
    const isIOS = /iPhone|iPad|iPod/i.test(userAgent);
    if (!isIOS || navigator.standalone === true) return false;
    const isSafari = /Version\/\d+(?:\.\d+)*.*Safari\//i.test(userAgent);
    const isAnotherBrowser = /CriOS|FxiOS|EdgiOS|OPiOS|DuckDuckGo|GSA/i.test(userAgent);
    return !isSafari || isAnotherBrowser;
  }

  function showSafariGate() {
    appShell.hidden = true;
    safariRequired.hidden = false;
  }

  async function copyCurrentLink() {
    const value = location.href;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const field = document.createElement("textarea");
        field.value = value;
        field.setAttribute("readonly", "");
        field.style.position = "fixed";
        field.style.opacity = "0";
        document.body.append(field);
        field.select();
        const copied = document.execCommand("copy");
        field.remove();
        if (!copied) throw new Error("Copy failed");
      }
      copyStatus.textContent = "Copied. Open Safari and paste the link.";
      copySafariLink.textContent = "COPIED";
    } catch (_error) {
      copyStatus.textContent = "Press and hold the address bar to copy, then paste it in Safari.";
    }
  }

  function setConnection(text, ready = false) {
    connection.textContent = text;
    send.disabled = !ready;
    input.disabled = !ready;
  }

  function appendMessage(item) {
    if (document.querySelector(`[data-seq="${item.seq}"]`)) return;
    opening.classList.add("hidden");
    const article = document.createElement("article");
    article.className = `message ${item.role === "user" ? "user" : "assistant"}`;
    article.dataset.seq = item.seq;
    const label = document.createElement("span");
    label.className = "speaker";
    label.textContent = item.role === "user" ? "YOU" : persona.textContent;
    const bubble = document.createElement("p");
    bubble.className = "bubble";
    bubble.textContent = item.content;
    article.append(label, bubble);
    transcript.append(article);
    lastSequence = Math.max(lastSequence, Number(item.seq) || 0);
    transcript.scrollTo({ top: transcript.scrollHeight, behavior: "smooth" });
  }

  async function pairInBrowser(pairToken) {
    history.replaceState(null, "", "/phone/");
    setConnection("Pairing this iPhone…");
    const response = await fetch("/api/phone/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pair_token: pairToken, device_name: "iPhone", client_kind: "web" }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Pairing failed.");
    token = data.device_token;
    localStorage.setItem(storageKey, token);
    await poll();
    startPolling();
    if (!window.navigator.standalone && localStorage.getItem("jarvis.phone-link.home-tip") !== "done") {
      installTip.hidden = false;
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = window.setInterval(poll, 1100);
  }

  async function pairFromFragment() {
    const params = new URLSearchParams(location.hash.slice(1));
    const pairToken = params.get("pair");
    if (!pairToken) return false;
    await pairInBrowser(pairToken);
    return true;
  }

  async function poll() {
    if (polling || !token) return;
    polling = true;
    try {
      const response = await fetch(`/api/phone/session?after=${lastSequence}`, { headers: authHeaders() });
      const data = await response.json();
      if (response.status === 401) {
        localStorage.removeItem(storageKey);
        token = "";
        throw new Error(data.error || "This iPhone link was revoked.");
      }
      if (!response.ok) throw new Error(data.error || "JARVIS is unavailable.");
      persona.textContent = data.persona || "JARVIS";
      setConnection("Connected on local Wi-Fi", true);
      (data.messages || []).forEach(appendMessage);
      return true;
    } catch (error) {
      setConnection(token ? "Waiting for your Mac…" : error.message);
      return false;
    } finally {
      polling = false;
    }
  }

  async function sendMessage(message) {
    const response = await fetch("/api/phone/chat", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ message }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Message could not be sent.");
    if (data.handoff) showHandoff(data.handoff);
  }

  function showHandoff(data) {
    handoffData = data;
    handoffTitle.textContent = data.label || "Action ready";
    handoffCopy.textContent = data.message || "Review this action on your iPhone.";
    handoffButton.textContent = data.kind === "call" ? "CALL" : data.kind === "message" ? "REVIEW" : "OPEN";
    handoffButton.setAttribute("href", data.url);
    handoffButton.setAttribute("aria-label", data.label || "Review phone action");
    handoff.hidden = false;
  }

  handoffButton.addEventListener("click", (event) => {
    if (!handoffData || !handoffData.url) {
      event.preventDefault();
    }
  });

  installTipClose.addEventListener("click", () => {
    localStorage.setItem("jarvis.phone-link.home-tip", "done");
    installTip.hidden = true;
  });

  copySafariLink.addEventListener("click", copyCurrentLink);

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || !token) return;
    input.value = "";
    input.style.height = "auto";
    setConnection("Sending…");
    try {
      await sendMessage(message);
      await poll();
    } catch (error) {
      setConnection(error.message);
    }
  });

  (async () => {
    try {
      if (requiresSafari()) {
        showSafariGate();
        return;
      }
      if (token) {
        const resumed = await poll();
        if (resumed) {
          history.replaceState(null, "", "/phone/");
          startPolling();
          return;
        }
      }
      const choosingClient = await pairFromFragment();
      if (choosingClient) return;
      if (!token) {
        setConnection("Scan a Phone Link QR in JARVIS");
        return;
      }
      await poll();
      startPolling();
    } catch (error) {
      setConnection(error.message);
    }
  })();
})();
