# LLMCodeScanner 
Technical analysis tool for game codebases using DeepSeek AI.

## Features
- Automated Unity C# code analysis
- Context-aware technical documentation
- Parallel processing of code files
- Architecture report generation
- Directory-level summaries

## Usage
```bash
python cli.py <deepseek_api_key> <game_project_dir> [max_workers] [start_from]
```

## Configuration
Edit `config/game_context.md` to customize framework documentation.

## Outputs
- `technical_analysis/`: Per-file and per-directory reports
- `technical_architecture.md`: Full project analysis
- `analysis_errors.json`: Processing errors
