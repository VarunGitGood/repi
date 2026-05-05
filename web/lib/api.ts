const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
    create: (query: string) => fetchApi("/investigate", { method: "POST", body: JSON.stringify({ query }) }),
    clarify: (id: string, reply: string) => fetchApi(`/investigations/${id}/clarify`, { method: "POST", body: JSON.stringify({ reply }) }),
  },
};
