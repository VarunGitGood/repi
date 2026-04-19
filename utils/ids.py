import hashlib

def generate_id(file_path: str, node_type: str, name: str, start_line: int) -> str:
    """
    Generate a deterministic 12-char ID for a code entity.
    """
    raw = f"{file_path}:{node_type}:{name}:{start_line}"
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]
