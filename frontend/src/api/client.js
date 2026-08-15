// Direct backend URL — used for OAuth login redirect (bypasses Render CDN proxy).
// GitHub OAuth callback is also on the backend directly (not the Render proxy).
const rawBackendUrl = import.meta.env.VITE_BACKEND_URL;
export const BACKEND_URL = (rawBackendUrl && rawBackendUrl !== 'undefined' && rawBackendUrl.trim() !== '')
  ? rawBackendUrl.replace(/\/+$/, '')
  : (typeof window !== 'undefined' && window.location.hostname.includes('onrender.com')
      ? 'https://ai-pull-request-agent-api.onrender.com'
      : 'http://localhost:8000');

// All non-OAuth API calls go through the same BACKEND_URL.
// We use Authorization: Bearer header — no cross-origin cookies needed.
export const API_URL = BACKEND_URL;

// ---------------------------------------------------------------------------
// Token storage (localStorage) — survives page refresh, works cross-tab
// ---------------------------------------------------------------------------
const TOKEN_KEY = 'ai_pr_agent_token';

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}

export function setToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token); } catch {}
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch {}
}

// ---------------------------------------------------------------------------
// API fetch — sends Authorization: Bearer token on every authenticated request
// ---------------------------------------------------------------------------
export async function apiFetch(endpoint, options = {}) {
  const url = endpoint.startsWith('http') ? endpoint : `${API_URL}${endpoint}`;

  const token = getToken();
  const headers = {
    'Accept': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    ...options.headers,
  };

  let body = options.body;
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(body);
  }

  const config = {
    ...options,
    headers,
    body,
    // Keep credentials:include so existing HttpOnly cookies still work
    // for any session that was set before this migration.
    credentials: 'include',
  };

  try {
    const response = await fetch(url, config);

    if (response.status === 401) {
      clearToken(); // Token invalid — clear stored token
      const data = await response.json().catch(() => ({}));
      const error = new Error(data.detail || 'Unauthorized');
      error.status = 401;
      error.data = data;
      throw error;
    }

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(data.detail || `HTTP Error ${response.status}`);
      error.status = response.status;
      error.data = data;
      throw error;
    }

    return await response.json();
  } catch (err) {
    throw err;
  }
}
