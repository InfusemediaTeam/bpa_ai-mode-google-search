import { Module } from '@nestjs/common';
import { BullModule } from '@nestjs/bull';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { PromptController } from './prompt.controller';
import { PromptService } from './prompt.service';
import { PromptProcessor } from './prompt.processor';
import { WorkerModule } from '../worker/worker.module';
import { TimeoutsService } from '../../config/timeouts';

@Module({
  imports: [
    WorkerModule,
    BullModule.registerQueueAsync({
      name: 'prompt',
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (configService: ConfigService) => {
        const jobTtl = configService.get<number>('JOB_RESULTS_TTL_SEC') || 86400;
        const searchTimeout = configService.get<number>('BULL_SEARCH_TIMEOUT_MS') || 60000;
        
        return {
          settings: {
            stalledInterval: 30000,
            maxStalledCount: 10,
          },
          defaultJobOptions: {
            removeOnComplete: { age: jobTtl },
            removeOnFail: { age: jobTtl },
            attempts: 3,
            backoff: {
              type: 'exponential',
              delay: 5000,
            },
            timeout: searchTimeout,
          },
        };
      },
    }),
  ],
  controllers: [PromptController],
  providers: [PromptService, PromptProcessor, TimeoutsService],
  exports: [PromptService],
})
export class PromptModule {}
