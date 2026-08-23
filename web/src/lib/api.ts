export type User = {
  id: string;
  email: string;
  display_name: string;
  gemini_configured: boolean;
};

export type Session = { access_token: string; token_type: string; user: User };
export type Action = { name: string; description: string };

const HTTP_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = (process.env.NEXT_PUBLIC_WS_URL || HTTP_URL.replace(/^http/, "ws")).replace(/\/$/, "");

export function getToken() {
  return typeof window === "undefined" ? null : window.localStorage.getItem("jarvis_session");
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem("jarvis_session", token);
  else window.localStorage.removeItem("jarvis_session");
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(`${HTTP_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
