import React, { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Spinner from '../components/Spinner';

export default function AuthSuccess() {
  const { refreshUser } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    async function init() {
      await refreshUser();
      navigate('/dashboard?installation=success', { replace: true });
    }
    init();
  }, [refreshUser, navigate]);

  return <Spinner message="GitHub App connected! Returning to dashboard..." />;
}
