import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { apiFetch } from '../api/client';
import { useAuth } from '../context/AuthContext';
import Spinner from '../components/Spinner';

export default function Repositories() {
  const { appInfo } = useAuth();
  const [repositories, setRepositories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchRepositories = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch('/user/repositories');
      setRepositories(data.repositories || []);
    } catch (err) {
      console.error('Failed to fetch repositories:', err);
      setError(err.message || 'Unable to load repositories');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRepositories();
  }, []);

  const installUrl = appInfo?.install_url || (appInfo?.slug ? `https://github.com/apps/${appInfo.slug}/installations/new` : 'https://github.com/apps/aipullrequestagent/installations/new');

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Repositories</h1>
          <p className="page-subtitle">Repositories connected to your GitHub App installations</p>
        </div>
        <div>
          <a
            href={installUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-primary"
          >
            + Connect GitHub Repository
          </a>
        </div>
      </div>

      {loading ? (
        <Spinner message="Loading your repositories..." />
      ) : error ? (
        <div className="error-state">
          <div className="error-state-icon">⚠️</div>
          <h3>Unable to load repositories</h3>
          <p>{error}</p>
          <button onClick={fetchRepositories} className="btn btn-secondary">
            Retry
          </button>
        </div>
      ) : repositories.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">📦</div>
          <h3>No Repositories Connected</h3>
          <p>
            You haven't installed the GitHub App on any repository yet. Connect your repositories to get started with AI PR reviews.
          </p>
          <a
            href={installUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-primary btn-lg"
          >
            Connect GitHub Repository
          </a>
        </div>
      ) : (
        <div className="grid-2">
          {repositories.map((repo) => (
            <div key={repo.id} className="card" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                  <h3 className="card-title" style={{ fontSize: '1.1rem', margin: 0 }}>
                    <Link to={`/repositories/${repo.owner}/${repo.name}`}>
                      {repo.full_name}
                    </Link>
                  </h3>
                  <span className={`badge ${repo.private ? 'badge-medium' : 'badge-info'}`}>
                    {repo.private ? 'Private' : 'Public'}
                  </span>
                </div>

                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem', display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  <div>Account: <span style={{ color: 'var(--text-primary)' }}>{repo.account_login}</span></div>
                  <div>Default branch: <span className="code-inline">{repo.default_branch || 'main'}</span></div>
                </div>
              </div>

              <div style={{ paddingTop: '0.75rem', borderTop: '1px solid var(--border-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <a
                  href={`https://github.com/${repo.full_name}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}
                >
                  View on GitHub ↗
                </a>
                <Link
                  to={`/repositories/${repo.owner}/${repo.name}`}
                  className="btn btn-secondary"
                  style={{ fontSize: '0.8rem', padding: '0.3rem 0.75rem' }}
                >
                  View Reviews →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </Layout>
  );
}
