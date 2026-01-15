/**
 * Worker Client Service
 * Handles communication with browser-worker instances (Puppeteer-based)
 * Supports multiple workers with load balancing and retry logic
 */
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TimeoutsService } from '../../config/timeouts';

export interface SearchResult {
  json: string;
  raw_text?: string;
}

interface ErrorWithExtras extends Error {
  blocked?: boolean;
  raw_text?: string;
}

interface ErrorResponse {
  error?: string;
  message?: string;
  raw_text?: string;
  retry_other_worker?: boolean;
}

export interface WorkerHealth {
  ok: boolean;
  busy?: boolean;
  browser?: string;
  ready?: boolean;
  version?: string | null;
  chrome_alive?: boolean;
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
      .map((s) => (s || '').trim().replace(/\/$/, ''))
      .filter(Boolean);

    if (this.endpoints.length === 0) {
      throw new Error(
        'WORKER_BASE_URLS must contain at least one valid endpoint',
      );
    }
  }

  onModuleInit() {
    this.logger.log(
      `Worker endpoints configured: ${this.endpoints.join(', ')}`,
    );
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
    const idx =
      (worker && Number.isFinite(worker) ? Math.trunc(worker) : 1) - 1;
    if (idx < 0 || idx >= this.endpoints.length) {
      throw new Error(
        `Invalid worker index: ${worker}. Allowed range is 1..${this.endpoints.length}`,
      );
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
      const r = await fetch(url, {
        ...(init || {}),
        signal: controller.signal,
      } as RequestInit);
      if (!r.ok) {
        // Try to parse JSON body for error responses (e.g., 422 with raw_text)
        let value: T | undefined = undefined;
        let errorText = '';
        try {
          const text = await r.text();
          value = JSON.parse(text) as T;
          const errResp = value as unknown as ErrorResponse;
          errorText = errResp?.error || errResp?.message || text?.slice(0, 200);
        } catch {
          errorText = 'Failed to parse error response';
        }
        return {
          ok: false,
          value,
          error: `HTTP ${r.status} - ${errorText}`,
          status: r.status,
        };
      }
      const value = expectJson
        ? ((await r.json()) as T)
        : ((await r.text()) as unknown as T);
      return { ok: true, value, status: r.status };
    } catch (e: unknown) {
      const err = e as Error;
      return { ok: false, error: String(err?.message || e) };
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
      const res = await this.requestOne(
        base,
        '/health',
        { method: 'GET' },
        this.timeouts.worker.healthMs,
        true,
      );
      if (res.ok && res.value) return res.value as WorkerHealth;
      return { ok: false, error: res.error || 'unknown error' };
    } catch (e: unknown) {
      const err = e as Error;
      return { ok: false, error: String(err?.message || e) };
    }
  }

  /**
   * Warmup search tab on worker
   */
  async warmupSearchTab(worker?: number): Promise<boolean> {
    try {
      const base = this.getEndpoint(worker);
      const res = await this.requestOne(
        base,
        '/tabs/search',
        { method: 'POST' },
        this.timeouts.worker.warmupMs,
        false,
      );
      return !!res.ok;
    } catch {
      return false;
    }
  }

  /**
   * Restart browser on worker
   */
  async restartBrowser(
    worker?: number,
  ): Promise<{ ok: boolean; error?: string }> {
    this.logger.log('Restarting browser...');
    try {
      const base = this.getEndpoint(worker);
      const res = await this.requestOne(
        base,
        '/browser/restart',
        { method: 'POST' },
        this.timeouts.worker.restartMs,
        true,
      );
      if (res.ok) return { ok: true };
      return { ok: false, error: res.error };
    } catch (e: unknown) {
      const err = e as Error;
      return { ok: false, error: String(err?.message || e) };
    }
  }

  /**
   * Refresh session on worker
   */
  async refreshSession(
    worker?: number,
  ): Promise<{ ok: boolean; error?: string }> {
    this.logger.log('Refreshing worker session...');
    try {
      const base = this.getEndpoint(worker);
      const res = await this.requestOne(
        base,
        '/session/refresh',
        { method: 'POST' },
        this.timeouts.worker.refreshMs,
        true,
      );
      if (res.ok) return { ok: true };
      return { ok: false, error: res.error };
    } catch (e: unknown) {
      const err = e as Error;
      return { ok: false, error: String(err?.message || e) };
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
      raw_text?: string;
      retry_other_worker?: boolean;
    }>(base, '/search', init, this.timeouts.worker.searchMs, true);

    if (!res.ok || !res.value) {
      // Check if this is a blocked worker error (503 with retry_other_worker flag)
      if (res.status === 503 && res.value?.retry_other_worker) {
        this.logger.warn(
          `Worker ${worker || 1} is blocked: ${res.value.error || 'unknown'}`,
        );
        const error = new Error(
          `Worker ${worker || 1} blocked: ${res.value.error || 'This request is not supported'}`,
        );
        (error as ErrorWithExtras).blocked = true;
        throw error;
      }

      // Empty result (422) - include raw_text in error for fallback
      if (res.status === 422 && res.value?.error === 'empty_result') {
        const error = new Error(
          `Worker ${worker || 1}: HTTP 422 - empty_result`,
        );
        (error as ErrorWithExtras).raw_text = res.value?.raw_text || '';
        throw error;
      }

      this.logger.error(
        `Search failed on worker ${worker || 1}: ${res.error || 'no details'}`,
      );
      throw new Error(
        `Worker error (worker=${worker || 1}): ${res.error || 'request failed'}`,
      );
    }
    const data = res.value;
    if (!data.ok || !data.result) {
      throw new Error('Invalid response from worker');
    }
    return data.result;
  }

  /**
   * Search - find free worker and execute search
   *
   * Finds first available worker via health check, then sends request.
   * Retries indefinitely until a worker completes the job.
   *
   * Returns immediately when:
   * - Worker returned result (even empty) - 422 empty_result → job completes with raw_text
   *
   * Retries when:
   * - All workers busy (423) - waits and retries
   * - Worker blocked by Google - worker rotates proxy, retry with another
   * - Any other error - retry with another worker
   */
  /**
   * Find first available (not busy) worker
   * Returns worker number (1-based) or null if all busy
   */
  private async findFreeWorker(): Promise<number | null> {
    const workerCount = this.getWorkerCount();

    // Check all workers in parallel for speed
    const healthChecks = await Promise.all(
      Array.from({ length: workerCount }, (_, i) => this.health(i + 1)),
    );

    for (let i = 0; i < workerCount; i++) {
      const h = healthChecks[i];
      if (h.ok && !h.busy && h.ready !== false) {
        return i + 1; // 1-based index
      }
    }

    return null;
  }

  async searchWithRetry(
    prompt: string,
    preferredWorker?: number,
  ): Promise<SearchResult & { usedWorker: number }> {
    const retryDelayMs = 2000; // Wait 2 seconds between retries
    const maxAttempts = this.timeouts.retry.maxAttempts * 10; // 30 attempts max (circuit breaker)
    let attempt = 0;

    // Try preferred worker first if specified and valid
    if (preferredWorker && preferredWorker >= 1 && preferredWorker <= this.getWorkerCount()) {
      try {
        const health = await this.health(preferredWorker);
        if (health.ok && !health.busy && health.ready !== false) {
          this.logger.log(`Trying preferred worker ${preferredWorker}`);
          const result = await this.search(prompt, preferredWorker);
          this.logger.log(`Preferred worker ${preferredWorker} completed job`);
          const json = result.json || result.raw_text || '';
          return { json, raw_text: result.raw_text, usedWorker: preferredWorker };
        }
      } catch (err: unknown) {
        const errTyped = err as ErrorWithExtras;
        const errorMsg = errTyped?.message || String(err);
        
        // Empty result - return immediately
        if (errorMsg.includes('422') || errorMsg.includes('empty_result')) {
          const rawText = errTyped?.raw_text || '';
          this.logger.warn(`Preferred worker ${preferredWorker} returned empty result`);
          return { json: '', raw_text: rawText, usedWorker: preferredWorker };
        }
        
        // Other errors - fall through to dynamic selection
        this.logger.warn(`Preferred worker ${preferredWorker} failed: ${errorMsg}, falling back to dynamic selection`);
      }
    }

    // Dynamic worker selection with circuit breaker
    while (attempt < maxAttempts) {
      attempt++;

      // Find a free worker first
      const freeWorker = await this.findFreeWorker();

      if (freeWorker) {
        try {
          const result = await this.search(prompt, freeWorker);
          this.logger.log(`Worker ${freeWorker} completed job`);

          // If json is empty, use raw_text as fallback
          const json = result.json || result.raw_text || '';
          return { json, raw_text: result.raw_text, usedWorker: freeWorker };
        } catch (err: unknown) {
          const errTyped = err as ErrorWithExtras;
          const errorMsg = errTyped?.message || String(err);

          // Empty result (422) - job completes with raw_text only, no json
          if (errorMsg.includes('422') || errorMsg.includes('empty_result')) {
            const rawText = errTyped?.raw_text || '';
            this.logger.warn(
              `Worker ${freeWorker} returned empty result (422), raw_text: ${rawText.length} chars`,
            );
            return { json: '', raw_text: rawText, usedWorker: freeWorker };
          }

          // Blocked by Google - worker will rotate proxy, retry with another worker
          if (errTyped?.blocked === true) {
            this.logger.warn(
              `Worker ${freeWorker} blocked by Google, proxy rotating - retrying...`,
            );
            continue;
          }

          // Worker became busy between health check and search - retry
          const isBusy =
            errorMsg.includes('423') ||
            errorMsg.includes('Locked') ||
            errorMsg.includes('busy');
          if (isBusy) {
            this.logger.debug(
              `Worker ${freeWorker} became busy, retrying...`,
            );
            continue;
          }

          // Other error - log and retry with another worker
          this.logger.warn(`Worker ${freeWorker} error: ${errorMsg}, retrying...`);
          continue;
        }
      }

      // No free workers - wait and retry
      if (attempt % 10 === 0) {
        this.logger.log(
          `All workers busy, waiting... (attempt ${attempt}/${maxAttempts})`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
    }

    // Circuit breaker triggered - all attempts exhausted
    this.logger.error(
      `Circuit breaker triggered: Max attempts (${maxAttempts}) exhausted. All workers unavailable.`,
    );
    throw new Error(
      `Search failed: All workers unavailable after ${maxAttempts} attempts. Check worker health.`,
    );
  }
}
