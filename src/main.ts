import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { ValidationPipe } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { WINSTON_MODULE_NEST_PROVIDER } from 'nest-winston';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { json, urlencoded } from 'express';
import { RequestIdInterceptor } from './common/interceptors/request-id.interceptor';
import { HttpExceptionFilter } from './common/filters/http-exception.filter';

async function bootstrap() {
  const app = await NestFactory.create(AppModule, { 
    bufferLogs: true,
    bodyParser: false,
  });
  app.useLogger(app.get(WINSTON_MODULE_NEST_PROVIDER));
  
  const configService = app.get(ConfigService);
  
  // Body size limits
  app.use(json({ limit: '10mb' }));
  app.use(urlencoded({ limit: '10mb', extended: true }));
  
  // Global interceptors and filters (n8n contract compliance)
  app.useGlobalInterceptors(new RequestIdInterceptor());
  app.useGlobalFilters(new HttpExceptionFilter());
  
  // Enable validation
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );
  
  // Swagger/OpenAPI documentation
  const port = configService.get<number>('PORT') || 3100;
  const domain = configService.get<string>('DOMAIN');
  
  const documentBuilder = new DocumentBuilder()
    .setTitle('Universal Prompt Service API')
    .setDescription('Universal service for processing prompts via worker pool. API follows n8n contracts.')
    .setVersion('1.0')
    .addTag('search-intelligence/searcher', 'Prompt processing operations')
    .addTag('health', 'Health check endpoints');
  
  if (domain) {
    documentBuilder.addServer(`https://${domain}`, 'Production');
  } else {
    documentBuilder.addServer(`http://localhost:${port}`, 'Local Development');
  }
  
  const config = documentBuilder.build();
  
  const document = SwaggerModule.createDocument(app, config);
  SwaggerModule.setup('api/docs', app, document, {
    customSiteTitle: 'Universal Prompt Service API Docs',
    customCss: '.swagger-ui .topbar { display: none }',
  });
  
  await app.listen(port);
  console.log(`Application is running on: http://localhost:${port}`);
  console.log(`Swagger docs: http://localhost:${port}/api/docs`);
  console.log(`API base path: http://localhost:${port}/search-intelligence/searcher/v1`);
}
bootstrap();
