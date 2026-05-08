import type { NextFunction, Request, Response } from 'express';

import { detectPlatform, isPlatformAllowed } from '../utils/detectPlatform';

const MAX_URL_LENGTH = 2048;

export interface ValidatedRequest extends Request {
  validated: {
    url: string;
    platform: ReturnType<typeof detectPlatform> & string;
  };
}

export function validateUrl(req: Request, res: Response, next: NextFunction): void {
  const body = (req.body ?? {}) as { url?: unknown; platform?: unknown };
  const rawUrl = typeof body.url === 'string' ? body.url.trim() : '';
  const rawPlatform = typeof body.platform === 'string' ? body.platform.trim().toLowerCase() : '';

  if (!rawUrl || rawUrl.length > MAX_URL_LENGTH) {
    res.status(400).json({
      success: false,
      error: 'INVALID_URL',
      message: 'Missing or invalid URL.',
    });
    return;
  }

  const detected = detectPlatform(rawUrl);
  if (!detected) {
    res.status(400).json({
      success: false,
      error: 'UNSUPPORTED_PLATFORM',
      message: 'The provided URL is not from a supported platform.',
    });
    return;
  }

  if (rawPlatform && rawPlatform !== detected) {
    res.status(400).json({
      success: false,
      error: 'PLATFORM_MISMATCH',
      message: `URL appears to be a ${detected} link, not ${rawPlatform}.`,
    });
    return;
  }

  if (rawPlatform && !isPlatformAllowed(rawPlatform)) {
    res.status(400).json({
      success: false,
      error: 'UNSUPPORTED_PLATFORM',
      message: 'The provided platform is not supported.',
    });
    return;
  }

  (req as ValidatedRequest).validated = { url: rawUrl, platform: detected };
  next();
}
