import { Router, type Request, type Response, type NextFunction } from 'express';

import { validateUrl, type ValidatedRequest } from '../middlewares/validateUrl';
import { fetchInfo, YtDlpError } from '../services/ytdlp.service';
import { logger } from '../utils/logger';

const log = logger.child('route:fetch-info');

export const fetchInfoRouter = Router();

fetchInfoRouter.post(
  '/fetch-info',
  validateUrl,
  async (req: Request, res: Response, next: NextFunction) => {
    const { url, platform } = (req as ValidatedRequest).validated;
    try {
      const info = await fetchInfo(url, platform);
      const formats = info.formats.slice(0, 30).map((f) => ({
        id: f.id,
        ext: f.ext,
        resolution: f.resolution,
        width: f.width,
        height: f.height,
        fps: f.fps,
        filesize: f.filesize,
        videoOnly: f.videoOnly,
        audioOnly: f.audioOnly,
        note: f.note,
      }));
      res.json({
        success: true,
        data: {
          id: info.id,
          title: info.title,
          thumbnail: info.thumbnail,
          duration: info.duration,
          uploader: info.uploader,
          platform: info.platform,
          url: info.url,
          formats,
        },
      });
    } catch (err) {
      if (err instanceof YtDlpError) {
        log.warn('fetch-info failed', { code: err.code, url });
        return next(err);
      }
      log.error('fetch-info crashed', { error: (err as Error).message });
      next(err);
    }
  },
);
