import React from 'react';

export default function Spinner({ message = 'Loading...' }) {
  return (
    <div className="spinner-container">
      <div className="spinner"></div>
      {message && <p>{message}</p>}
    </div>
  );
}
