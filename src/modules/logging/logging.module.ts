import { Module, Global } from '@nestjs/common';
import { WinstonModule } from 'nest-winston';
import * as winston from 'winston';
import 'winston-daily-rotate-file';

const LOG_DIR = process.env.LOG_DIR || 'logs';

const logFormat = winston.format.combine(
  winston.format.timestamp(),
  winston.format.errors({ stack: true }),
  winston.format.printf(({ timestamp, level, message, context, stack }) => {
    const ctx = context ? `[${context}]` : '';
    const stackTrace = stack ? `\n${stack}` : '';
    return `${timestamp} ${level.toUpperCase()} ${ctx} ${message}${stackTrace}`;
  }),
);

// JSON format for file logs (easier to parse)
const jsonFormat = winston.format.combine(
  winston.format.timestamp(),
  winston.format.errors({ stack: true }),
  winston.format.json(),
);

@Global()
@Module({
  imports: [
    WinstonModule.forRoot({
      transports: [
        // Console output with colors
        new winston.transports.Console({
          format: winston.format.combine(
            winston.format.colorize({ all: true }),
            logFormat,
          ),
        }),
        // Daily rotating file for all logs
        new winston.transports.DailyRotateFile({
          dirname: LOG_DIR,
          filename: 'app-%DATE%.log',
          datePattern: 'YYYY-MM-DD',
          maxSize: '50m',
          maxFiles: '14d',
          format: jsonFormat,
        }),
        // Separate file for errors only
        new winston.transports.DailyRotateFile({
          dirname: LOG_DIR,
          filename: 'error-%DATE%.log',
          datePattern: 'YYYY-MM-DD',
          maxSize: '50m',
          maxFiles: '30d',
          level: 'error',
          format: jsonFormat,
        }),
      ],
    }),
  ],
})
export class LoggingModule {}
