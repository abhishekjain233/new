import { randomBytes } from 'node:crypto';

/**
 * Generates a short, URL-safe identifier for download jobs. We avoid full UUIDs
 * to keep filenames short and friendly when downloaded by the client.
 */
export function generateJobId(): string {
  return randomBytes(9).toString('base64url');
}
