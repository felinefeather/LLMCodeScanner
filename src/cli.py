import asyncio
import sys
from pathlib import Path
from .core import GameCodeProcessor

async def main():
    if len(sys.argv) < 3:
        print("Usage: python -m game_analyzer <api_key> <game_project_dir> [max_workers] [start_from]")
        sys.exit(1)
    
    api_key = sys.argv[1]
    game_dir = Path(sys.argv[2])
    max_workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    start_from = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    
    async with GameCodeProcessor(api_key, max_workers) as processor:
        await processor.process_directory(game_dir)
    
    print(f"Analysis complete. Results in {game_dir}/technical_analysis/")

if __name__ == "__main__":
    asyncio.run(main())