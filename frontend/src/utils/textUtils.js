/**
 * Utility functions for text analysis, RTL detection, and session management.
 */

// Arabic Unicode range detector
export function isArabicText(text) {
  if (!text || typeof text !== 'string') return false;
  // Arabic Unicode block: \u0600-\u06FF, \u0750-\u077F, \u08A0-\u08FF, \uFB50-\uFDFF, \uFE70-\uFEFF
  const arabicRegex = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;
  return arabicRegex.test(text);
}

export function generateSessionId() {
  return `session_${Math.random().toString(36).substring(2, 10)}_${Date.now().toString(36)}`;
}

export function formatTime(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
