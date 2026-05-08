import type { ErrorRequestHandler, NextFunction, Request, Response } from 'express';

import { YtDlpError } from '../services/ytdlp.service';
import { logger } from '../utils/logger';

const log = logger.child('error');

export const errorHandler: ErrorRequestHandler = (
  err: Error,
  _req: Request,
  res: Response,
  _next: NextFunction,
) => {
  if (res.headersSent) {
    log.warn('error after headers sent', { error: err.message });
    return;
  }
  if (err instanceof YtDlpError) {
    res.status(422).json({
      success: false,
      error: err.code,
      message: err.message,
    });
    return;
  }
  log.error('unhandled error', { error: err.message, stack: err.stack });
  res.status(500).json({
    success: false,
    error: 'INTERNAL_ERROR',
    message: 'An internal error occurred. Please try again.',
  });
};

export function notFoundHandler(_req: Request, res: Response): void {
  res.status(404).json({
    success: false,
    error: 'NOT_FOUND',
    message: 'Endpoint not found.',
  });
}
