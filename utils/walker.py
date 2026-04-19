import os
import pathspec

def walk_repo(repo_path: str):
    """
    Yields (relative_path, source_code) for supported files in repo.
    """
    ignore_patterns = [
        'node_modules/', 'dist/', 'build/', '.next/', 
        '*.d.ts', '*.min.js'
    ]
    
    gitignore_path = os.path.join(repo_path, '.gitignore')
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                ignore_patterns.extend(f.readlines())
        except Exception:
            pass
            
    spec = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, ignore_patterns)
    
    supported_extensions = {'.py', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs'}
    valid_size_limit = 500 * 1024  # 500 KB
    
    for root, dirs, files in os.walk(repo_path):
        rel_root = os.path.relpath(root, repo_path)
        if rel_root == '.':
            rel_root = ''
            
        dirs[:] = [d for d in dirs if not spec.match_file(os.path.join(rel_root, d))]
        
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext not in supported_extensions:
                continue
                
            rel_file = os.path.join(rel_root, file) if rel_root else file
            rel_file_norm = rel_file.replace(os.sep, '/')
            
            if spec.match_file(rel_file_norm):
                continue
                
            abs_path = os.path.join(root, file)
            
            try:
                if os.path.getsize(abs_path) > valid_size_limit:
                    continue
                with open(abs_path, 'r', encoding='utf-8') as f:
                    source = f.read()
                yield rel_file_norm, source
            except Exception:
                pass
