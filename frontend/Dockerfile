# ── EventLoop Frontend ───────────────────────────────────────────────────────
# Two-stage build: Node builds the Vite app, nginx serves the static output.
# Set VITE_API_BASE_URL at build time to the Railway API service public URL.
# ─────────────────────────────────────────────────────────────────────────────

# Stage 1: build
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_API_BASE_URL is injected by Railway as a build argument.
# Default empty string falls back to relative /api (same-origin dev).
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

# Stage 2: serve
FROM nginx:alpine

# Remove default nginx page
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# SPA routing: unknown paths → index.html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
