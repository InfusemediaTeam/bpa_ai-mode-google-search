import { Module, Global } from '@nestjs/common';
import { TimeoutsService } from './timeouts';

@Global()
@Module({
  providers: [TimeoutsService],
  exports: [TimeoutsService],
})
export class AppConfigModule {}
