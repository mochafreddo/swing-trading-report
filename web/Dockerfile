FROM node:24.16.0-alpine3.22@sha256:191c9f0080fcbbc6547a85dc0ff7988072214a355aabdc1d2ec55a7dae5eea8a AS base
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
