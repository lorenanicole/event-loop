# ── EventLoop Frontend ───────────────────────────────────────────────────────
# Two-stage build: Node builds the Vite app, nginx serves the static output.
# The backend URL is NOT baked into the JS bundle. Instead, nginx proxies
# /api/* to the backend at runtime using the API_URL environment variable.
# ─────────────────────────────────────────────────────────────────────────────

# Stage 1: build
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Build with no VITE_API_BASE_URL — the app uses relative /api paths,
# which nginx proxies to the real backend at runtime.
RUN npm run build

# Stage 2: serve
FROM nginx:alpine

# envsubst ships with gettext; install it so we can template nginx.conf
RUN apk add --no-cache gettext

# Remove default nginx page
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config as a template (contains ${API_URL} placeholder)
COPY nginx.conf /etc/nginx/conf.d/default.conf.template

EXPOSE 80

# At startup: substitute API_URL into the nginx config, then start nginx.
# API_URL must be set as a Railway environment variable, e.g.:
#   API_URL=https://event-loop-production.up.railway.app
CMD ["/bin/sh", "-c", "envsubst '${API_URL}' < /etc/nginx/conf.d/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
