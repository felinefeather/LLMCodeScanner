import re
import logging

def preprocess_code(code: str) -> str:
    """Clean code while preserving structure"""
    try:
        lines = []
        for line in code.split('\n'):
            stripped = line.strip()
            if stripped.startswith('//'):
                continue
            if '//' in line:
                line = line.split('//')[0]
            if line.strip():
                lines.append(line)
        
        cleaned = '\n'.join(lines)
        return re.sub(r'\n{3,}', '\n\n', cleaned)
    except Exception as e:
        logging.warning(f"Preprocessing error: {str(e)}")
        return code
    
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='game_code_processor.log'
)
logger = logging.getLogger(__name__)
start_from = 0
