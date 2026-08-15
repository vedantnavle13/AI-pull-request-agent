import React, { createContext, useContext, useState, useEffect } from 'react';
import { apiFetch, API_URL, BACKEND_URL } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [appInfo, setAppInfo] = useState(null);

  const refreshUser = async () => {
    try {
      setLoading(true);
      console.log('[AuthContext] Checking /user/me');
      const data = await apiFetch('/user/me');
      console.log('[AuthContext] /user/me status: 200 OK — authenticated as @', data?.github_username);
      setUser(data);
    } catch (err) {
      const status = err.status || (err.message && err.message.includes('401') ? 401 : 'unknown');
      console.log('[AuthContext] /user/me status:', status);
      if (status === 401) {
        console.log('[AuthContext] /user/me 401 — session cookie not accepted or user unauthenticated');
      }
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const fetchAppInfo = async () => {
    try {
      const data = await apiFetch('/auth/github/app-info');
      setAppInfo(data);
    } catch (err) {
      console.warn('Could not fetch GitHub app info:', err);
    }
  };

  useEffect(() => {
    refreshUser();
    fetchAppInfo();
  }, []);

  const login = () => {
    // Navigate DIRECTLY to the backend for OAuth — bypasses Render CDN proxy.
    // Render's Cloudflare CDN caches 302 redirects, causing blank pages on
    // subsequent login clicks. Going to the backend directly avoids this.
    // The OAuth callback is set to the frontend domain so Set-Cookie lands
    // on the correct host for same-origin cookie access.
    const oauthUrl = `${BACKEND_URL}/auth/github/login`;
    console.log('[Login] Navigating directly to backend OAuth:', oauthUrl);
    window.location.assign(oauthUrl);
  };

  const logout = async () => {
    try {
      await apiFetch('/auth/logout', { method: 'POST' });
    } catch (err) {
      console.error('Logout error:', err);
    } finally {
      setUser(null);
      window.location.href = '/';
    }
  };

  const value = {
    user,
    loading,
    isAuthenticated: !!user,
    login,
    logout,
    refreshUser,
    appInfo,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
