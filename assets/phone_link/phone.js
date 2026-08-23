(() => {
  const storageKey = "jarvis.phone-link.token.v1";
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
  let token = localStorage.getItem(storageKey) || "";
  let lastSequence = 0;
  let polling = false;
  let handoffData = null;

  const authHeaders = () => ({
    "Content-Type": "application/json",
    "Authorization": `Bearer ${token}`,
  });

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

  async function pairFromFragment() {
    const params = new URLSearchParams(location.hash.slice(1));
    const pairToken = params.get("pair");
    if (!pairToken) return false;
    history.replaceState(null, "", "/phone/");
    setConnection("Pairing this iPhone…");
    const response = await fetch("/api/phone/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pair_token: pairToken, device_name: "iPhone" }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Pairing failed.");
    token = data.device_token;
    localStorage.setItem(storageKey, token);
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
    } catch (error) {
      setConnection(token ? "Waiting for your Mac…" : error.message);
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
    handoff.hidden = false;
  }

  handoffButton.addEventListener("click", async () => {
    if (!handoffData) return;
    if (handoffData.copy && navigator.clipboard) {
      try { await navigator.clipboard.writeText(handoffData.copy); } catch (_) {}
    }
    location.href = handoffData.url;
    handoff.hidden = true;
  });

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
      await pairFromFragment();
      if (!token) {
        setConnection("Scan a Phone Link QR in JARVIS");
        return;
      }
      await poll();
      setInterval(poll, 1100);
    } catch (error) {
      setConnection(error.message);
    }
  })();
})();
