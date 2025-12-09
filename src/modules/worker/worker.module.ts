import { Module, Global } from '@nestjs/common';
import { WorkerClientService } from './worker-client.service';

@Global()
@Module({
  providers: [WorkerClientService],
  exports: [WorkerClientService],
})
export class WorkerModule {}
