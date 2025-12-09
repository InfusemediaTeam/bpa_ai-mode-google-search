import { Injectable, OnModuleDestroy, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import IORedis, { Redis } from 'ioredis';

@Injectable()
export class RedisService implements OnModuleDestroy {
  private readonly logger = new Logger(RedisService.name);
  private client: Redis;

  constructor(private readonly configService: ConfigService) {
    const url = this.configService.get<string>('REDIS_URL');
    
    if (!url) {
      throw new Error('REDIS_URL environment variable is required');
    }
    
    this.client = new IORedis(url, {
      lazyConnect: false,
      maxRetriesPerRequest: null,
    });

    this.client.on('error', (err) => {
      this.logger.error(`Redis error: ${err?.message || err}`);
    });
    this.client.on('connect', () => {
      this.logger.log('Redis connected');
    });
    this.client.on('end', () => {
      this.logger.log('Redis connection ended');
    });
  }

  /**
   * Ping redis and return RTT in ms, or null on failure
   */
  async ping(): Promise<number | null> {
    try {
      const start = Date.now();
      const res = await this.client.ping();
      if (res?.toUpperCase() !== 'PONG') return null;
      return Date.now() - start;
    } catch {
      return null;
    }
  }

  getClient(): Redis {
    return this.client;
  }

  async onModuleDestroy() {
    try {
      await this.client.quit();
    } catch {
      try { this.client.disconnect(); } catch {}
    }
  }
}
