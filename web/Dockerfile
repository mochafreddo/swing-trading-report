FROM node:24.14.1-alpine3.22@sha256:4f33c7804fa7775b87875f512e25e515692210bfdeafd715eb8bc441c364e2f6 AS base
WORKDIR /app

RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ENV NODE_ENV=production

RUN SAB_SKIP_ENV_VALIDATION=1 pnpm run build

EXPOSE 3000

RUN chown -R node:node /app
USER node

CMD ["pnpm", "run", "start"]
