import { Injectable, Logger, NotFoundException } from '@nestjs/common';
import { InjectQueue } from '@nestjs/bull';
import type { Queue, JobStatus, Job } from 'bull';
import { JobStatusDto, JobState } from '../dto/job-status.dto';
import { TimeoutsService } from '../../../../../config/timeouts';
import { RedisService } from '../../../../../modules/redis/redis.service';

export interface PromptJobData {
  prompt: string;
  worker?: number;
  batchId?: string;
  batchIndex?: number;
  batchTotal?: number;
  priority?: number;
}

export interface PromptJobResult {
  json: string;
  raw_text?: string;
  usedWorker?: number;
}

@Injectable()
export class SearcherService {
  private readonly logger = new Logger(SearcherService.name);

  constructor(
    @InjectQueue('prompt') private readonly promptQueue: Queue,
    private readonly timeouts: TimeoutsService,
    private readonly redis: RedisService,
  ) {}

  /**
   * Enqueue a new prompt for processing
   * Returns the job ID immediately
   * Supports idempotency via optional key
   */
  async enqueue(
    prompt: string,
    preferredWorker?: number,
    idempotencyKey?: string,
    priority?: number,
  ): Promise<string> {
    // Check idempotency key if provided
    if (idempotencyKey) {
      const cachedJobId = await this.redis.getClient().get(`idempotency:${idempotencyKey}`);
      if (cachedJobId) {
        this.logger.log(`Idempotency hit: returning existing job ${cachedJobId}`);
        return cachedJobId;
      }
    }

    this.logger.log(`Enqueuing prompt: ${prompt.substring(0, 50)}...`);

    const job = await this.promptQueue.add(
      'process',
      { prompt, worker: preferredWorker, priority } as PromptJobData,
      {
        attempts: 3,
        backoff: {
          type: 'exponential',
          delay: 5000,
        },
        timeout: this.timeouts.bull.searchJobMs,
        priority: priority ?? 0, // Higher number = higher priority
      },
    );

    const jobId = String(job.id);

    // Cache idempotency key for 24 hours
    if (idempotencyKey) {
      await this.redis.getClient().setex(
        `idempotency:${idempotencyKey}`,
        this.timeouts.jobResultsTtlSec,
        jobId,
      );
    }

    return jobId;
  }

  /**
   * Enqueue multiple prompts for bulk processing
   * Creates individual jobs that process in parallel
   * Returns batch ID and array of job IDs
   * Supports idempotency via optional key
   */
  async enqueueBulk(
    prompts: string[],
    preferredWorker?: number,
    idempotencyKey?: string,
    priority?: number,
  ): Promise<{ batchId: string; jobIds: string[] }> {
    // Check idempotency key if provided
    if (idempotencyKey) {
      const cachedResult = await this.redis.getClient().get(`idempotency:bulk:${idempotencyKey}`);
      if (cachedResult) {
        const parsed = JSON.parse(cachedResult);
        this.logger.log(`Idempotency hit: returning existing batch ${parsed.batchId}`);
        return parsed;
      }
    }

    this.logger.log(`Enqueuing ${prompts.length} prompts in bulk`);

    const batchId = `batch_${Date.now()}_${Math.random().toString(36).substring(7)}`;

    const jobs = await Promise.all(
      prompts.map((prompt, index) =>
        this.promptQueue.add(
          'process',
          {
            prompt,
            worker: preferredWorker,
            batchId,
            batchIndex: index,
            batchTotal: prompts.length,
            priority,
          } as PromptJobData,
          {
            attempts: 3,
            backoff: {
              type: 'exponential',
              delay: 5000,
            },
            timeout: this.timeouts.bull.searchJobMs,
            priority: priority ?? 0, // Higher number = higher priority
          },
        ),
      ),
    );

    const jobIds = jobs.map((job) => String(job.id));
    this.logger.log(
      `Created batch ${batchId} with ${jobIds.length} jobs: ${jobIds.join(', ')}`,
    );

    // Store batch-to-jobs mapping in Redis Set for efficient lookup
    const batchKey = `batch:${batchId}:jobs`;
    await this.redis.getClient().sadd(batchKey, ...jobIds);
    await this.redis.getClient().expire(batchKey, this.timeouts.jobResultsTtlSec);

    const result = { batchId, jobIds };

    // Cache idempotency key for 24 hours
    if (idempotencyKey) {
      await this.redis.getClient().setex(
        `idempotency:bulk:${idempotencyKey}`,
        this.timeouts.jobResultsTtlSec,
        JSON.stringify(result),
      );
    }

    return result;
  }

  /**
   * Get job status by ID
   */
  async getStatus(jobId: string): Promise<JobStatusDto> {
    const job = await this.promptQueue.getJob(jobId);

    if (!job) {
      throw new NotFoundException(`Job ${jobId} not found`);
    }

    const state = await job.getState();
    const progress = job.progress() as Record<string, unknown> | number;

    return {
      jobId: String(job.id),
      status: this.mapState(state),
      progress: typeof progress === 'object' ? progress : undefined,
      result:
        state === 'completed' ? (job.returnvalue as PromptJobResult) : null,
      error: state === 'failed' ? job.failedReason : null,
      createdAt: new Date(job.timestamp).toISOString(),
      completedAt: job.finishedOn
        ? new Date(job.finishedOn).toISOString()
        : null,
    };
  }

  /**
   * Get batch status by batch ID
   * Returns aggregated status of all jobs in the batch
   * Optimized: Uses Redis Set for O(1) lookup instead of O(N) filtering
   */
  async getBatchStatus(batchId: string): Promise<{
    batchId: string;
    total: number;
    completed: number;
    processing: number;
    pending: number;
    failed: number;
    jobs: JobStatusDto[];
  }> {
    // Get job IDs from Redis Set (O(1) lookup)
    const batchKey = `batch:${batchId}:jobs`;
    const jobIds = await this.redis.getClient().smembers(batchKey);

    if (jobIds.length === 0) {
      throw new NotFoundException(`Batch ${batchId} not found`);
    }

    // Fetch job statuses in parallel
    const jobs: JobStatusDto[] = [];
    const jobDataMap = new Map<string, { batchIndex: number }>();

    await Promise.all(
      jobIds.map(async (jobId) => {
        try {
          const job = await this.promptQueue.getJob(jobId);
          if (job?.data) {
            jobDataMap.set(jobId, { batchIndex: job.data.batchIndex ?? 0 });
          }
          const jobStatus = await this.getStatus(jobId);
          jobs.push(jobStatus);
        } catch {
          // Job may have been removed
        }
      }),
    );

    const statusCounts = {
      completed: jobs.filter((j) => j.status === 'completed').length,
      processing: jobs.filter((j) => j.status === 'processing').length,
      pending: jobs.filter((j) => j.status === 'pending').length,
      failed: jobs.filter((j) => j.status === 'failed').length,
    };

    return {
      batchId,
      total: jobs.length,
      ...statusCounts,
      jobs: jobs.sort((a, b) => {
        const aIndex = jobDataMap.get(a.jobId)?.batchIndex ?? 0;
        const bIndex = jobDataMap.get(b.jobId)?.batchIndex ?? 0;
        return aIndex - bIndex;
      }),
    };
  }

  /**
   * Get all jobs with cursor-based pagination
   */
  async getAllJobs(
    status?: string,
    limit: number = 50,
    pageToken?: string,
  ): Promise<{
    items: JobStatusDto[];
    pagination: {
      totalItems: number;
      itemsPerPage: number;
      nextPageToken?: string;
    };
  }> {
    let allJobs: Job<PromptJobData>[] = [];

    if (status) {
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
      allJobs = await this.promptQueue.getJobs([status as JobStatus]);
    } else {
      const [waiting, active, completed, failed, delayed] = await Promise.all([
        this.promptQueue.getJobs(['waiting']),
        this.promptQueue.getJobs(['active']),
        this.promptQueue.getJobs(['completed']),
        this.promptQueue.getJobs(['failed']),
        this.promptQueue.getJobs(['delayed']),
      ]);
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
      allJobs = [...waiting, ...active, ...completed, ...failed, ...delayed];
    }

    allJobs.sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0));

    const totalItems = allJobs.length;

    let startIndex = 0;
    if (pageToken) {
      try {
        const decoded = JSON.parse(
          Buffer.from(pageToken, 'base64').toString('utf-8'),
        ) as { offset?: number };
        startIndex = decoded.offset ?? 0;
      } catch {
        // Invalid token, start from beginning
      }
    }

    const paginatedJobs = allJobs.slice(startIndex, startIndex + limit);

    const items: JobStatusDto[] = [];
    for (const job of paginatedJobs) {
      try {
        const jobStatus = await this.getStatus(String(job.id));
        items.push(jobStatus);
      } catch {
        // Job may have been removed
      }
    }

    let nextPageToken: string | undefined;
    if (startIndex + limit < totalItems) {
      nextPageToken = Buffer.from(
        JSON.stringify({ offset: startIndex + limit }),
      ).toString('base64');
    }

    return {
      items,
      pagination: {
        totalItems,
        itemsPerPage: limit,
        ...(nextPageToken && { nextPageToken }),
      },
    };
  }

  private mapState(state: string): JobState {
    switch (state) {
      case 'waiting':
      case 'delayed':
        return 'pending';
      case 'active':
        return 'processing';
      case 'completed':
        return 'completed';
      case 'failed':
        return 'failed';
      default:
        return 'pending';
    }
  }
}
