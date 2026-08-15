import React, { createContext, useContext, useState, useEffect } from 'react';
import { apiFetch, BACKEND_URL, getToken, clearToken } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [appInfo, setAppInfo] = useState(null);

  const refreshUser = async () => {
    try {
      setLoading(true);
      // Only attempt if we have a stored token — avoids unnecessary 401s
      if (!getToken()) {
        setUser(null);
        return;
      }
      const data = await apiFetch('/user/me');
      console.log('[Auth] Authenticated as @', data?.github_username);
      setUser(data);
    } catch (err) {
      console.log('[Auth] /user/me failed:', err.status || err.message);
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
      console.warn('[Auth] Could not fetch app info:', err);
    }
  };

  useEffect(() => {
    refreshUser();
    fetchAppInfo();
  }, []);

  const login = () => {
    // Navigate directly to backend — bypasses Render CDN completely.
    // The CDN (Cloudflare) was caching OAuth redirects and returning
    // 304 Not Modified, causing blank pages. Direct backend call is immune.
    const oauthUrl = `${BACKEND_URL}/auth/github/login`;
    console.log('[Auth] Navigating to backend OAuth:', oauthUrl);
    window.location.assign(oauthUrl);
  };

  const logout = async () => {
    try {
      await apiFetch('/auth/logout', { method: 'POST' }).catch(() => {});
    } finally {
      clearToken();          // Remove JWT from localStorage
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
