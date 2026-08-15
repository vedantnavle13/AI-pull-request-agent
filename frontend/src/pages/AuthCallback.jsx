import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { setToken } from '../api/client';
import { useAuth } from '../context/AuthContext';
import Spinner from '../components/Spinner';

/**
 * OAuth callback landing page.
 *
 * The backend redirects here after successful GitHub OAuth with:
 *   /auth/callback?token=<JWT>[&installation=success]
 *
 * This page:
 * 1. Reads the token from the URL query string
 * 2. Stores it in localStorage (via setToken)
 * 3. Clears the token from the URL (security: no token in browser history)
 * 4. Calls refreshUser to load the user profile
 * 5. Navigates to /dashboard
 */
export default function AuthCallback() {
  const { refreshUser } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState(null);

  useEffect(() => {
    async function handleAuth() {
      const token = searchParams.get('token');
      const authError = searchParams.get('error');

      if (authError) {
        setError(authError);
        setTimeout(() => navigate('/login', { replace: true }), 3000);
        return;
      }

      if (!token) {
        console.error('[AuthCallback] No token in URL');
        setError('No authentication token received. Please try logging in again.');
        setTimeout(() => navigate('/login', { replace: true }), 3000);
        return;
      }

      // Store the token
      setToken(token);
      console.log('[AuthCallback] Token stored in localStorage');

      // Clear the token from the URL (so it's not in browser history)
      window.history.replaceState({}, '', '/auth/callback');

      // Refresh user data using the stored token
      await refreshUser();

      // Navigate to dashboard
      navigate('/dashboard', { replace: true });
    }

    handleAuth();
  }, []); // Run once on mount — intentionally no deps to avoid double execution

  if (error) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        color: '#e74c3c',
        fontFamily: 'system-ui, sans-serif',
        background: '#0a0a0f',
      }}>
        <h2>Authentication Error</h2>
        <p>{error}</p>
        <p style={{ color: '#888', fontSize: '14px' }}>Redirecting to login...</p>
      </div>
    );
  }

  return <Spinner message="Completing authentication..." />;
}
