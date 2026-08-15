const rawApiUrl = import.meta.env.VITE_API_URL;

// All authenticated API fetch calls go through /api (Render rewrite → backend).
// This ensures cookies are same-origin and never hit CDN caching issues.
export const API_URL = '/api';

// Direct backend URL used ONLY for the OAuth login redirect.
// Must bypass Render's CDN proxy because Cloudflare caches 302 redirects,
// turning subsequent login clicks into a blank 304 Not Modified page.
const rawBackendUrl = import.meta.env.VITE_BACKEND_URL;
export const BACKEND_URL = (rawBackendUrl && rawBackendUrl !== 'undefined' && rawBackendUrl.trim() !== '')
  ? rawBackendUrl.replace(/\/+$/, '')
  : (typeof window !== 'undefined' && window.location.hostname.includes('onrender.com')
      ? 'https://ai-pull-request-agent-api.onrender.com'
      : 'http://localhost:8000');


export async function apiFetch(endpoint, options = {}) {
  const url = endpoint.startsWith('http') ? endpoint : `${API_URL}${endpoint}`;
  
  const headers = {
    'Accept': 'application/json',
    ...options.headers,
  };

  // If payload is object and not FormData, stringify
  let body = options.body;
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(body);
  }

  const config = {
    ...options,
    headers,
    body,
    credentials: 'include', // Ensures HttpOnly cookies are sent cross-origin
  };

  try {
    const response = await fetch(url, config);

    // Handle 401 Unauthorized globally if needed or pass back to caller
    if (response.status === 401) {
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
