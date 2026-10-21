# N100 Service Hub 프런트엔드 이미지 (정적 빌드 + nginx)
#
# * Docker 소켓을 마운트하지 않는다 (docs/SECURITY.md).
# * 빌드 산출물(dist)만 런타임 이미지에 넣는다.
#
# 빌드: docker build -t n100-service-hub-frontend:0.1.0 ./frontend
FROM node:22-bookworm-slim AS build
WORKDIR /app

# 의존성 레이어 캐시
COPY package.json package-lock.json ./
RUN npm ci

# 소스 + 빌드
COPY . .
RUN npm run build

# 런타임: nginx 정적 서빙
FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
