import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../api/client';
import Spinner from '../components/Spinner';

export default function Settings() {
  const { user, logout, appInfo } = useAuth();
  const [installations, setInstallations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchInstallations = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch('/user/installations');
      setInstallations(data.installations || []);
    } catch (err) {
      console.error('Failed to load installations:', err);
      setError(err.message || 'Failed to load GitHub App installations');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchInstallations();
  }, []);

  const installUrl = appInfo?.install_url || (appInfo?.slug ? `https://github.com/apps/${appInfo.slug}/installations/new` : 'https://github.com/apps/aipullrequestagent/installations/new');

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Manage your account and GitHub App installations</p>
        </div>
      </div>

      {/* Account Profile Section */}
      <div className="card" style={{ marginBottom: '2rem' }}>
        <h2 className="card-title" style={{ marginBottom: '1.25rem' }}>GitHub Profile</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
          <img
            src={user?.github_avatar_url || 'https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png'}
            alt={user?.github_username}
            className="avatar avatar-lg"
          />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              @{user?.github_username}
            </div>
            {user?.email && (
              <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                ✉️ {user.email}
              </div>
            )}
            <div style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)', marginTop: '0.25rem' }}>
              Account ID: {user?.id}
            </div>
          </div>
          <div>
            <button onClick={logout} className="btn btn-danger">
              Sign Out
            </button>
          </div>
        </div>
      </div>

      {/* GitHub App Installations Section */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <h2 className="card-title">GitHub App Installations</h2>
            <p className="card-subtitle">Installations connected to your account</p>
          </div>
          <a
            href={installUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-primary"
          >
            + Add GitHub Installation
          </a>
        </div>

        {loading ? (
          <Spinner message="Loading installations..." />
        ) : error ? (
          <div className="error-state">
            <div className="error-state-icon">⚠️</div>
            <p>{error}</p>
            <button onClick={fetchInstallations} className="btn btn-secondary">
              Retry
            </button>
          </div>
        ) : installations.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🔌</div>
            <h3>No GitHub Installations Connected</h3>
            <p>Install the AI Pull Request Agent GitHub App on your account or organization to enable reviews.</p>
            <a
              href={installUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary"
            >
              Install GitHub App
            </a>
          </div>
        ) : (
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Type</th>
                  <th>Installation ID</th>
                  <th>Connected Date</th>
                </tr>
              </thead>
              <tbody>
                {installations.map((inst) => (
                  <tr key={inst.id}>
                    <td style={{ fontWeight: 600 }}>@{inst.account_login}</td>
                    <td>
                      <span className="badge badge-info">{inst.account_type}</span>
                    </td>
                    <td>
                      <span className="code-inline">{inst.installation_id}</span>
                    </td>
                    <td style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                      {inst.created_at ? new Date(inst.created_at).toLocaleDateString() : 'N/A'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
