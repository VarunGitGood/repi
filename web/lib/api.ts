// Defaults to a same-origin `/api` prefix so the browser only needs to reach
// the Next.js server; the server proxies `/api/*` to uvicorn (see
// next.config.ts). Set NEXT_PUBLIC_API_URL at build time to point the browser
// directly at a remote API host instead.
export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api";

export async function fetchApi(path: string, options: RequestInit = {}) {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || "An error occurred");
  }

  return response.json();
}

export const api = {
  config: {
    get: () => fetchApi("/config"),
    update: (data: any) => fetchApi("/config", { method: "PUT", body: JSON.stringify(data) }),
  },
  watchers: {
    list: () => fetchApi("/watchers"),
    create: (data: any) => fetchApi("/watchers", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: any) => fetchApi(`/watchers/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) => fetchApi(`/watchers/${id}`, { method: "DELETE" }),
  },
  investigations: {
    list: () => fetchApi("/investigations"),
    get: (id: string) => fetchApi(`/investigations/${id}`),
    create: (query: string, conversation_id?: string) =>
      fetchApi("/investigate", {
        method: "POST",
        body: JSON.stringify(conversation_id ? { query, conversation_id } : { query }),
      }),
    clarify: (id: string, reply: string) => fetchApi(`/investigations/${id}/clarify`, { method: "POST", body: JSON.stringify({ reply }) }),
  },
  conversations: {
    list: () => fetchApi("/conversations"),
    get: (id: string) => fetchApi(`/conversations/${id}`),
  },
};

