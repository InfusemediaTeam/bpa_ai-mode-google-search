import { ApiProperty } from '@nestjs/swagger';
import { IsArray, IsString, IsNotEmpty, MaxLength, ArrayMinSize, ArrayMaxSize, ValidateNested } from 'class-validator';
import { Type } from 'class-transformer';

class PromptItem {
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

export class CreateBulkPromptsDto {
  @ApiProperty({
    description: 'Array of prompts to process in bulk',
    type: [PromptItem],
    minItems: 1,
    maxItems: 100,
    example: [
      { prompt: 'What is the capital of France?' },
      { prompt: 'What is the capital of Germany?' },
    ],
  })
  @IsArray()
  @ArrayMinSize(1)
  @ArrayMaxSize(100)
  @ValidateNested({ each: true })
  @Type(() => PromptItem)
  prompts: PromptItem[];
}
