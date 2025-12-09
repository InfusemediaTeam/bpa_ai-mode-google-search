import { Process, Processor } from '@nestjs/bull';
import { Logger } from '@nestjs/common';
import type { Job } from 'bull';
import { WorkerClientService } from '../worker/worker-client.service';
import type { PromptJobData, PromptJobResult } from './prompt.service';

@Processor('prompt')
export class PromptProcessor {
  private readonly logger = new Logger(PromptProcessor.name);

  constructor(
    private readonly workerClient: WorkerClientService,
  ) {}

  @Process({ name: 'process', concurrency: 1 })
  async handlePrompt(job: Job<PromptJobData>): Promise<PromptJobResult> {
    const { prompt, worker } = job.data;
    this.logger.log(`Processing job ${job.id}: ${prompt.substring(0, 50)}...`);

    try {
      // Update progress
      await job.progress({ stage: 'processing', workerId: worker });

      // Call worker with retry logic
      const result = await this.workerClient.searchWithRetry(prompt, worker);
      
      this.logger.log(`Job ${job.id} completed successfully, result size: ${result.text.length} chars`);
      
      return {
        text: result.text,
        html: result.html,
        usedWorker: result.usedWorker,
      };
    } catch (error: any) {
      this.logger.error(`Job ${job.id} failed: ${error.message}`, error.stack);
      throw error;
    }
  }
}
