import React, { useEffect, useState } from 'react';
import { useParams, useSearchParams, Link } from 'react-router-dom';
import Layout from '../components/Layout';
import { apiFetch } from '../api/client';
import Spinner from '../components/Spinner';
import StatusBadge from '../components/StatusBadge';
import FindingCard from '../components/FindingCard';

export default function ReviewDetail() {
  const { owner, repo, prNumber } = useParams();
  const [searchParams] = useSearchParams();
  const shaQuery = searchParams.get('sha');

  const fullName = `${owner}/${repo}`;

  const [review, setReview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchReviewDetails = async () => {
    setLoading(true);
    setError(null);
    try {
      let targetSha = shaQuery;

      // If SHA wasn't passed in query, get the latest review for this PR from user reviews
      if (!targetSha) {
        const userReviews = await apiFetch(`/user/reviews?repository=${encodeURIComponent(fullName)}`);
        const matchingPr = (userReviews.reviews || []).find((r) => String(r.pr_number) === String(prNumber));
        if (matchingPr) {
          targetSha = matchingPr.commit_sha;
        }
      }

      if (!targetSha) {
        setError(`No review run found for PR #${prNumber} on ${fullName}`);
        setLoading(false);
        return;
      }

      // Fetch review detail using existing GET /reviews/{repo}/{pr_number}/{commit_sha} endpoint
      const data = await apiFetch(`/reviews/${fullName}/${prNumber}/${targetSha}`);
      if (data.status === 'not_found') {
        setError('Review data not found.');
      } else {
        setReview({ ...data, commit_sha: targetSha });
      }
    } catch (err) {
      console.error('Failed to fetch review detail:', err);
      setError(err.message || 'Failed to load review details');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReviewDetails();
  }, [owner, repo, prNumber, shaQuery]);

  const findings = review?.findings || [];
  const status = review?.status || 'QUEUED';
  const decision = review?.decision;
  const githubPrUrl = `https://github.com/${fullName}/pull/${prNumber}`;

  return (
    <Layout>
      <div className="page-header">
        <div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
            <Link to={`/repositories/${owner}/${repo}`}>← Back to {fullName}</Link>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <h1 className="page-title">PR #{prNumber} Review</h1>
            <StatusBadge status={status} />
            {decision && <span className="badge badge-info">Decision: {decision}</span>}
          </div>
          <p className="page-subtitle" style={{ marginTop: '0.5rem' }}>
            Repository: <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{fullName}</span> | Commit:{' '}
            <span className="code-inline">{review?.commit_sha?.substring(0, 7) || 'N/A'}</span>
          </p>
        </div>
        <div>
          <a
            href={githubPrUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="btn btn-secondary"
          >
            View PR on GitHub ↗
          </a>
        </div>
      </div>

      {loading ? (
        <Spinner message="Loading AI review details..." />
      ) : error ? (
        <div className="error-state">
          <div className="error-state-icon">⚠️</div>
          <h3>Unable to load AI review</h3>
          <p>{error}</p>
          <button onClick={fetchReviewDetails} className="btn btn-secondary">
            Retry
          </button>
        </div>
      ) : (
        <div>
          {/* Status Alert Banner if Processing or Failed */}
          {status === 'QUEUED' && (
            <div className="card" style={{ backgroundColor: 'rgba(139, 148, 158, 0.1)', borderColor: 'rgba(139, 148, 158, 0.3)', marginBottom: '1.5rem' }}>
              ⏳ <strong>AI Review Queued:</strong> This pull request is queued for automated analysis.
            </div>
          )}

          {(status === 'PROCESSING' || status === 'AI_REVIEWING' || status === 'VALIDATING') && (
            <div className="card" style={{ backgroundColor: 'rgba(210, 153, 34, 0.1)', borderColor: 'rgba(210, 153, 34, 0.3)', marginBottom: '1.5rem' }}>
              ⚡ <strong>AI Review in Progress:</strong> The multi-agent pipeline is analyzing code changes...
            </div>
          )}

          {(status === 'FAILED' || status === 'DEAD_LETTER') && (
            <div className="card" style={{ backgroundColor: 'rgba(248, 81, 73, 0.1)', borderColor: 'rgba(248, 81, 73, 0.3)', marginBottom: '1.5rem' }}>
              ❌ <strong>Review Failed:</strong> {review?.error_message || 'An error occurred during review processing.'}
            </div>
          )}

          {/* Findings List */}
          <div style={{ marginBottom: '1.5rem' }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>AI Findings & Feedback</span>
              <span className="badge badge-info">{findings.length}</span>
            </h2>

            {status === 'COMPLETED' && findings.length === 0 ? (
              <div className="empty-state">
                <div className="empty-state-icon">🎉</div>
                <h3>No Issues Found</h3>
                <p>AI review completed successfully. No critical bugs, performance issues, or security flaws were detected.</p>
              </div>
            ) : (
              <div>
                {findings.map((item, idx) => (
                  <FindingCard key={idx} finding={item} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </Layout>
  );
}
