import { Module, Global } from '@nestjs/common';
import { WinstonModule } from 'nest-winston';
import * as winston from 'winston';

const logFormat = winston.format.combine(
  winston.format.timestamp(),
  winston.format.errors({ stack: true }),
  winston.format.printf(({ timestamp, level, message, context, stack }) => {
    const ctx = context ? `[${context}]` : '';
    const stackTrace = stack ? `\n${stack}` : '';
    return `${timestamp} ${level.toUpperCase()} ${ctx} ${message}${stackTrace}`;
  }),
);

@Global()
@Module({
  imports: [
    WinstonModule.forRoot({
      transports: [
        new winston.transports.Console({
          format: winston.format.combine(
            winston.format.colorize({ all: true }),
            logFormat,
          ),
        }),
      ],
    }),
  ],
})
export class LoggingModule {}
