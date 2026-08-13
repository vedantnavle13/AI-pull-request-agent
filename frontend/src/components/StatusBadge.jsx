import React from 'react';

export default function StatusBadge({ status, type = 'status' }) {
  if (!status) return null;

  const normalized = String(status).toLowerCase();
  
  if (type === 'severity') {
    const classMap = {
      critical: 'badge-critical',
      high: 'badge-high',
      medium: 'badge-medium',
      low: 'badge-low',
      info: 'badge-info',
    };
    const badgeClass = classMap[normalized] || 'badge-info';
    return <span className={`badge ${badgeClass}`}>{status}</span>;
  }

  // Type === 'status'
  let badgeClass = 'badge-queued';
  let label = status;

  switch (normalized) {
    case 'completed':
      badgeClass = 'badge-completed';
      label = 'Completed';
      break;
    case 'processing':
    case 'ai_reviewing':
    case 'validating':
    case 'policy_decision':
    case 'publishing':
      badgeClass = 'badge-processing';
      label = 'Processing';
      break;
    case 'failed':
    case 'dead_letter':
      badgeClass = 'badge-failed';
      label = 'Failed';
      break;
    case 'queued':
      badgeClass = 'badge-queued';
      label = 'Queued';
      break;
    default:
      badgeClass = 'badge-info';
      break;
  }

  return <span className={`badge ${badgeClass}`}>{label}</span>;
}
