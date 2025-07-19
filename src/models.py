from dataclasses import dataclass

@dataclass
class ProcessingError:
    file_path: str
    error_type: str
    error_msg: str