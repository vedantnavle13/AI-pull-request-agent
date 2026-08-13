import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import Layout from '../components/Layout';
import { useAuth } from '../context/AuthContext';
import { apiFetch } from '../api/client';
import Spinner from '../components/Spinner';
import StatusBadge from '../components/StatusBadge';

export default function Dashboard() {
  const { user, appInfo } = useAuth();
  const [searchParams] = useSearchParams();
  const showBanner = searchParams.get('installation') === 'success';

  const [repos, setRepos] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [repoData, reviewData] = await Promise.all([
        apiFetch('/user/repositories'),
        apiFetch('/user/reviews?limit=10'),
      ]);
      setRepos(repoData.repositories || []);
      setReviews(reviewData.reviews || []);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
      setError(err.message || 'Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const installUrl = appInfo?.install_url || (appInfo?.slug ? `https://github.com/apps/${appInfo.slug}/installations/new` : 'https://github.com/apps/aipullrequestagent/installations/new');

  return (
    <Layout>
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Welcome back, @{user?.github_username}</p>
        </div>
        <div>
          <a
            href={installUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-primary"
          >
            <svg height="16" width="16" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
            Connect GitHub Repository
          </a>
        </div>
      </div>

      {showBanner && (
        <div style={{ backgroundColor: 'rgba(63, 185, 80, 0.15)', border: '1px solid rgba(63, 185, 80, 0.4)', color: '#3fb950', padding: '0.9rem 1.25rem', borderRadius: 'var(--radius-md)', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span>✅</span>
          <span>GitHub App connected successfully. Your repositories are synced.</span>
        </div>
      )}

      {loading ? (
        <Spinner message="Loading dashboard stats..." />
      ) : error ? (
        <div className="error-state">
          <div className="error-state-icon">⚠️</div>
          <h3>Unable to load dashboard data</h3>
          <p>{error}</p>
          <button onClick={fetchData} className="btn btn-secondary">
            Retry
          </button>
        </div>
      ) : (
        <>
          {/* Stat Boxes */}
          <div className="grid-2" style={{ marginBottom: '2rem' }}>
            <div className="stat-box">
              <div className="stat-label">Connected Repositories</div>
              <div className="stat-value">{repos.length}</div>
              <div style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
                <Link to="/repositories">Manage repositories →</Link>
              </div>
            </div>

            <div className="stat-box">
              <div className="stat-label">Total AI Reviews</div>
              <div className="stat-value">{reviews.length}</div>
              <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                {reviews.length > 0 ? 'Recent review runs' : 'No review runs yet'}
              </div>
            </div>
          </div>

          {/* Recent Reviews Table */}
          <div style={{ marginBottom: '2rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Recent Activity</h2>
              {reviews.length > 0 && (
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  Showing last {reviews.length} reviews
                </span>
              )}
            </div>

            {reviews.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">🤖</div>
                <h3>No PR Reviews Found</h3>
                <p>
                  Connect your GitHub repositories and open a Pull Request to trigger an automated AI review.
                </p>
                <a href={installUrl} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
                  Connect GitHub Repository
                </a>
              </div>
            ) : (
              <div className="table-container">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Repository</th>
                      <th>PR #</th>
                      <th>Commit SHA</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reviews.map((rev) => (
                      <tr key={rev.id}>
                        <td style={{ fontWeight: 600 }}>
                          <Link to={`/repositories/${rev.owner}/${rev.repo}`}>
                            {rev.full_name}
                          </Link>
                        </td>
                        <td>#{rev.pr_number}</td>
                        <td>
                          <span className="code-inline">{rev.commit_sha?.substring(0, 7)}</span>
                        </td>
                        <td>
                          <StatusBadge status={rev.status} />
                        </td>
                        <td style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                          {rev.created_at ? new Date(rev.created_at).toLocaleString() : 'N/A'}
                        </td>
                        <td>
                          <Link
                            to={`/repositories/${rev.owner}/${rev.repo}/pulls/${rev.pr_number}`}
                            className="btn btn-secondary"
                            style={{ padding: '0.25rem 0.6rem', fontSize: '0.8rem' }}
                          >
                            View Review →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </Layout>
  );
}
