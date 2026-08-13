import React from 'react';
import { NavLink, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Layout({ children }) {
  const { user, logout } = useAuth();

  return (
    <div className="app-container">
      <aside className="sidebar">
        <Link to="/dashboard" className="sidebar-logo">
          <div className="sidebar-logo-icon">AI</div>
          <span>PR Agent</span>
        </Link>

        <nav className="sidebar-nav">
          <NavLink
            to="/dashboard"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            📊 Dashboard
          </NavLink>
          <NavLink
            to="/repositories"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            📦 Repositories
          </NavLink>
          <NavLink
            to="/settings"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            ⚙️ Settings
          </NavLink>
        </nav>

        {user && (
          <div className="sidebar-footer">
            <div className="user-profile-btn" style={{ justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden' }}>
                <img
                  src={user.github_avatar_url || 'https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png'}
                  alt={user.github_username}
                  className="avatar avatar-sm"
                />
                <span style={{ fontWeight: 500, fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  @{user.github_username}
                </span>
              </div>
              <button
                onClick={logout}
                title="Logout"
                style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', padding: '0.2rem 0.4rem', borderRadius: '4px' }}
                onMouseEnter={(e) => e.target.style.color = 'var(--accent-red)'}
                onMouseLeave={(e) => e.target.style.color = 'var(--text-secondary)'}
              >
                Logout
              </button>
            </div>
          </div>
        )}
      </aside>

      <main className="main-content">
        {children}
      </main>
    </div>
  );
}
