/**
 * Centralized timeout configuration
 * All timeouts accessed via ConfigService
 */
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class TimeoutsService {
  constructor(private readonly configService: ConfigService) {}

  private getInt(envName: string, def: number): number {
    const v = this.configService.get<number>(envName);
    if (v === undefined || v === null) return def;
    const n = Number(v);
    if (!Number.isFinite(n) || n <= 0) {
      console.warn(`[TIMEOUTS] Invalid ${envName}=${v}, using default ${def}ms`);
      return def;
    }
    return n;
  }

  get worker() {
    return {
      /** Health check timeout (ms) */
      healthMs: this.getInt('WORKER_HEALTH_TIMEOUT_MS', 7000),
      /** Search request timeout (ms) */
      searchMs: this.getInt('WORKER_SEARCH_TIMEOUT_MS', 30000),
      /** Session refresh timeout (ms) */
      refreshMs: this.getInt('WORKER_REFRESH_TIMEOUT_MS', 15000),
      /** Browser restart timeout (ms) */
      restartMs: this.getInt('WORKER_RESTART_TIMEOUT_MS', 15000),
      /** Tab warmup timeout (ms) */
      warmupMs: this.getInt('WORKER_WARMUP_TIMEOUT_MS', 20000),
    };
  }

  get bull() {
    return {
      /** Single search/prompt job timeout (ms) */
      searchJobMs: this.getInt('BULL_SEARCH_TIMEOUT_MS', 60000),
      /** Bulk job timeout (ms) */
      bulkJobMs: this.getInt('BULL_BULK_TIMEOUT_MS', 3600000),
    };
  }

  get retry() {
    return {
      /** Max retry attempts for worker failures */
      maxAttempts: this.getInt('RETRY_MAX_ATTEMPTS', 3),
      /** Delay between retry attempts (ms) */
      delayMs: this.getInt('RETRY_DELAY_MS', 1000),
    };
  }

  get jobResultsTtlSec(): number {
    return this.getInt('JOB_RESULTS_TTL_SEC', 86400);
  }

  /** Number of workers from WORKER_BASE_URLS */
  get workerCount(): number {
    const urls = this.configService.get<string>('WORKER_BASE_URLS') || '';
    const count = urls.split(',').filter(Boolean).length;
    return count > 0 ? count : 3;
  }
}
