import { Router, type NextFunction, type Request, type Response } from 'express';

import { validateUrl, type ValidatedRequest } from '../middlewares/validateUrl';
import { enqueueDownload } from '../services/queue.service';
import { generateJobId } from '../utils/generateJobId';
import { logger } from '../utils/logger';

const log = logger.child('route:download');

export const downloadRouter = Router();

downloadRouter.post(
  '/download',
  validateUrl,
  async (req: Request, res: Response, next: NextFunction) => {
    const { url, platform } = (req as ValidatedRequest).validated;
    const formatId =
      typeof req.body?.formatId === 'string' && req.body.formatId.trim().length > 0
        ? String(req.body.formatId).trim()
        : undefined;

    const jobId = generateJobId();
    try {
      await enqueueDownload({
        jobId,
        url,
        platform,
        formatId,
        outputBasename: `fetch_${jobId}`,
      });
      log.info('enqueued download', { jobId, platform });
      res.status(202).json({
        success: true,
        data: { jobId },
      });
    } catch (err) {
      log.error('enqueue failed', { error: (err as Error).message });
      next(err);
    }
  },
);
