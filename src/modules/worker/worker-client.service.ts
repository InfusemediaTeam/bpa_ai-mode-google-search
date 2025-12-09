/**
 * Worker Client Service
 * Handles communication with browser-worker instances (Puppeteer-based)
 * Supports multiple workers with load balancing and retry logic
 */
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TimeoutsService } from '../../config/timeouts';

export interface SearchResult {
  text: string;
  html: string;
  raw_text?: string;
}

export interface WorkerHealth {
  ok: boolean;
  busy?: boolean;
  browser?: string;
  ready?: boolean;
  version?: string | null;
  error?: string;
}

@Injectable()
export class WorkerClientService implements OnModuleInit {
  private readonly logger = new Logger(WorkerClientService.name);
  private readonly endpoints: string[];

  constructor(
    private readonly configService: ConfigService,
    private readonly timeouts: TimeoutsService,
  ) {
    // WORKER_BASE_URLS is required - validated by ConfigModule
    const workerUrls = this.configService.get<string>('WORKER_BASE_URLS');
    
    if (!workerUrls) {
      throw new Error('WORKER_BASE_URLS environment variable is required');
    }

    this.endpoints = workerUrls
      .split(',')
      .map(s => (s || '').trim().replace(/\/$/, ''))
      .filter(Boolean);

    if (this.endpoints.length === 0) {
      throw new Error('WORKER_BASE_URLS must contain at least one valid endpoint');
    }
  }

  onModuleInit() {
    this.logger.log(`Worker endpoints configured: ${this.endpoints.join(', ')}`);
  }

  /**
   * Number of configured worker endpoints
   */
  public getWorkerCount(): number {
    return this.endpoints.length;
  }

  /**
   * Resolve base URL for specific worker (1-based index). Defaults to 1.
   */
  private getEndpoint(worker?: number): string {
    const idx = (worker && Number.isFinite(worker) ? Math.trunc(worker as number) : 1) - 1;
    if (idx < 0 || idx >= this.endpoints.length) {
      throw new Error(`Invalid worker index: ${worker}. Allowed range is 1..${this.endpoints.length}`);
    }
    return this.endpoints[idx];
  }

  /**
   * Make HTTP request to worker with timeout
   */
  private async requestOne<T = any>(
    base: string,
    path: string,
    init: RequestInit,
    timeoutMs: number,
    expectJson: boolean = true,
  ): Promise<{ ok: boolean; value?: T; status?: number; error?: string }> {
    const url = `${base}${path}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      this.logger.debug(`Requesting ${url}`);
      const r = await fetch(url, { ...(init || {}), signal: controller.signal } as RequestInit);
      if (!r.ok) {
        const text = await r.text();
        return { ok: false, error: `HTTP ${r.status} - ${text?.slice(0, 200)}`, status: r.status };
      }
      const value = expectJson ? ((await r.json()) as T) : ((await r.text()) as unknown as T);
      return { ok: true, value, status: r.status };
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) };
    } finally {
      clearTimeout(timeout);
    }
  }

  /**
   * Check worker health
   */
  async health(worker?: number): Promise<WorkerHealth> {
    try {
      const base = this.getEndpoint(worker);
      const res = await this.requestOne(base, '/health', { method: 'GET' }, this.timeouts.worker.healthMs, true);
      if (res.ok) return res.value as any;
      return { ok: false, error: res.error || 'unknown error' };
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) };
    }
  }

  /**
   * Warmup search tab on worker
   */
  async warmupSearchTab(worker?: number): Promise<boolean> {
    try {
      const base = this.getEndpoint(worker);
      const res = await this.requestOne(base, '/tabs/search', { method: 'POST' }, this.timeouts.worker.warmupMs, false);
      return !!res.ok;
    } catch {
      return false;
    }
  }

  /**
   * Restart browser on worker
   */
  async restartBrowser(worker?: number): Promise<{ ok: boolean; error?: string }> {
    this.logger.log('Restarting browser...');
    try {
      const base = this.getEndpoint(worker);
      const res = await this.requestOne(base, '/browser/restart', { method: 'POST' }, this.timeouts.worker.restartMs, true);
      if (res.ok) return { ok: true };
      return { ok: false, error: res.error };
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) };
    }
  }

  /**
   * Refresh session on worker
   */
  async refreshSession(worker?: number): Promise<{ ok: boolean; error?: string }> {
    this.logger.log('Refreshing worker session...');
    try {
      const base = this.getEndpoint(worker);
      const res = await this.requestOne(base, '/session/refresh', { method: 'POST' }, this.timeouts.worker.refreshMs, true);
      if (res.ok) return { ok: true };
      return { ok: false, error: res.error };
    } catch (e: any) {
      return { ok: false, error: String(e?.message || e) };
    }
  }

  /**
   * Execute search on specific worker
   */
  async search(prompt: string, worker?: number): Promise<SearchResult> {
    const init: RequestInit = {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ prompt }),
    } as RequestInit;

    const base = this.getEndpoint(worker);
    const res = await this.requestOne<{ 
      ok: boolean; 
      result?: SearchResult;
      error?: string;
      retry_other_worker?: boolean;
    }>(
      base,
      '/search',
      init,
      this.timeouts.worker.searchMs,
      true,
    );

    if (!res.ok || !res.value) {
      // Check if this is a blocked worker error (503 with retry_other_worker flag)
      if (res.status === 503 && res.value?.retry_other_worker) {
        this.logger.warn(`Worker ${worker || 1} is blocked: ${res.value.error || 'unknown'}`);
        const error = new Error(`Worker ${worker || 1} blocked: ${res.value.error || 'This request is not supported'}`);
        (error as any).blocked = true;
        throw error;
      }
      
      this.logger.error(`Search failed on worker ${worker || 1}: ${res.error || 'no details'}`);
      throw new Error(`Worker error (worker=${worker || 1}): ${res.error || 'request failed'}`);
    }
    const data = res.value;
    if (!data.ok || !data.result) {
      throw new Error('Invalid response from worker');
    }
    return data.result;
  }

  /**
   * Wait for at least one healthy worker to become available
   */
  private async waitForHealthyWorker(timeoutMs: number): Promise<number> {
    const startTime = Date.now();
    const workerCount = this.getWorkerCount();
    let attempt = 0;
    
    while (Date.now() - startTime < timeoutMs) {
      attempt++;
      this.logger.log(`Checking for healthy workers (attempt ${attempt})...`);
      
      for (let i = 1; i <= workerCount; i++) {
        try {
          const healthResult = await this.health(i);
          if (healthResult.ok && healthResult.ready) {
            this.logger.log(`Worker ${i} is healthy and ready`);
            return i;
          }
        } catch (err) {
          // Continue checking other workers
        }
      }
      
      const remainingTime = timeoutMs - (Date.now() - startTime);
      if (remainingTime > 0) {
        const waitTime = Math.min(this.timeouts.retry.healthCheckIntervalMs, remainingTime);
        this.logger.warn(`No healthy workers found, waiting ${waitTime}ms before retry...`);
        await new Promise(resolve => setTimeout(resolve, waitTime));
      }
    }
    
    throw new Error(`No healthy workers available after ${Math.round(timeoutMs / 1000)}s timeout`);
  }

  /**
   * Search with retry logic and worker failover
   * - Tries preferred worker first, then others
   * - If all workers fail, waits for workers to recover
   * - Keeps retrying until success or max wait time
   */
  async searchWithRetry(
    prompt: string, 
    preferredWorker?: number, 
    options?: {
      maxAttempts?: number;
      waitForRecovery?: boolean;
      maxWaitMs?: number;
    }
  ): Promise<SearchResult & { usedWorker: number }> {
    const maxAttempts = options?.maxAttempts ?? this.timeouts.retry.maxAttempts;
    const waitForRecovery = options?.waitForRecovery ?? true;
    const maxWaitMs = options?.maxWaitMs ?? this.timeouts.retry.waitForWorkerMaxMs;
    
    const errors: Array<{ worker: number; attempt: number; error: string; timestamp: Date }> = [];
    const workerCount = this.getWorkerCount();
    const startTime = Date.now();
    
    // Build list of workers to try
    const workersToTry: number[] = [];
    if (preferredWorker && preferredWorker >= 1 && preferredWorker <= workerCount) {
      workersToTry.push(preferredWorker);
    }
    // Add other workers in sequence
    for (let i = 1; i <= workerCount; i++) {
      if (i !== preferredWorker) {
        workersToTry.push(i);
      }
    }
    
    let globalAttempt = 0;
    let delay = this.timeouts.retry.initialDelayMs;
    
    while (true) {
      globalAttempt++;
      const elapsedMs = Date.now() - startTime;
      
      // Check if we exceeded max wait time
      if (waitForRecovery && elapsedMs > maxWaitMs) {
        const errorSummary = errors.slice(-10).map(e => 
          `[${e.timestamp.toISOString()}] worker ${e.worker} (attempt ${e.attempt}): ${e.error}`
        ).join('\n  ');
        throw new Error(
          `Search failed: No healthy workers after ${Math.round(elapsedMs / 1000)}s.\n` +
          `Last errors:\n  ${errorSummary}`
        );
      }
      
      // Try all available workers in this round
      for (let i = 0; i < workersToTry.length; i++) {
        const workerToUse = workersToTry[i];
        
        try {
          this.logger.debug(`Search global attempt ${globalAttempt}, worker ${workerToUse} (${i + 1}/${workersToTry.length})`);
          const result = await this.search(prompt, workerToUse);
          
          // Success!
          if (globalAttempt > 1 || i > 0) {
            this.logger.warn(
              `Search succeeded on worker ${workerToUse} after ${globalAttempt} rounds and ${errors.length} failed attempts ` +
              `(elapsed: ${Math.round(elapsedMs / 1000)}s)`
            );
          }
          return { ...result, usedWorker: workerToUse };
          
        } catch (err: any) {
          const errorMsg = err?.message || String(err);
          const isBlocked = err?.blocked === true;
          
          errors.push({ 
            worker: workerToUse, 
            attempt: globalAttempt, 
            error: errorMsg,
            timestamp: new Date()
          });
          
          // Check if worker is blocked - skip immediately
          if (isBlocked) {
            this.logger.error(
              `Worker ${workerToUse} is BLOCKED (${errorMsg}). ` +
              `Immediately trying next worker...`
            );
            continue;
          }
          
          // Check if worker is busy (423 Locked) - skip to next worker immediately
          const isBusy = errorMsg.includes('423') || errorMsg.includes('Locked') || errorMsg.includes('busy');
          if (isBusy) {
            this.logger.debug(`Worker ${workerToUse} is busy (423 Locked), immediately trying next worker...`);
            continue;
          }
          
          this.logger.warn(
            `Search failed on worker ${workerToUse} ` +
            `(global attempt ${globalAttempt}, worker attempt ${i + 1}/${workersToTry.length}): ${errorMsg}`
          );
          
          // Small delay between workers in same round for other errors
          if (i < workersToTry.length - 1) {
            await new Promise(resolve => setTimeout(resolve, 500));
          }
        }
      }
      
      // All workers failed in this round
      if (!waitForRecovery) {
        const errorSummary = errors.map(e => `worker ${e.worker}: ${e.error}`).join('; ');
        throw new Error(`All ${workerCount} workers failed (attempt ${globalAttempt}): ${errorSummary}`);
      }
      
      if (globalAttempt >= maxAttempts && maxAttempts > 0) {
        this.logger.error(`Max attempts (${maxAttempts}) reached, but will continue waiting for healthy worker...`);
      }
      
      // Wait before next round with exponential backoff
      this.logger.warn(
        `All ${workerCount} workers failed in round ${globalAttempt}. ` +
        `Waiting ${delay}ms before next attempt... (elapsed: ${Math.round(elapsedMs / 1000)}s)`
      );
      await new Promise(resolve => setTimeout(resolve, delay));
      
      // Exponential backoff with max limit
      delay = Math.min(delay * 2, this.timeouts.retry.maxDelayMs);
      
      // Try to find a healthy worker proactively
      if (globalAttempt % 3 === 0) {
        try {
          const healthyWorker = await this.waitForHealthyWorker(this.timeouts.retry.healthCheckIntervalMs);
          this.logger.log(`Found healthy worker ${healthyWorker}, will prioritize it in next attempt`);
          const idx = workersToTry.indexOf(healthyWorker);
          if (idx > 0) {
            workersToTry.splice(idx, 1);
            workersToTry.unshift(healthyWorker);
          }
        } catch {
          // No healthy workers yet, continue with retry
        }
      }
    }
  }
}
