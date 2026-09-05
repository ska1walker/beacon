# Frontend — mehrstufig, damit das Abbild nur die Laufzeit trägt.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Die Schriften liegen im Repo unter app/fonts. Kein Google-CDN, auch
# nicht zur Bauzeit — sonst führe der Bau eine Verbindung nach draußen,
# die es laut Versprechen nicht geben darf.
ENV NEXT_TELEMETRY_DISABLED=1
# Das Proxy-Ziel der Rewrites wird BEIM BAU eingebrannt: next.config.mjs
# liest BACKEND_URL beim Bauen, und im Standalone-Abbild ist die
# Umgebungsvariable zur Laufzeit dafür bedeutungslos. Auf der Box lief
# 0.1.1 deshalb gegen localhost:8000 und jede API-Anfrage endete mit
# 500. Der Dienstname ist im Chart fest, also darf er hier stehen.
ARG BACKEND_URL=http://beacon-backend:8000
ENV BACKEND_URL=$BACKEND_URL
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

USER 1000
EXPOSE 3000

CMD ["node", "server.js"]
