import React, { createContext, useContext, useState, useEffect } from 'react';
import { apiFetch } from '../api/client';

const AuthContext = createContext(null);

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [appInfo, setAppInfo] = useState(null);

  const refreshUser = async () => {
    try {
      setLoading(true);
      const data = await apiFetch('/user/me');
      setUser(data);
    } catch (err) {
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
    window.location.href = `${API_URL}/auth/github/login`;
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
