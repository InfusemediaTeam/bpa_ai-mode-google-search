import { Module } from '@nestjs/common';
import { HealthController } from './health.controller';
import { WorkerModule } from '../worker/worker.module';

@Module({
  imports: [WorkerModule],
  controllers: [HealthController],
})
export class HealthModule {}
