import React from 'react';
import StatusBadge from './StatusBadge';

export default function FindingCard({ finding }) {
  if (!finding) return null;

  const {
    severity = 'INFO',
    category,
    title,
    description,
    file,
    line,
    suggestion,
  } = finding;

  return (
    <div className="card" style={{ borderLeft: `4px solid var(--severity-${severity.toLowerCase()}, #8b949e)` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem', gap: '0.5rem' }}>
        <h4 style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--text-primary)' }}>
          {title || 'Finding'}
        </h4>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {category && <span className="badge badge-info">{category}</span>}
          <StatusBadge status={severity} type="severity" />
        </div>
      </div>

      {file && (
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
          📄 <span className="code-inline">{file}{line ? `:${line}` : ''}</span>
        </div>
      )}

      {description && (
        <p style={{ color: 'var(--text-primary)', fontSize: '0.9rem', marginBottom: '0.75rem', lineHeight: '1.5' }}>
          {description}
        </p>
      )}

      {suggestion && (
        <div style={{ marginTop: '0.75rem', padding: '0.75rem', backgroundColor: 'var(--bg-surface)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-muted)' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-green)', marginBottom: '0.25rem', textTransform: 'uppercase' }}>
            Suggested Fix
          </div>
          <pre style={{ fontFamily: 'var(--font-mono)', fontSize: '0.85rem', color: '#e6edf3', overflowX: 'auto', margin: 0, whiteSpace: 'pre-wrap' }}>
            {suggestion}
          </pre>
        </div>
      )}
    </div>
  );
}
