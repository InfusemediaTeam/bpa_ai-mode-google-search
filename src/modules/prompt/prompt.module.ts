import { Module } from '@nestjs/common';
import { BullModule } from '@nestjs/bull';
import { ConfigModule } from '@nestjs/config';
import { PromptController } from './prompt.controller';
import { PromptService } from './prompt.service';
import { PromptProcessor } from './prompt.processor';
import { WorkerModule } from '../worker/worker.module';
import { AppConfigModule } from '../../config/config.module';
import { TimeoutsService } from '../../config/timeouts';

@Module({
  imports: [
    WorkerModule,
    BullModule.registerQueueAsync({
      name: 'prompt',
      imports: [ConfigModule, AppConfigModule],
      inject: [TimeoutsService],
      useFactory: (timeouts: TimeoutsService) => {
        return {
          settings: {
            stalledInterval: 30000,
            maxStalledCount: 10,
          },
          // Note: concurrency is set in @Process decorator (processor.ts)
          // limiter would limit rate (jobs/sec), not parallelism
          defaultJobOptions: {
            removeOnComplete: { age: timeouts.jobResultsTtlSec },
            removeOnFail: { age: timeouts.jobResultsTtlSec },
            attempts: 3,
            backoff: {
              type: 'exponential',
              delay: 5000,
            },
            timeout: timeouts.bull.searchJobMs,
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
