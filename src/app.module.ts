import { Module } from '@nestjs/common';
import { BullModule } from '@nestjs/bull';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { ThrottlerModule } from '@nestjs/throttler';
import { LoggingModule } from './modules/logging/logging.module';
import { RedisModule } from './modules/redis/redis.module';
import { SearcherModule } from './api/v1/search-intelligence/searcher/searcher.module';
import { AppConfigModule } from './config/config.module';
import { validate } from './config/env.validation';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      validate, // Validate all required env vars on startup
    }),
    ThrottlerModule.forRoot([{
      ttl: 60000, // 1 minute
      limit: 100, // 100 requests per minute per IP
    }]),
    AppConfigModule,
    LoggingModule,
    RedisModule,
    BullModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (configService: ConfigService) => {
        const redisUrl = configService.get<string>('REDIS_URL');
        if (!redisUrl) {
          throw new Error('REDIS_URL environment variable is required');
        }

        const u = new URL(redisUrl);
        const host = u.hostname;
        const port = Number(u.port || '6379');
        const password = u.password
          ? decodeURIComponent(u.password)
          : undefined;

        const jobTtl =
          configService.get<number>('JOB_RESULTS_TTL_SEC') || 86400;

        return {
          redis: password ? { host, port, password } : { host, port },
          defaultJobOptions: {
            removeOnComplete: { age: jobTtl },
            removeOnFail: { age: jobTtl },
          },
        };
      },
    }),
    SearcherModule,
  ],
})
export class AppModule {}
