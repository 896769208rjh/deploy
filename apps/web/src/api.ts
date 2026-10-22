export type User = {
  id: string;
  email: string;
  display_name: string;
  role: string;
};

const TOKEN_KEY = "ai_platform_token";

export function token() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(value: string) {
  localStorage.setItem(TOKEN_KEY, value);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const current = token();
  if (current) headers.set("Authorization", `Bearer ${current}`);
  const response = await fetch(path, { ...options, headers });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new ApiError(typeof detail === "string" ? detail : "请求没有完成");
  }
  return data as T;
}

export function streamUrl(path: string) {
  const current = encodeURIComponent(token());
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}access_token=${current}`;
}
