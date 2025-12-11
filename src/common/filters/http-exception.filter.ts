import { ExceptionFilter, Catch, ArgumentsHost, HttpException, HttpStatus, Logger } from '@nestjs/common';
import { Request, Response } from 'express';
import { REQUEST_ID_HEADER } from '../interceptors/request-id.interceptor';

/**
 * Map HTTP status to standard error codes according to n8n contracts
 */
const STATUS_TO_ERROR_CODE: Record<number, string> = {
  400: 'BAD_REQUEST',
  401: 'UNAUTHORIZED',
  403: 'FORBIDDEN',
  404: 'NOT_FOUND',
  409: 'CONFLICT',
  412: 'PRECONDITION_FAILED',
  422: 'VALIDATION_ERROR',
  429: 'RATE_LIMITED',
  500: 'INTERNAL_ERROR',
  502: 'UPSTREAM_ERROR',
};

@Catch()
export class HttpExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(HttpExceptionFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    const request = ctx.getRequest<Request>();

    // Get request ID from request or generate
    const requestId = (request as any).requestId || 
                      request.headers[REQUEST_ID_HEADER.toLowerCase()] ||
                      request.headers['x-request-id'] ||
                      'unknown';

    // Set response header
    response.setHeader(REQUEST_ID_HEADER, requestId);

    let status: number = HttpStatus.INTERNAL_SERVER_ERROR;
    let message: string = 'Internal server error';
    let details: any;

    if (exception instanceof HttpException) {
      status = exception.getStatus();
      const exceptionResponse = exception.getResponse();
      
      if (typeof exceptionResponse === 'string') {
        message = exceptionResponse;
      } else if (typeof exceptionResponse === 'object') {
        const resp = exceptionResponse as any;
        
        // If response already has error object in contract format, use it directly
        if (resp.error && typeof resp.error === 'object' && resp.error.code) {
          response.status(status).json({
            error: resp.error,
            meta: {
              requestId,
            },
          });
          return;
        }
        
        message = resp.message || resp.error || 'An error occurred';
        
        // Handle validation errors from class-validator
        if (Array.isArray(resp.message)) {
          details = {
            fields: resp.message.map((msg: string) => ({
              field: 'unknown',
              code: 'VALIDATION_ERROR',
              message: msg,
            })),
          };
          message = 'Validation failed';
        }
      }
    } else if (exception instanceof Error) {
      status = HttpStatus.INTERNAL_SERVER_ERROR;
      message = exception.message || 'Internal server error';
      this.logger.error(`Unhandled exception: ${exception.message}`, exception.stack);
    } else {
      status = HttpStatus.INTERNAL_SERVER_ERROR;
      message = 'Internal server error';
      this.logger.error(`Unknown exception: ${exception}`);
    }

    const errorCode = STATUS_TO_ERROR_CODE[status] || 'INTERNAL_ERROR';

    const errorResponse = {
      error: {
        code: errorCode,
        message,
        ...(details && { details }),
      },
      meta: {
        requestId,
      },
    };

    response.status(status).json(errorResponse);
  }
}
