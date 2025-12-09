import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';

/**
 * Standard API response format according to n8n contracts
 * All responses must follow: { data?, error?, meta: { requestId } }
 */

export class ApiErrorDetail {
  @ApiProperty({ description: 'Field name' })
  field: string;

  @ApiProperty({ description: 'Error code for this field' })
  code: string;

  @ApiProperty({ description: 'Human-readable error message' })
  message: string;
}

export class ApiError {
  @ApiProperty({ description: 'Error code in SNAKE_CASE format', example: 'VALIDATION_ERROR' })
  code: string;

  @ApiProperty({ description: 'Human-readable error message' })
  message: string;

  @ApiPropertyOptional({ description: 'Additional error details' })
  details?: {
    fields?: ApiErrorDetail[];
    [key: string]: any;
  };
}

export class ApiMeta {
  @ApiProperty({ description: 'Request correlation ID from X-Request-Id header' })
  requestId: string;

  @ApiPropertyOptional({ description: 'Processing time in milliseconds' })
  processingTimeMs?: number;

  @ApiPropertyOptional({ description: 'Pagination information' })
  pagination?: {
    totalItems?: number;
    itemsPerPage?: number;
    currentPage?: number;
    nextPageToken?: string;
  };
}

export class ApiResponse<T = any> {
  @ApiPropertyOptional({ description: 'Response data (present on success)' })
  data?: T;

  @ApiPropertyOptional({ description: 'Error information (present on failure)', type: ApiError })
  error?: ApiError;

  @ApiProperty({ description: 'Response metadata', type: ApiMeta })
  meta: ApiMeta;
}

/**
 * Helper to create success response
 */
export function createSuccessResponse<T>(data: T, requestId: string, processingTimeMs?: number): ApiResponse<T> {
  return {
    data,
    meta: {
      requestId,
      ...(processingTimeMs !== undefined && { processingTimeMs }),
    },
  };
}

/**
 * Helper to create error response
 */
export function createErrorResponse(
  code: string,
  message: string,
  requestId: string,
  details?: ApiError['details'],
): ApiResponse<never> {
  return {
    error: {
      code,
      message,
      ...(details && { details }),
    },
    meta: {
      requestId,
    },
  };
}
