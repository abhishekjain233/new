import compression from 'compression';
import cors from 'cors';
import express, { type Express } from 'express';
import helmet from 'helmet';
import morgan from 'morgan';

import { config } from './config';
import { errorHandler, notFoundHandler } from './middlewares/errorHandler';
import { apiRateLimiter, fileRateLimiter } from './middlewares/rateLimiter';
import { downloadRouter } from './routes/download';
import { fetchInfoRouter } from './routes/fetchInfo';
import { fileRouter } from './routes/file';
import { progressRouter } from './routes/progress';
import { startCleanupSweeper } from './services/cleanup.service';
import { initCookiesFile } from './services/cookies.service';
import { closeQueue, startWorker } from './services/queue.service';
import { closeRedis } from './services/redis.service';
import { logger } from './utils/logger';

const log = logger.child('http');

export function buildApp(): Express {
  const app = express();
  app.disable('x-powered-by');
  app.set('trust proxy', 1);

  app.use(helmet());
  app.use(cors());
  app.use(compression());
  app.use(express.json({ limit: '64kb' }));
  app.use(
    morgan(config.nodeEnv === 'production' ? 'combined' : 'dev', {
      stream: { write: (msg) => log.info(msg.trim()) },
    }),
  );

  app.get('/health', (_req, res) => {
    res.json({ success: true, data: { status: 'ok' } });
  });

  app.use('/api', apiRateLimiter, fetchInfoRouter);
  app.use('/api', apiRateLimiter, downloadRouter);
  app.use('/api', apiRateLimiter, progressRouter);
  app.use('/api', fileRateLimiter, fileRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}

async function main(): Promise<void> {
  const app = buildApp();

  // Bring up HTTP first so /health is reachable while Redis / Bull connect.
  // Healthcheck-driven hosts (Railway, Fly, etc.) need a 200 within ~30s.
  const server = app.listen(config.port, () => {
    log.info(`fetch backend listening on :${config.port}`, { env: config.nodeEnv });
  });

  initCookiesFile();
  startCleanupSweeper();
  startWorker().catch((err) => {
    log.error('worker failed to start', { error: (err as Error).message });
  });

  const shutdown = async (signal: string) => {
    log.info(`received ${signal}, shutting down`);
    server.close();
    try {
      await closeQueue();
      await closeRedis();
    } catch (err) {
      log.warn('shutdown error', { error: (err as Error).message });
    }
    process.exit(0);
  };
  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('SIGINT', () => void shutdown('SIGINT'));
}

if (require.main === module) {
  main().catch((err) => {
    // eslint-disable-next-line no-console
    console.error('fatal startup error', err);
    process.exit(1);
  });
}
