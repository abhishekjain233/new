import rateLimit from 'express-rate-limit';

import { config } from '../config';

export const apiRateLimiter = rateLimit({
  windowMs: config.rateLimitWindowMs,
  max: config.rateLimitMax,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: {
    success: false,
    error: 'RATE_LIMITED',
    message: 'Too many requests. Please slow down and try again shortly.',
  },
});

export const fileRateLimiter = rateLimit({
  windowMs: config.rateLimitWindowMs,
  max: Math.max(config.rateLimitMax * 2, 40),
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: {
    success: false,
    error: 'RATE_LIMITED',
    message: 'Too many requests. Please slow down and try again shortly.',
  },
});
