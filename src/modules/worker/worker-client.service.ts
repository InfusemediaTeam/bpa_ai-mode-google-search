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
        // Try to parse JSON body for error responses (e.g., 422 with raw_text)
        let value: any = undefined;
        let errorText = '';
        try {
          const text = await r.text();
          value = JSON.parse(text);
          errorText = value?.error || value?.message || text?.slice(0, 200);
        } catch {
          errorText = 'Failed to parse error response';
        }
        return { ok: false, value, error: `HTTP ${r.status} - ${errorText}`, status: r.status };
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
      
      // Empty result (422) - include raw_text in error for fallback
      if (res.status === 422 && res.value?.error === 'empty_result') {
        const error = new Error(`Worker ${worker || 1}: HTTP 422 - empty_result`);
        const val = res.value as any;
        (error as any).raw_text = val.raw_text || '';
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
   * Search - try workers sequentially until one accepts
   * 
   * Workers return 423 instantly if busy, so sequential check is fast.
   * Bull handles concurrency - multiple jobs run in parallel on different workers.
   * 
   * NO retry when:
   * - Worker returned result (even empty) - 422 empty_result → job completes
   * - Worker is blocked by Google - 503 → job fails
   */
  async searchWithRetry(
    prompt: string, 
    _preferredWorker?: number,
  ): Promise<SearchResult & { usedWorker: number }> {
    const workerCount = this.getWorkerCount();
    let lastError: Error | null = null;
    
    // Try each worker - busy workers return 423 instantly
    for (let i = 1; i <= workerCount; i++) {
      try {
        const result = await this.search(prompt, i);
        this.logger.log(`Worker ${i} completed job`);
        
        // If json is empty, use raw_text as fallback
        const json = result.json || result.raw_text || '';
        return { json, raw_text: result.raw_text, usedWorker: i };
        
      } catch (err: any) {
        const errorMsg = err?.message || String(err);
        lastError = err;
        
        // Empty result (422) - job completes with raw_text only, no json
        if (errorMsg.includes('422') || errorMsg.includes('empty_result')) {
          const rawText = err?.raw_text || '';
          this.logger.warn(`Worker ${i} returned empty result (422), raw_text: ${rawText.length} chars`);
          return { json: '', raw_text: rawText, usedWorker: i };
        }
        
        // Blocked by Google - fail immediately
        if (err?.blocked === true) {
          throw err;
        }
        
        // Busy (423) or warming up (503) - try next worker instantly
        const isBusy = errorMsg.includes('423') || errorMsg.includes('Locked') || errorMsg.includes('busy');
        const isWarmingUp = errorMsg.includes('warming_up') || errorMsg.includes('warming up');
        if (isBusy || isWarmingUp) {
          this.logger.debug(`Worker ${i} is ${isBusy ? 'busy' : 'warming up'}, trying next...`);
          continue;
        }
        
        // Other error - try next worker
        this.logger.warn(`Worker ${i} error: ${errorMsg}`);
      }
    }
    
    // All workers busy - throw to let Bull retry later
    throw lastError || new Error('All workers are busy');
  }
}
