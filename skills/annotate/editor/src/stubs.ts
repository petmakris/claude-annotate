/**
 * The two dashboard helpers the copied editor files import, so livePreview.ts
 * and source.ts stay the dashboard's files apart from their import lines.
 */

/** The four tones a callout can carry. */
export type CalloutTone = 'stop' | 'warn' | 'ok' | 'info';

/** Copied verbatim from the dashboard's `lib/taskBody.ts`: a leading marker
 *  glyph in the first 120 characters, mapped to the tone it means. Unmarked
 *  returns null, so a plain quotation stays plain. */
export function calloutTone(text: string): CalloutTone | null {
  const head = text.slice(0, 120);
  if (head.includes('⛔') || head.includes('🔴')) return 'stop';
  if (head.includes('⚠')) return 'warn';       // covers ⚠ and ⚠️
  if (head.includes('✅')) return 'ok';
  if (head.includes('ℹ')) return 'info';       // covers ℹ and ℹ️
  return null;
}

/** `ABC-274`, `RDMP-12`, `EL-8835`: kept so ticket keys get their style. */
export const TICKET_KEY_RE = /\b([A-Z][A-Z0-9]+-\d+)\b/g;
