import React from 'react';
import { useSearchParams, Link } from 'react-router-dom';

export default function AuthError() {
  const [searchParams] = useSearchParams();
  const reason = searchParams.get('reason') || searchParams.get('error') || 'Authentication failed';

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--bg-dark)', padding: '1.5rem' }}>
      <div className="error-state" style={{ maxWidth: '420px', width: '100%' }}>
        <div className="error-state-icon">⚠️</div>
        <h3>Authentication Failed</h3>
        <p style={{ color: 'var(--accent-red)', fontSize: '0.9rem', marginBottom: '1.5rem' }}>
          {reason}
        </p>
        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
          <Link to="/login" className="btn btn-primary">
            Try Again
          </Link>
          <Link to="/" className="btn btn-secondary">
            Go Home
          </Link>
        </div>
      </div>
    </div>
  );
}
