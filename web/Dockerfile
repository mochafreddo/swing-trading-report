FROM node:24.14.0-alpine3.22@sha256:76db75ca7e7da9148ae42c92d9be12d12a8d7b03e171f18339355d8078d644a0 AS base
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
