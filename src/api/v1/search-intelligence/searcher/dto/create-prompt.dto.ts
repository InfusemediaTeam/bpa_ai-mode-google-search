import { ApiProperty } from '@nestjs/swagger';
import { IsString, IsNotEmpty, MaxLength } from 'class-validator';

export class CreatePromptDto {
  @ApiProperty({
    description: 'The prompt text to process',
    example: 'What is the capital of France?',
    maxLength: 10000,
  })
  @IsString()
  @IsNotEmpty()
  @MaxLength(10000)
  prompt: string;
}
