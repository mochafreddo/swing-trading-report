FROM python:3.14.5-alpine3.22@sha256:6b91e66ab2a880ce9ca5a1b91c70f45963ff71ff68268df056336e1a657d5efd AS journal-python

FROM node:24.16.0-alpine3.22@sha256:191c9f0080fcbbc6547a85dc0ff7988072214a355aabdc1d2ec55a7dae5eea8a AS base
WORKDIR /app

COPY --from=journal-python /usr/local /opt/python
ENV PATH="/opt/python/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/python/lib"

RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/next.config.ts web/next-env.d.ts web/tsconfig.json web/middleware.ts ./
COPY web/scripts ./scripts
COPY web/fixtures/toss-holdings.qa.json ./fixtures/toss-holdings.qa.json
COPY web/src ./src
COPY sab/decision_board/run_journal_public.py /opt/sab/decision_board/run_journal_public.py
RUN python3 -m py_compile /opt/sab/decision_board/run_journal_public.py \
    && python3 /opt/sab/decision_board/run_journal_public.py --help >/dev/null

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN SAB_SKIP_ENV_VALIDATION=1 pnpm run build

EXPOSE 3000

RUN chown -R node:node /app
USER node

CMD ["pnpm", "run", "start"]
