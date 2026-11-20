import React from 'react';

export function BrandLogo({ className = "w-5 h-5" }) {
  const id = React.useId();

  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <defs>
        <linearGradient id={id} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#8AB4F8" />
          <stop offset="100%" stopColor="#4285F4" />
        </linearGradient>
      </defs>
      {/* Sleek architectural skyline & luxury property silhouette */}
      <path
        d="M3 21H21"
        stroke={`url(#${id})`}
        strokeWidth="1.75"
        strokeLinecap="round"
      />
      <path
        d="M5 21V7.5L12 3.5V21"
        stroke={`url(#${id})`}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M12 11L19 14.5V21"
        stroke={`url(#${id})`}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="8.5" cy="9.5" r="0.75" fill={`url(#${id})`} />
      <circle cx="8.5" cy="13" r="0.75" fill={`url(#${id})`} />
      <circle cx="8.5" cy="16.5" r="0.75" fill={`url(#${id})`} />
      <circle cx="15.5" cy="17" r="0.75" fill={`url(#${id})`} />
    </svg>
  );
}
