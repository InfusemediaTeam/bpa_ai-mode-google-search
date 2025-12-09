import { plainToInstance } from 'class-transformer';
import { IsString, IsNotEmpty, validateSync, IsOptional, IsNumber, Min, IsIn } from 'class-validator';

/**
 * Environment variables validation schema
 * 
 * REQUIRED for API service:
 * - REDIS_URL
 * - WORKER_BASE_URLS
 * 
 * Optional variables have sensible defaults.
 * Browser-worker specific vars (PY_*, PROXY_*, etc.) are not validated here
 * as they are used by Python workers, not the NestJS API.
 */
export class EnvironmentVariables {
  // ===========================================
  // REQUIRED - API will fail without these
  // ===========================================
  
  @IsString()
  @IsNotEmpty({ message: 'REDIS_URL is required' })
  REDIS_URL: string;

  @IsString()
  @IsNotEmpty({ message: 'WORKER_BASE_URLS is required (comma-separated list of worker endpoints)' })
  WORKER_BASE_URLS: string;

  // ===========================================
  // OPTIONAL - App configuration
  // ===========================================

  @IsNumber()
  @IsOptional()
  PORT?: number;

  @IsString()
  @IsOptional()
  @IsIn(['development', 'production', 'test'])
  NODE_ENV?: string;

  @IsString()
  @IsOptional()
  LOG_DIR?: string;

  // ===========================================
  // OPTIONAL - Cache & Job TTL
  // ===========================================

  @IsNumber()
  @IsOptional()
  @Min(60)
  CACHE_TTL_SEC?: number;

  @IsNumber()
  @IsOptional()
  @Min(60)
  JOB_RESULTS_TTL_SEC?: number;

  // ===========================================
  // OPTIONAL - Worker HTTP timeouts (ms)
  // ===========================================

  @IsNumber()
  @IsOptional()
  @Min(1000)
  WORKER_HEALTH_TIMEOUT_MS?: number;

  @IsNumber()
  @IsOptional()
  @Min(1000)
  WORKER_SEARCH_TIMEOUT_MS?: number;

  @IsNumber()
  @IsOptional()
  @Min(1000)
  WORKER_REFRESH_TIMEOUT_MS?: number;

  @IsNumber()
  @IsOptional()
  @Min(1000)
  WORKER_RESTART_TIMEOUT_MS?: number;

  @IsNumber()
  @IsOptional()
  @Min(1000)
  WORKER_WARMUP_TIMEOUT_MS?: number;

  // ===========================================
  // OPTIONAL - Bull queue timeouts (ms)
  // ===========================================

  /** Single search job timeout */
  @IsNumber()
  @IsOptional()
  @Min(1000)
  BULL_SEARCH_TIMEOUT_MS?: number;

  /** Bulk job timeout (1 hour default) */
  @IsNumber()
  @IsOptional()
  @Min(1000)
  BULL_BULK_TIMEOUT_MS?: number;

  // ===========================================
  // OPTIONAL - Retry configuration
  // ===========================================

  @IsNumber()
  @IsOptional()
  @Min(1)
  RETRY_MAX_ATTEMPTS?: number;

  @IsNumber()
  @IsOptional()
  @Min(100)
  RETRY_INITIAL_DELAY_MS?: number;

  @IsNumber()
  @IsOptional()
  @Min(1000)
  RETRY_MAX_DELAY_MS?: number;

  @IsNumber()
  @IsOptional()
  @Min(0)
  RETRY_WAIT_FOR_WORKER_MAX_MS?: number;

  @IsNumber()
  @IsOptional()
  @Min(1000)
  RETRY_HEALTH_CHECK_INTERVAL_MS?: number;

  // ===========================================
  // OPTIONAL - Reverse proxy / TLS
  // ===========================================

  @IsString()
  @IsOptional()
  DOMAIN?: string;

  @IsNumber()
  @IsOptional()
  API_PORT?: number;

  // Note: Browser-worker specific variables (PY_*, PROXY_*, SESSION_*, etc.)
  // are NOT validated here as they are used by Python workers directly
}

export function validate(config: Record<string, unknown>) {
  const validatedConfig = plainToInstance(EnvironmentVariables, config, {
    enableImplicitConversion: true,
  });

  const errors = validateSync(validatedConfig, {
    skipMissingProperties: false,
  });

  if (errors.length > 0) {
    const errorMessages = errors
      .map(err => {
        const constraints = err.constraints ? Object.values(err.constraints).join(', ') : 'Invalid value';
        return `  - ${err.property}: ${constraints}`;
      })
      .join('\n');
    
    throw new Error(`\n\nEnvironment validation failed:\n${errorMessages}\n\nPlease check your .env file.\n`);
  }

  return validatedConfig;
}
