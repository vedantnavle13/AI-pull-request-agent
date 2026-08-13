import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Spinner from '../components/Spinner';

export default function AuthCallback() {
  const { refreshUser } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    async function handleAuth() {
      await refreshUser();
      navigate('/dashboard', { replace: true });
    }
    handleAuth();
  }, [refreshUser, navigate]);

  return <Spinner message="Completing authentication..." />;
}
