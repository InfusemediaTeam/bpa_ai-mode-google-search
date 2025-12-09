import { Controller, Post, Get, Param, Body, Query, HttpException, HttpStatus, Logger, Res, HttpCode } from '@nestjs/common';
import { ApiTags, ApiOperation, ApiResponse, ApiQuery, ApiHeader } from '@nestjs/swagger';
import { Response } from 'express';
import { PromptService } from './prompt.service';
import { CreatePromptDto } from './dto/create-prompt.dto';
import { JobStatusDto, CreateJobResponseDto } from './dto/job-status.dto';

/**
 * Prompt Controller
 * 
 * API paths follow n8n contract: /{businessFlow}/{tool}/v{major}/{action}
 * - businessFlow: search-intelligence
 * - tool: searcher
 * - version: v1
 */
@ApiTags('search-intelligence/searcher')
@Controller('search-intelligence/searcher/v1')
@ApiHeader({ name: 'X-Request-Id', description: 'Request correlation ID', required: false })
export class PromptController {
  private readonly logger = new Logger(PromptController.name);

  constructor(private readonly promptService: PromptService) {}

  /**
   * Submit a prompt for async processing
   * Returns 202 Accepted with jobId for long-running operations
   */
  @Post('prompts')
  @HttpCode(HttpStatus.ACCEPTED) // 202 for async operations per n8n contract
  @ApiOperation({ summary: 'Submit a prompt for async processing' })
  @ApiResponse({ status: 202, description: 'Job accepted for processing' })
  @ApiResponse({ status: 400, description: 'Invalid request' })
  @ApiResponse({ status: 422, description: 'Validation error' })
  async createPrompt(
    @Body() dto: CreatePromptDto,
    @Query('worker') workerQuery?: string,
  ): Promise<{ jobId: string }> {
    let preferredWorker: number | undefined;
    
    if (workerQuery !== undefined) {
      const n = Number(workerQuery);
      if (!Number.isFinite(n) || n < 1) {
        throw new HttpException({
          code: 'BAD_REQUEST',
          message: 'Invalid worker parameter',
        }, HttpStatus.BAD_REQUEST);
      }
      preferredWorker = Math.trunc(n);
    }

    const jobId = await this.promptService.enqueue(dto.prompt, preferredWorker);
    
    // Response will be wrapped by RequestIdInterceptor
    return { jobId };
  }

  /**
   * Get job status by ID
   * Per n8n contract: GET /{businessFlow}/{tool}/v1/jobs/{jobId}
   */
  @Get('jobs/:jobId')
  @ApiOperation({ summary: 'Get job status by ID' })
  @ApiResponse({ status: 200, description: 'Job status retrieved' })
  @ApiResponse({ status: 404, description: 'Job not found' })
  async getJobStatus(@Param('jobId') jobId: string) {
    return await this.promptService.getStatus(jobId);
  }

  /**
   * List all jobs with optional status filter
   */
  @Get('jobs')
  @ApiOperation({ summary: 'List all jobs or filter by status' })
  @ApiQuery({ name: 'status', required: false, enum: ['pending', 'processing', 'completed', 'failed'] })
  @ApiQuery({ name: 'limit', required: false, description: 'Max items per page (default: 50, max: 100)' })
  @ApiQuery({ name: 'pageToken', required: false, description: 'Pagination cursor' })
  @ApiResponse({ status: 200, description: 'Jobs list retrieved' })
  async getJobs(
    @Query('status') status?: string,
    @Query('limit') limit?: string,
    @Query('pageToken') pageToken?: string,
  ) {
    const parsedLimit = limit ? Math.min(Math.max(1, parseInt(limit, 10) || 50), 100) : 50;
    return await this.promptService.getAllJobs(status, parsedLimit, pageToken);
  }
}
