import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';

export type JobState = 'pending' | 'processing' | 'completed' | 'failed';

export class JobProgressDto {
  @ApiPropertyOptional({ description: 'Current stage of processing' })
  stage?: string;

  @ApiPropertyOptional({ description: 'Worker ID processing this job' })
  workerId?: number;
}

export class JobResultDto {
  @ApiProperty({ description: 'Text result from the prompt processing' })
  text: string;

  @ApiPropertyOptional({ description: 'HTML content if available' })
  html?: string;

  @ApiPropertyOptional({ description: 'Worker ID that processed this job' })
  usedWorker?: number;
}

export class JobStatusDto {
  @ApiProperty({ description: 'Unique job identifier' })
  jobId: string;

  @ApiProperty({ 
    description: 'Current job status',
    enum: ['pending', 'processing', 'completed', 'failed'],
  })
  status: JobState;

  @ApiPropertyOptional({ description: 'Job progress information', type: JobProgressDto })
  progress?: JobProgressDto;

  @ApiPropertyOptional({ description: 'Job result (only when completed)', type: JobResultDto })
  result?: JobResultDto | null;

  @ApiPropertyOptional({ description: 'Error message (only when failed)' })
  error?: string | null;

  @ApiProperty({ description: 'Job creation timestamp' })
  createdAt: string;

  @ApiPropertyOptional({ description: 'Job completion timestamp' })
  completedAt?: string | null;
}

export class CreateJobResponseDto {
  @ApiProperty({ description: 'Unique job identifier' })
  jobId: string;
}
