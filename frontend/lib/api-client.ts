const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010/api/v1";
// Earlier versions kept the session token in localStorage; it now lives in an httpOnly cookie.
const LEGACY_TOKEN_KEY = "applypilot_token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function clearLegacyToken(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(LEGACY_TOKEN_KEY);
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers);
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!headers.has("Content-Type") && options.body && !isFormData) {
    headers.set("Content-Type", "application/json");
  }
  // Required by the API for cookie-authenticated writes (CSRF protection).
  headers.set("X-Requested-With", "ApplyPilot");

  const res = await fetch(`${API_URL}${path}`, { ...options, headers, credentials: "include" });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail)
        ? body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ") || detail
        : detail;
    } catch {
      // response had no JSON body
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}
