FROM node:24.13.1-alpine3.22 AS base
WORKDIR /app

RUN apk add --no-cache curl
RUN curl -fsSL https://github.com/pnpm/pnpm/releases/download/v10.29.3/pnpm-linuxstatic-x64 \
  -o /usr/local/bin/pnpm && \
  chmod +x /usr/local/bin/pnpm
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 3000
CMD ["pnpm", "run", "dev"]
