import os
import re
import asyncio
import aiohttp
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from .models import ProcessingError
from .utils import logger
from .config import DEFAULT_GAME_CONTEXT
import json

class GameCodeProcessor:
    def __init__(self, api_key: str, max_workers: int = 8, start_from = 0, game_context: str = "", module_name: str = ""):
        self.api_key = api_key
        self.max_workers = max_workers
        self.game_context = game_context or DEFAULT_GAME_CONTEXT
        self.start_from = start_from
        self.module_name = module_name or "Assembly-CSharp"
        self.errors: List[ProcessingError] = []
        self.session: Optional[aiohttp.ClientSession] = None
        self.file_counter = 0
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=aiohttp.ClientTimeout(total=60*10)  # 10 minutes timeout
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def record_error(self, file_path: str, error_type: str, error_msg: str):
        error = ProcessingError(file_path, error_type, error_msg)
        self.errors.append(error)
        logger.error(f"Error processing {file_path}: {error_type} - {error_msg}")
    
    def preprocess_code(self, code: str) -> str:
        """Clean code while preserving structure"""
        try:
            # Remove comments but keep #regions and #defines
            lines = []
            for line in code.split('\n'):
                stripped = line.strip()
                if stripped.startswith('//'):
                    continue
                if '//' in line:
                    line = line.split('//')[0]
                if line.strip():
                    lines.append(line)
            
            # Remove duplicate blank lines
            cleaned = '\n'.join(lines)
            cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
            return cleaned
        except Exception as e:
            logger.warning(f"Preprocessing error: {str(e)}")
            return code

    async def analyze_with_deepseek(self, prompt: str, is_many_files: bool, chunk_size: int) -> str:
        """Analyze with precise technical focus and game context hints"""
        if not self.session:
            raise RuntimeError("Session not initialized")
        
        try:
            if is_many_files:
                system_message = (
                    f"{self.game_context}\n\n"
                    "Analyze these code files technically. For each:\n"
                    "1. If under 10 lines: Show exact structure\n"
                    "2. Otherwise: Describe concrete implementation\n\n"
                    "Format:\n"
                    "- [filename]: [Specific technical content]\n\n"
                    "Examples:\n"
                    "- PoseType.cs: Bit flag Enum {{stand,crouch,down,back}}\n"
                    "- DamageSystem.cs: Calculates damage using Attack-Defense formula\n"
                    "- Inventory.cs: Dictionary<ItemID, int> with serialization"
                )
            else:
                system_message = (
                    f"{self.game_context}\n\n"
                    "Analyze this code module in depth:\n"
                    "1. Technical architecture (classes, patterns)\n"
                    "2. Implementation details\n"
                    "3. Game-specific adaptations\n\n"
                    "Omit trivial details but cover all key components."
                )
            
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 8192  # Using full context window
            }
            
            async with self.session.post(
                "https://api.deepseek.com/v1/chat/completions",
                json=payload
            ) as response:
                response.raise_for_status()
                result = await response.json()
                return result['choices'][0]['message']['content']
        
        except Exception as e:
            raise RuntimeError(f"API request failed: {str(e)}")

    async def process_chunk(self, chunk: List[Tuple[Path, str]], output_dir: Path) -> Dict:
        """Process a chunk and return analysis metadata"""
        self.file_counter += len(chunk)
        chunk_id = f"{self.file_counter:06d}"
        output_path = output_dir / f"analysis_{chunk_id}.md"

        if output_path.exists() and self.file_counter <= self.start_from:
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()
            return {
                'chunk_id': chunk_id,
                'files': [str(p) for p, _ in chunk],
                'analysis': existing_content,
                'directory': str(chunk[0][0].parent)
            }

        combined_code = "\n\n".join([f"// File: {rel_path}\n{content}" for rel_path, content in chunk])
        
        # Determine analysis type
        avg_size = sum(len(c[1]) for c in chunk) / len(chunk)
        is_many_files = len(chunk) > 5 and avg_size < 2000  # Many small files
        
        try:
            analysis = await self.analyze_with_deepseek(combined_code, is_many_files, len(combined_code))
            
            # Save detailed analysis
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"# Technical Analysis - Chunk {chunk_id}\n\n")
                f.write(f"**Files:** {len(chunk)} | **Total Size:** {len(combined_code)} chars\n\n")
                f.write("\n## Analysis:\n")
                f.write(analysis)
            
            return {
                'chunk_id': chunk_id,
                'files': [str(p) for p, _ in chunk],
                'analysis': analysis,
                'directory': str(chunk[0][0].parent)
            }
        except Exception as e:
            error_msg = (
                f"API request failed for chunk {chunk_id}\n\n"
                f"Prompt:\n{combined_code[:]}...\n\n"
                f"Error: {str(e)}"
            )
            self.record_error(f"chunk_{chunk_id}", "AnalysisError", error_msg)
            return {
                'chunk_id': chunk_id,
                'error': error_msg
            }

    async def process_directory(self, root_dir: Path):
        """Process all code with enhanced technical focus"""
        analysis_dir = root_dir / "technical_analysis"
        analysis_dir.mkdir(exist_ok=True)
        
        # First pass: Collect all files with size
        all_files = []
        for dirpath, _, filenames in os.walk(root_dir):
            for filename in filenames:
                if filename.endswith('.cs'):
                    full_path = Path(dirpath) / filename
                    try:
                        with open(full_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        cleaned = self.preprocess_code(content)
                        all_files.append((
                            full_path,
                            full_path.relative_to(root_dir),
                            cleaned,
                            len(cleaned.encode('utf-8'))
                        ))
                    except Exception as e:
                        self.record_error(str(full_path), "FileReadError", str(e))
        
        # Sort by directory then size (small files first)
        all_files.sort(key=lambda x: (str(x[0].parent), x[3]))
        
        # Create chunks with directory affinity
        chunks = []
        current_chunk = []
        current_size = 0
        MAX_CHUNK_SIZE = 120 * 1024  # 120KB to stay under token limit
        MAX_CHUNK_NUM = 8
        
        for full_path, rel_path, content, size in all_files:
            if len(current_chunk) > MAX_CHUNK_NUM or current_size + size > MAX_CHUNK_SIZE and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
            
            current_chunk.append((rel_path, content))
            current_size += size
        
        if current_chunk:
            chunks.append(current_chunk)
        
        # Process chunks with enhanced parallelism
        semaphore = asyncio.Semaphore(self.max_workers)
        
        async def limited_task(chunk):
            async with semaphore:
                return await self.process_chunk(chunk, analysis_dir)
        
        chunk_results = await asyncio.gather(
            *[limited_task(chunk) for chunk in chunks],
            return_exceptions=True
        )

        print("chunks completed")
        
        # Generate directory summaries
        await self.generate_directory_summaries(analysis_dir, chunk_results)
        
        # Generate full architecture report
        await self.generate_architecture_report(root_dir, chunk_results)
        
        # Save error report
        if self.errors:
            with open(root_dir / "analysis_errors.json", 'w', encoding='utf-8') as f:
                json.dump([e.__dict__ for e in self.errors], f, indent=2)

    async def generate_directory_summaries(self, analysis_dir: Path, chunk_results: List[Dict]):
        """Create per-directory technical summaries with AI analysis"""
        dir_map = {}
        
        for result in chunk_results:
            if 'error' in result:
                continue
            
            dir_path = result['directory']
            if dir_path not in dir_map:
                dir_map[dir_path] = {
                    'chunks': [],
                    'files': set(),
                    'analyses': []
                }
            
            dir_map[dir_path]['chunks'].append(result['chunk_id'])
            dir_map[dir_path]['files'].update(result['files'])
            dir_map[dir_path]['analyses'].append(result['analysis'])
        
        # Process directories with AI summarization
        for dir_path, data in dir_map.items():
            summary_path = analysis_dir / f"summary_{Path(dir_path).name}.md"
            
            if len(data['chunks']) > 1:
                # AI-generated summary for multi-chunk directories
                prompt = (
                    "Analyze these code chunks. Summarize:\n"
                    "0. **Overall purpose of the module.**\n"
                    "1. **Structure** - Core components, hierarchy, data flow\n"
                    "2. **Modules** - files' purpose, key functions, interfaces\n"
                    "3. **Connections** - Dependencies, external integrations\n\n"
                    "**Rules:**\n"
                    "- Group logically, not by chunk order.\n"
                    "- Mark inferences clearly. Be technical, detailed and structured.\n\n"
                    f"Directory: {dir_path}\n"
                    f"Files: {len(data['files'])}\n\n"
                    "Code chunks:\n"
                    + "\n\n---\n\n".join(data['analyses'])
                )
                
                try:
                    summary = await self.analyze_with_deepseek(prompt, False, 0)
                    with open(summary_path, 'w', encoding='utf-8') as f:
                        f.write(f"# Directory Technical Summary: {dir_path}\n\n")
                        f.write(f"**Total Files:** {len(data['files'])}\n")
                        f.write(f"**Analysis Chunks:** {', '.join(data['chunks'])}\n\n")
                        f.write(summary)
                except Exception as e:
                    error_msg = f"Directory summary failed:\n\nPrompt:\n{prompt}\n\nError: {str(e)}"
                    self.record_error(str(summary_path), "SummaryError", error_msg)
                    with open(summary_path, 'w', encoding='utf-8') as f:
                        f.write(f"# Summary Generation Failed\n\n{error_msg}")
            else:
                # Single chunk - just store the analysis
                with open(summary_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Single Chunk Analysis: {dir_path}\n\n")
                    f.write(data['analyses'][0])

    async def generate_architecture_report(self, root_dir: Path, chunk_results: List[Dict]):
        """Generate comprehensive technical architecture document"""
        # Collect all summary files
        summary_files = list((root_dir / "technical_analysis").glob("summary_*.md"))
        summary_contents = []
        
        for sf in summary_files:
            try:
                with open(sf, 'r', encoding='utf-8') as f:
                    summary_contents.append(f.read())
            except Exception as e:
                self.record_error(str(sf), "SummaryReadError", str(e))
        
        prompt = f"""
            Please read and organize the following code, and provide a detailed explanation of {self.module_name}. Output in English. 

            I want you to approach this from a code editor's perspective (i.e., "what functionality exists where; what functionality is absent from {self.module_name}"), using:
            1. Concrete features and structural framework as hierarchy levels
            2. The module's specific data structures as narrative threads
            3. Present it logically, systematically, and structurally with detailed depth.

            """


        prompt_parts = [
            f"{self.game_context}\n\n",
            prompt,
            "Directory summaries:\n"
        ]
        
        prompt_parts.extend(f"\n=== {sf.name} ===\n{content[:]}"  # Truncate very long summaries
                        for sf, content in zip(summary_files, summary_contents))
        
        try:
            report = await self.analyze_with_deepseek(''.join(prompt_parts), False, 0)
            
            with open(root_dir / "technical_architecture.md", 'w', encoding='utf-8') as f:
                f.write("# Game Technical Architecture\n\n")
                f.write(f"## Framework Context\n{self.game_context}\n\n")
                f.write("## Comprehensive Code Structure Analysis\n\n")
                f.write(report)
        except Exception as e:
            error_msg = f"Report generation failed:\n\nPrompt:\n{''.join(prompt_parts)[:]}...\n\nError: {str(e)}"
            self.record_error("technical_architecture.md", "ReportError", error_msg)
            with open(root_dir / "technical_architecture.md", 'w', encoding='utf-8') as f:
                f.write("# Report Generation Failed\n\n" + error_msg)