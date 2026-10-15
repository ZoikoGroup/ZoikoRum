# Zoikorum web app: static build served by nginx, which also forwards the API (/v1, /health, /ready) so the browser
# sees one origin (no CORS). API_UPSTREAM is the backend address, e.g. http://api:8000 (see backend/docs/DEPLOYMENT.md).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Which app this image serves (src/portal.ts): customer (default) or staff, plus each app's public address so the two can
# send people to each other. Build the image twice: once per app, e.g. app.your-domain.com and staff.your-domain.com.
ARG VITE_PORTAL=customer
ARG VITE_CUSTOMER_URL=""
ARG VITE_STAFF_URL=""
ENV VITE_PORTAL=$VITE_PORTAL VITE_CUSTOMER_URL=$VITE_CUSTOMER_URL VITE_STAFF_URL=$VITE_STAFF_URL
RUN npm run build

FROM nginx:1.27-alpine
# Security fixes for the base system (OpenSSL, libexpat, libpng, ...) published since the base image was built.
RUN apk upgrade --no-cache
ENV API_UPSTREAM=http://api:8000
# The Google load balancer's own public address (its forwarding rule), so it is skipped when finding the visitor.
ENV TRUSTED_LB_IP=127.0.0.1
# The official image renders /etc/nginx/templates/*.template with environment variables at start.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
