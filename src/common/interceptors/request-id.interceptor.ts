import { Injectable, NestInterceptor, ExecutionContext, CallHandler, HttpException, HttpStatus } from '@nestjs/common';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

export const REQUEST_ID_HEADER = 'X-Request-Id';

/**
 * Interceptor to handle X-Request-Id header
 * - X-Request-Id is REQUIRED per n8n contract
 * - Returns 400 BAD_REQUEST if header is missing
 * - Adds X-Request-Id to response headers
 * - Wraps response in standard format with meta.requestId
 */
@Injectable()
export class RequestIdInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    const ctx = context.switchToHttp();
    const request = ctx.getRequest();
    const response = ctx.getResponse();
    const startTime = Date.now();

    // X-Request-Id is REQUIRED
    const requestId = request.headers[REQUEST_ID_HEADER.toLowerCase()] || 
                      request.headers['x-request-id'];
    
    if (!requestId) {
      throw new HttpException({
        error: {
          code: 'BAD_REQUEST',
          message: 'Missing required header: X-Request-Id',
        },
        meta: {
          requestId: 'unknown',
        },
      }, HttpStatus.BAD_REQUEST);
    }

    // Store in request for later use
    request.requestId = requestId;

    // Set response header
    response.setHeader(REQUEST_ID_HEADER, requestId);

    return next.handle().pipe(
      map((data) => {
        const processingTimeMs = Date.now() - startTime;

        // If response already has meta, just ensure requestId is there
        if (data && typeof data === 'object' && 'meta' in data) {
          return {
            ...data,
            meta: {
              ...data.meta,
              requestId,
              processingTimeMs,
            },
          };
        }

        // Wrap in standard format
        return {
          data,
          meta: {
            requestId,
            processingTimeMs,
          },
        };
      }),
    );
  }
}
