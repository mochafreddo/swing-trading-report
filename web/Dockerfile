FROM node:24.13.1-alpine3.22@sha256:d28696cabe6a72c5addbb608b344818e5a158d849174abd4b1ae85ab48536280 AS base
WORKDIR /app

RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ENV NODE_ENV=production

RUN SAB_SKIP_ENV_VALIDATION=1 pnpm run build

EXPOSE 3000

RUN chown -R node:node /app
USER node

CMD ["pnpm", "run", "start"]
