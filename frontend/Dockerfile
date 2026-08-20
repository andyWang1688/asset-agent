# 前端：Vite 构建产物 + Nginx 托管与 /api 反向代理
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml* ./
# dangerouslyAllowAllBuilds 仅构建阶段使用：允许 esbuild 等工具链的 postinstall 在容器内执行
RUN corepack enable && pnpm install --frozen-lockfile=false --config.dangerouslyAllowAllBuilds=true
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
