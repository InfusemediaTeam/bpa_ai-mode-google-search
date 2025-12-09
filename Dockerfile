# Multi-stage build for NestJS API
# Based on official NestJS deployment recommendations
# https://docs.nestjs.com/deployment

# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /usr/src/app

# Copy package files
COPY package*.json ./

# Install dependencies (including devDependencies for build)
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Stage 2: Production
FROM node:20-alpine AS production

WORKDIR /usr/src/app

# Copy package files
COPY package*.json ./

# Install only production dependencies
RUN apk add --no-cache curl && npm ci --omit=dev && npm cache clean --force

# Copy built application from builder stage
COPY --from=builder /usr/src/app/dist ./dist

# Create logs and storage directories with correct permissions
# Must be done BEFORE switching to node user
RUN mkdir -p logs storage/jobs && \
    chown -R node:node /usr/src/app

# Run as non-root user for security
USER node

# Expose port
EXPOSE 4001

# Start the application
CMD ["node", "dist/main"]
