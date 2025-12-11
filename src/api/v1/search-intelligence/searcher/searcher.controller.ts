import { Controller, Get, Post, Param, Body, Query, Res, HttpException, HttpStatus, HttpCode } from '@nestjs/common';
import { ApiTags, ApiOperation, ApiResponse, ApiHeader, ApiQuery } from '@nestjs/swagger';
import { Response } from 'express';
import * as fs from 'fs';
import * as path from 'path';
import { RedisService } from '../../../../modules/redis/redis.service';
import { WorkerClientService } from '../../../../modules/worker/worker-client.service';
import { SearcherService } from './services/searcher.service';
import { CreatePromptDto } from './dto/create-prompt.dto';

/**
 * Searcher Controller
 * 
 * API paths follow contract: /api/v{major}/{businessFlow}/{tool}/{action}
 * - businessFlow: search-intelligence
 * - tool: searcher
 * - version: v1
 */
@ApiTags('search-intelligence/searcher')
@Controller('api/v1/search-intelligence/searcher')
@ApiHeader({ name: 'X-Request-Id', description: 'Request correlation ID', required: true })
export class SearcherController {
  constructor(
    private readonly redis: RedisService,
    private readonly worker: WorkerClientService,
    private readonly searcherService: SearcherService,
  ) {}

  // ==================== PROMPTS ====================

  /**
   * Submit a prompt for async processing
   * Returns 202 Accepted with jobId for long-running operations
   */
  @Post('prompts')
  @HttpCode(HttpStatus.ACCEPTED)
  @ApiOperation({ summary: 'Submit a prompt for async processing' })
  @ApiQuery({ name: 'worker', required: false, description: 'Preferred worker ID (1-15)', type: Number })
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
          error: {
            code: 'BAD_REQUEST',
            message: 'Invalid worker parameter',
            details: { field: 'worker', value: workerQuery },
          },
        }, HttpStatus.BAD_REQUEST);
      }
      preferredWorker = Math.trunc(n);
    }

    const jobId = await this.searcherService.enqueue(dto.prompt, preferredWorker);
    return { jobId };
  }

  // ==================== JOBS ====================

  /**
   * Get job status by ID
   */
  @Get('jobs/:jobId')
  @ApiOperation({ summary: 'Get job status by ID' })
  @ApiResponse({ status: 200, description: 'Job status retrieved' })
  @ApiResponse({ status: 404, description: 'Job not found' })
  async getJobStatus(@Param('jobId') jobId: string) {
    return await this.searcherService.getStatus(jobId);
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
    return await this.searcherService.getAllJobs(status, parsedLimit, pageToken);
  }

  // ==================== HEALTH ====================

  @Get('health')
  @ApiOperation({ summary: 'Health check endpoint' })
  @ApiResponse({ status: 200, description: 'Service health status' })
  async getHealth() {
    const rtt = await this.redis.ping();
    const redisOk = typeof rtt === 'number';
    
    const workerCount = this.worker.getWorkerCount();
    const workersHealth = await Promise.all(
      Array.from({ length: workerCount }, (_, i) => 
        this.worker.health(i + 1)
          .then(health => ({ workerId: i + 1, ...health }))
          .catch(err => ({ 
            workerId: i + 1, 
            ok: false, 
            error: err?.message || String(err) 
          }))
      )
    );
    
    const healthyWorkers = workersHealth.filter(w => w.ok);
    const busyWorkers = workersHealth.filter(w => 'busy' in w && w.busy);
    const allWorkersOk = healthyWorkers.length === workerCount;
    const anyWorkerOk = healthyWorkers.length > 0;
    
    return {
      status: anyWorkerOk ? 'ok' : 'degraded',
      app: 'ok',
      redis: redisOk ? 'ok' : 'fail',
      redisRttMs: redisOk ? rtt : null,
      workers: {
        total: workerCount,
        healthy: healthyWorkers.length,
        busy: busyWorkers.length,
        status: allWorkersOk ? 'ok' : (anyWorkerOk ? 'degraded' : 'fail'),
        details: workersHealth.map(w => {
          let errorMsg: string | null = null;
          if (!w.ok) {
            if ('chrome_alive' in w && !w.chrome_alive) {
              errorMsg = 'browser crashed or zombie';
            } else if ('error' in w && w.error) {
              errorMsg = w.error as string;
            } else {
              errorMsg = 'unknown error';
            }
          }
          
          return {
            id: w.workerId,
            ok: w.ok,
            busy: ('busy' in w && w.busy) || false,
            ready: ('ready' in w && w.ready) || false,
            browser: ('browser' in w && w.browser) || 'unknown',
            version: ('version' in w && w.version) ?? null,
            chromeAlive: ('chrome_alive' in w) ? w.chrome_alive : null,
            error: errorMsg,
          };
        }),
      },
      timestamp: new Date().toISOString(),
    };
  }

  // ==================== LOGS ====================

  @Get('logs')
  @ApiOperation({ summary: 'Get application logs' })
  @ApiResponse({ status: 200, description: 'Log file contents' })
  @ApiQuery({ name: 'type', required: false, enum: ['app', 'error'], description: 'Log type (default: app)' })
  @ApiQuery({ name: 'date', required: false, description: 'Date in YYYY-MM-DD format (default: today)' })
  @ApiQuery({ name: 'lines', required: false, description: 'Number of lines from end (default: 100)' })
  @ApiQuery({ name: 'format', required: false, enum: ['json', 'text'], description: 'Output format (default: json)' })
  async getLogs(
    @Res() res: Response,
    @Query('type') type: string = 'app',
    @Query('date') date?: string,
    @Query('lines') lines: string = '100',
    @Query('format') format: string = 'json',
  ) {
    const logDir = process.env.LOG_DIR || 'logs';
    const logDate = date || new Date().toISOString().split('T')[0];
    const logType = type === 'error' ? 'error' : 'app';
    const filename = `${logType}-${logDate}.log`;
    const filepath = path.join(logDir, filename);

    if (!fs.existsSync(filepath)) {
      return res.status(404).json({
        error: {
          code: 'NOT_FOUND',
          message: 'Log file not found',
          details: { filename, availableLogs: this.getAvailableLogs(logDir) },
        },
      });
    }

    try {
      const content = fs.readFileSync(filepath, 'utf-8');
      const allLines = content.trim().split('\n').filter(Boolean);
      const numLines = Math.min(parseInt(lines) || 100, 10000);
      const selectedLines = allLines.slice(-numLines);

      if (format === 'text') {
        res.setHeader('Content-Type', 'text/plain');
        return res.send(selectedLines.join('\n'));
      }

      const parsedLogs = selectedLines.map(line => {
        try { return JSON.parse(line); } catch { return { raw: line }; }
      });

      return res.json({
        filename,
        totalLines: allLines.length,
        returnedLines: selectedLines.length,
        logs: parsedLogs,
      });
    } catch (err) {
      return res.status(500).json({
        error: {
          code: 'INTERNAL_ERROR',
          message: 'Failed to read log file',
          details: { reason: err instanceof Error ? err.message : String(err) },
        },
      });
    }
  }

  @Get('logs/files')
  @ApiOperation({ summary: 'List available log files' })
  @ApiResponse({ status: 200, description: 'List of log files' })
  async getLogFiles() {
    const logDir = process.env.LOG_DIR || 'logs';
    return { logDir, files: this.getAvailableLogs(logDir) };
  }

  private getAvailableLogs(logDir: string): { name: string; size: number; modified: string }[] {
    try {
      if (!fs.existsSync(logDir)) return [];
      return fs.readdirSync(logDir)
        .filter(f => f.endsWith('.log'))
        .map(f => {
          const stat = fs.statSync(path.join(logDir, f));
          return { name: f, size: stat.size, modified: stat.mtime.toISOString() };
        })
        .sort((a, b) => b.modified.localeCompare(a.modified));
    } catch { return []; }
  }
}
