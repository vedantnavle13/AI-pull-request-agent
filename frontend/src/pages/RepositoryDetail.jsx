import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { apiFetch } from '../api/client';
import Spinner from '../components/Spinner';
import StatusBadge from '../components/StatusBadge';

export default function RepositoryDetail() {
  const { owner, repo } = useParams();
  const fullName = `${owner}/${repo}`;

  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchRepoReviews = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch(`/user/reviews?repository=${encodeURIComponent(fullName)}`);
      setReviews(data.reviews || []);
    } catch (err) {
      console.error('Failed to fetch repo reviews:', err);
      setError(err.message || 'Failed to load reviews for this repository');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRepoReviews();
  }, [owner, repo]);

  return (
    <Layout>
      <div className="page-header">
        <div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
            <Link to="/repositories">← Back to Repositories</Link>
          </div>
          <h1 className="page-title">{fullName}</h1>
          <p className="page-subtitle">Pull requests & AI reviews for this repository</p>
        </div>
        <div>
          <a
            href={`https://github.com/${fullName}`}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary"
          >
            View on GitHub ↗
          </a>
        </div>
      </div>

      {loading ? (
        <Spinner message="Loading repository reviews..." />
      ) : error ? (
        <div className="error-state">
          <div className="error-state-icon">⚠️</div>
          <h3>Unable to load reviews</h3>
          <p>{error}</p>
          <button onClick={fetchRepoReviews} className="btn btn-secondary">
            Retry
          </button>
        </div>
      ) : reviews.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🔍</div>
          <h3>No Reviews Found for {fullName}</h3>
          <p>
            Open or update a Pull Request on this repository to trigger an automated AI code review.
          </p>
        </div>
      ) : (
        <div>
          <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>
            Pull Requests ({reviews.length})
          </h2>

          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>PR #</th>
                  <th>Commit SHA</th>
                  <th>Review Status</th>
                  <th>Created</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {reviews.map((rev) => (
                  <tr key={rev.id}>
                    <td style={{ fontWeight: 600 }}>#{rev.pr_number}</td>
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
                        to={`/repositories/${owner}/${repo}/pulls/${rev.pr_number}?sha=${rev.commit_sha}`}
                        className="btn btn-secondary"
                        style={{ padding: '0.25rem 0.6rem', fontSize: '0.8rem' }}
                      >
                        View AI Review →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Layout>
  );
}
