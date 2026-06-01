# Build stage — compiles Next.js, including devDependencies needed for the build.
# No devDependencies survive into the runtime layer.
FROM node:22-alpine AS build
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Runtime stage — standalone Next.js output only.
# Contains only the minimal node_modules required at runtime (no devDependencies).
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE ${PORT:-3000}
CMD ["node", "server.js"]
