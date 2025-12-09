import { Process, Processor } from '@nestjs/bull';
import { Logger } from '@nestjs/common';
import type { Job } from 'bull';
import { WorkerClientService } from '../worker/worker-client.service';
import type { PromptJobData, PromptJobResult } from './prompt.service';

// Calculate worker count from env at module load time (before DI)
const WORKER_CONCURRENCY = (process.env.WORKER_BASE_URLS || '').split(',').filter(Boolean).length || 3;

@Processor('prompt')
export class PromptProcessor {
  private readonly logger = new Logger(PromptProcessor.name);

  constructor(
    private readonly workerClient: WorkerClientService,
  ) {
    this.logger.log(`Processor initialized with ${this.workerClient.getWorkerCount()} workers, concurrency=${WORKER_CONCURRENCY}`);
  }

  // Process jobs in parallel - one per available worker
  @Process({ name: 'process', concurrency: WORKER_CONCURRENCY })
  async handlePrompt(job: Job<PromptJobData>): Promise<PromptJobResult> {
    const { prompt, worker } = job.data;
    this.logger.log(`Processing job ${job.id}: ${prompt.substring(0, 50)}...`);

    // Update progress to processing
    await job.progress({ stage: 'processing', workerId: worker });

    try {
      // Call worker with retry logic
      const result = await this.workerClient.searchWithRetry(prompt, worker);
      
      // Update progress to completed
      await job.progress({ stage: 'completed', workerId: result.usedWorker });
      
      this.logger.log(`Job ${job.id} completed successfully, result size: ${result.json?.length || 0} chars`);
      
      return {
        json: result.json || '',
        raw_text: result.raw_text || '',
        usedWorker: result.usedWorker,
      };
    } catch (error: any) {
      // Update progress to failed
      await job.progress({ stage: 'failed', workerId: worker });
      
      this.logger.error(`Job ${job.id} failed: ${error.message}`);
      throw error;
    }
  }
}
