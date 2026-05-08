import { createReadStream } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { Router, type NextFunction, type Request, type Response } from 'express';

import { config } from '../config';
import { scheduleFileDeletion } from '../services/cleanup.service';
import { getJobProgress } from '../services/queue.service';
import { logger } from '../utils/logger';

const log = logger.child('route:file');
const JOB_ID_RE = /^[A-Za-z0-9_-]{6,32}$/;

export const fileRouter = Router();

fileRouter.get(
  '/file/:jobId',
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
      if (!progress || progress.status !== 'complete' || !progress.filePath) {
        res.status(404).json({
          success: false,
          error: 'NOT_READY',
          message: 'File is not ready or has expired.',
        });
        return;
      }

      const filePath = path.resolve(progress.filePath);
      if (!filePath.startsWith(config.tempDir)) {
        res.status(403).json({
          success: false,
          error: 'FORBIDDEN',
          message: 'Access denied.',
        });
        return;
      }

      let stat: Awaited<ReturnType<typeof fs.stat>>;
      try {
        stat = await fs.stat(filePath);
      } catch {
        res.status(404).json({
          success: false,
          error: 'FILE_GONE',
          message: 'The file is no longer available.',
        });
        return;
      }

      const total = stat.size;
      const filename = progress.filename ?? path.basename(filePath);
      const safeFilename = filename.replace(/[^A-Za-z0-9._-]/g, '_');
      const contentType = guessContentType(filename);

      res.setHeader('Content-Type', contentType);
      res.setHeader('Accept-Ranges', 'bytes');
      res.setHeader(
        'Content-Disposition',
        `attachment; filename="${safeFilename}"`,
      );
      res.setHeader('Cache-Control', 'no-store');

      const range = req.headers.range;
      if (range) {
        const m = /^bytes=(\d*)-(\d*)$/.exec(range);
        if (!m) {
          res.status(416).end();
          return;
        }
        const startStr = m[1];
        const endStr = m[2];
        const start = startStr ? Number.parseInt(startStr, 10) : 0;
        const end = endStr ? Number.parseInt(endStr, 10) : total - 1;
        if (
          !Number.isFinite(start) ||
          !Number.isFinite(end) ||
          start < 0 ||
          end >= total ||
          start > end
        ) {
          res.status(416).setHeader('Content-Range', `bytes */${total}`).end();
          return;
        }
        res.status(206);
        res.setHeader('Content-Range', `bytes ${start}-${end}/${total}`);
        res.setHeader('Content-Length', String(end - start + 1));
        const stream = createReadStream(filePath, { start, end });
        stream.on('error', (err) => {
          log.error('range stream error', { error: err.message });
          res.destroy(err);
        });
        stream.pipe(res);
      } else {
        res.setHeader('Content-Length', String(total));
        const stream = createReadStream(filePath);
        stream.on('error', (err) => {
          log.error('stream error', { error: err.message });
          res.destroy(err);
        });
        stream.pipe(res);
      }

      void scheduleFileDeletion(filePath, jobId);
    } catch (err) {
      next(err);
    }
  },
);

function guessContentType(filename: string): string {
  const ext = path.extname(filename).toLowerCase();
  switch (ext) {
    case '.mp4':
    case '.m4v':
      return 'video/mp4';
    case '.webm':
      return 'video/webm';
    case '.mkv':
      return 'video/x-matroska';
    case '.mov':
      return 'video/quicktime';
    case '.m4a':
      return 'audio/mp4';
    case '.mp3':
      return 'audio/mpeg';
    default:
      return 'application/octet-stream';
  }
}
