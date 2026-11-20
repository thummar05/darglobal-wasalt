/**
 * Utilities for RTL and Arabic language support
 */

// Arabic unicode character ranges
export const ARABIC_REGEX = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;

/**
 * Checks whether text contains Arabic characters.
 */
export function isArabicText(text) {
  if (!text || typeof text !== 'string') return false;
  return ARABIC_REGEX.test(text);
}

/**
 * Returns 'rtl' if text is predominantly Arabic, else 'ltr'.
 */
export function getTextDirection(text) {
  return isArabicText(text) ? 'rtl' : 'ltr';
}

/**
 * Returns appropriate font family class based on language.
 */
export function getFontFamilyClass(text) {
  return isArabicText(text) ? 'font-arabic' : 'font-sans';
}
