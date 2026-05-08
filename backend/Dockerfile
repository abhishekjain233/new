FROM node:20-alpine AS builder

RUN apk add --no-cache python3 ffmpeg curl ca-certificates

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:20-alpine

RUN apk add --no-cache python3 ffmpeg curl ca-certificates tini \
  && curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp \
       -o /usr/local/bin/yt-dlp \
  && chmod +x /usr/local/bin/yt-dlp \
  && yt-dlp --version

WORKDIR /app

COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY package*.json ./

ENV NODE_ENV=production \
    PORT=3000 \
    YTDLP_PATH=/usr/local/bin/yt-dlp \
    TEMP_DIR=/tmp

EXPOSE 3000

ENTRYPOINT ["/sbin/tini", "--"]
CMD ["node", "dist/index.js"]
