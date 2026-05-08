import { Router, type NextFunction, type Request, type Response } from 'express';

import { getJobProgress } from '../services/queue.service';

export const progressRouter = Router();

const JOB_ID_RE = /^[A-Za-z0-9_-]{6,32}$/;

progressRouter.get(
  '/progress/:jobId',
  async (req: Request, res: Response, next: NextFunction) => {
    const { jobId } = req.params;
    if (!JOB_ID_RE.test(jobId)) {
      res.status(400).json({
        success: false,
        error: 'INVALID_JOB_ID',
        message: 'Invalid jobId.',
      });
      return;
    }
    try {
      const progress = await getJobProgress(jobId);
      if (!progress) {
        res.status(404).json({
          success: false,
          error: 'JOB_NOT_FOUND',
          message: 'No progress found for this jobId.',
        });
        return;
      }
      res.json({
        success: true,
        data: {
          jobId: progress.jobId,
          status: progress.status,
          progress: progress.progress,
          speed: progress.speed,
          eta: progress.eta,
          bytesDownloaded: progress.bytesDownloaded,
          bytesTotal: progress.bytesTotal,
          downloadUrl: progress.downloadUrl,
          filename: progress.filename,
          errorCode: progress.errorCode,
          errorMessage: progress.errorMessage,
        },
      });
    } catch (err) {
      next(err);
    }
  },
);
