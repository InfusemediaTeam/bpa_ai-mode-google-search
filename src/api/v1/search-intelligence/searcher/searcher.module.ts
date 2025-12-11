import { Module } from '@nestjs/common';
import { BullModule } from '@nestjs/bull';
import { SearcherController } from './searcher.controller';
import { SearcherService } from './services/searcher.service';
import { SearcherProcessor } from './services/searcher.processor';
import { RedisModule } from '../../../../modules/redis/redis.module';
import { WorkerModule } from '../../../../modules/worker/worker.module';
import { TimeoutsService } from '../../../../config/timeouts';

@Module({
  imports: [
    BullModule.registerQueue({
      name: 'prompt',
    }),
    RedisModule,
    WorkerModule,
  ],
  controllers: [SearcherController],
  providers: [
    SearcherService,
    SearcherProcessor,
    TimeoutsService,
  ],
})
export class SearcherModule {}
