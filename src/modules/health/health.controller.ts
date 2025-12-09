import { Controller, Get } from '@nestjs/common';
import { ApiTags, ApiOperation, ApiResponse, ApiHeader } from '@nestjs/swagger';
import { RedisService } from '../redis/redis.service';
import { WorkerClientService } from '../worker/worker-client.service';

/**
 * Health Controller
 * 
 * API path follows n8n contract: /{businessFlow}/{tool}/v{major}/health
 */
@ApiTags('health')
@Controller('search-intelligence/searcher/v1')
@ApiHeader({ name: 'X-Request-Id', description: 'Request correlation ID', required: false })
export class HealthController {
  constructor(
    private readonly redis: RedisService,
    private readonly worker: WorkerClientService,
  ) {}

  @Get('health')
  @ApiOperation({ summary: 'Health check endpoint' })
  @ApiResponse({ status: 200, description: 'Service health status' })
  async getHealth() {
    const rtt = await this.redis.ping();
    const redisOk = typeof rtt === 'number';
    
    // Check all workers
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
    
    // Aggregate worker stats
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
        details: workersHealth.map(w => ({
          id: w.workerId,
          ok: w.ok,
          busy: ('busy' in w && w.busy) || false,
          ready: ('ready' in w && w.ready) || false,
          browser: ('browser' in w && w.browser) || 'unknown',
          version: ('version' in w && w.version) ?? null,
          error: w.ok ? null : (('error' in w && w.error) || 'unknown error'),
        })),
      },
      timestamp: new Date().toISOString(),
    };
  }
}
