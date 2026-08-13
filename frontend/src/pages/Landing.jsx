import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Landing() {
  const { isAuthenticated, login } = useAuth();

  return (
    <div style={{ minHeight: '100vh', backgroundColor: 'var(--bg-dark)', color: 'var(--text-primary)' }}>
      {/* Top Navbar */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '1.5rem 2.5rem', borderBottom: '1px solid var(--border-color)', maxWidth: '1200px', margin: '0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', fontWeight: 700, fontSize: '1.2rem' }}>
          <div className="sidebar-logo-icon">AI</div>
          <span>AI Pull Request Agent</span>
        </div>
        <div>
          {isAuthenticated ? (
            <Link to="/dashboard" className="btn btn-primary">
              Go to Dashboard →
            </Link>
          ) : (
            <button type="button" onClick={(e) => { e.preventDefault(); login(); }} className="btn btn-github">
              <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
              </svg>
              Sign in with GitHub
            </button>
          )}
        </div>
      </header>

      {/* Hero Section */}
      <section style={{ textAlign: 'center', padding: '5rem 1.5rem', maxWidth: '800px', margin: '0 auto' }}>
        <div className="badge badge-info" style={{ marginBottom: '1.5rem', fontSize: '0.8rem', padding: '0.4rem 0.8rem' }}>
          🤖 Multi-Tenant AI Code Reviewer
        </div>
        <h1 style={{ fontSize: '3rem', fontWeight: 800, lineHeight: 1.15, marginBottom: '1.5rem', letterSpacing: '-0.03em' }}>
          AI-Powered Pull Request Reviews
        </h1>
        <p style={{ fontSize: '1.2rem', color: 'var(--text-secondary)', marginBottom: '2.5rem', lineHeight: 1.6 }}>
          Automatically review your GitHub pull requests with AI. Connect your repositories and let our intelligent multi-agent pipeline detect bugs, security flaws, and performance bottlenecks on every commit.
        </p>

        <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem', flexWrap: 'wrap' }}>
          {isAuthenticated ? (
            <Link to="/dashboard" className="btn btn-primary btn-lg">
              Open Dashboard →
            </Link>
          ) : (
            <button type="button" onClick={(e) => { e.preventDefault(); login(); }} className="btn btn-primary btn-lg">
              <svg height="20" width="20" viewBox="0 0 16 16" fill="currentColor">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
              </svg>
              Login with GitHub
            </button>
          )}
        </div>
      </section>

      {/* Feature Cards Grid */}
      <section style={{ maxWidth: '1100px', margin: '0 auto', padding: '0 1.5rem 5rem 1.5rem' }}>
        <div className="grid-2">
          <div className="card" style={{ padding: '2rem' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '0.75rem' }}>⚡</div>
            <h3 className="card-title">AI Code Review</h3>
            <p className="card-subtitle" style={{ fontSize: '0.95rem', lineHeight: 1.5 }}>
              Multi-agent LangGraph analysis identifies bugs, edge cases, and architectural smells before code reaches production.
            </p>
          </div>

          <div className="card" style={{ padding: '2rem' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '0.75rem' }}>🔗</div>
            <h3 className="card-title">Automatic GitHub Integration</h3>
            <p className="card-subtitle" style={{ fontSize: '0.95rem', lineHeight: 1.5 }}>
              Seamless GitHub App webhook integration post comments directly on your pull requests in real time.
            </p>
          </div>

          <div className="card" style={{ padding: '2rem' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '0.75rem' }}>🔒</div>
            <h3 className="card-title">Multi-Repository Support</h3>
            <p className="card-subtitle" style={{ fontSize: '0.95rem', lineHeight: 1.5 }}>
              Isolated multi-user architecture guarantees strict data separation across organization and personal repositories.
            </p>
          </div>

          <div className="card" style={{ padding: '2rem' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '0.75rem' }}>📜</div>
            <h3 className="card-title">Review History & Audit Trail</h3>
            <p className="card-subtitle" style={{ fontSize: '0.95rem', lineHeight: 1.5 }}>
              Track review statuses, finding severity levels, and automated checks in a central SaaS dashboard.
            </p>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{ borderTop: '1px solid var(--border-color)', padding: '2rem 1.5rem', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '0.85rem' }}>
        AI Pull Request Agent &copy; {new Date().getFullYear()}. Multi-User SaaS Platform.
      </footer>
    </div>
  );
}
