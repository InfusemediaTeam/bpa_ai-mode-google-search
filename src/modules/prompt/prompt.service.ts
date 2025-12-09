import { Injectable, Logger, NotFoundException } from '@nestjs/common';
import { InjectQueue } from '@nestjs/bull';
import type { Queue, JobStatus } from 'bull';
import { JobStatusDto, JobState } from './dto/job-status.dto';
import { TimeoutsService } from '../../config/timeouts';

export interface PromptJobData {
  prompt: string;
  worker?: number;
}

export interface PromptJobResult {
  json: string;
  raw_text?: string;
  usedWorker?: number;
}

@Injectable()
export class PromptService {
  private readonly logger = new Logger(PromptService.name);

  constructor(
    @InjectQueue('prompt') private readonly promptQueue: Queue,
    private readonly timeouts: TimeoutsService,
  ) {}

  /**
   * Enqueue a new prompt for processing
   * Returns the job ID immediately
   */
  async enqueue(prompt: string, preferredWorker?: number): Promise<string> {
    this.logger.log(`Enqueuing prompt: ${prompt.substring(0, 50)}...`);
    
    const job = await this.promptQueue.add(
      'process',
      { prompt, worker: preferredWorker } as PromptJobData,
      {
        attempts: 3,
        backoff: {
          type: 'exponential',
          delay: 5000,
        },
        timeout: this.timeouts.bull.searchJobMs,
      },
    );

    return String(job.id);
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
    const progress = job.progress();

    return {
      jobId: String(job.id),
      status: this.mapState(state),
      progress: typeof progress === 'object' ? progress : undefined,
      result: state === 'completed' ? job.returnvalue : null,
      error: state === 'failed' ? job.failedReason : null,
      createdAt: new Date(job.timestamp).toISOString(),
      completedAt: job.finishedOn ? new Date(job.finishedOn).toISOString() : null,
    };
  }

  /**
   * Get all jobs with cursor-based pagination (per n8n contract)
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
    let allJobs: any[] = [];

    if (status) {
      allJobs = await this.promptQueue.getJobs([status as JobStatus]);
    } else {
      // Get all jobs from all states
      const [waiting, active, completed, failed, delayed] = await Promise.all([
        this.promptQueue.getJobs(['waiting']),
        this.promptQueue.getJobs(['active']),
        this.promptQueue.getJobs(['completed']),
        this.promptQueue.getJobs(['failed']),
        this.promptQueue.getJobs(['delayed']),
      ]);
      allJobs = [...waiting, ...active, ...completed, ...failed, ...delayed];
    }

    // Sort by timestamp descending (newest first)
    allJobs.sort((a, b) => b.timestamp - a.timestamp);

    const totalItems = allJobs.length;

    // Apply cursor-based pagination
    let startIndex = 0;
    if (pageToken) {
      try {
        const decoded = JSON.parse(Buffer.from(pageToken, 'base64').toString('utf-8'));
        startIndex = decoded.offset || 0;
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

    // Generate next page token if there are more items
    let nextPageToken: string | undefined;
    if (startIndex + limit < totalItems) {
      nextPageToken = Buffer.from(JSON.stringify({ offset: startIndex + limit })).toString('base64');
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

  /**
   * Map Bull job state to our JobState enum
   */
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
