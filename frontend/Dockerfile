FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# Dev/tools target (tsc, eslint, vitest): used by the compose "tools" profile and scripts/check.*
FROM deps AS dev
COPY . .

FROM dev AS build
ARG VITE_DEV_KIT=false
ENV VITE_DEV_KIT=$VITE_DEV_KIT
RUN npm run build
# Precompressed copies for nginx gzip_static: maximum level once, no per-request CPU.
RUN find dist -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' -o -name '*.json' \
      -o -name '*.html' -o -name '*.txt' \) -size +1k -exec gzip -9 -k -n {} +

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
