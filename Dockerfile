FROM node:24-alpine AS build
WORKDIR /workspace
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/frontend/app/package.json apps/frontend/app/package.json
COPY apps/backend/user/user-app-api/package.json apps/backend/user/user-app-api/package.json
COPY libs/common/api-contracts/package.json libs/common/api-contracts/package.json
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build
RUN pnpm --filter @wiut/api deploy --prod --legacy /out/api

FROM node:24-alpine AS api
ENV NODE_ENV=production API_HOST=0.0.0.0 API_PORT=3000
WORKDIR /app
COPY --from=build --chown=node:node /out/api ./
USER node
EXPOSE 3000
CMD ["node", "dist/main.js"]

FROM nginx:alpine AS web
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/frontend/app/dist /usr/share/nginx/html
EXPOSE 80
