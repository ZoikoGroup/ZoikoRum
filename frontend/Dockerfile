# Zoikorum web app: static build served by nginx, which also forwards the API (/v1, /health, /ready) so the browser
# sees one origin (no CORS). API_UPSTREAM is the backend address, e.g. http://api:8000 (see backend/docs/DEPLOYMENT.md).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
ENV API_UPSTREAM=http://api:8000
# The official image renders /etc/nginx/templates/*.template with environment variables at start.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
