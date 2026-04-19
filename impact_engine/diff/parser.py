import os
from git import Repo
from unidiff import PatchSet
from .types import DiffHunk

def parse_diff(repo_path: str, ref: str = "HEAD") -> list[DiffHunk]:
    """
    Parse git diff between HEAD and ref into structured DiffHunks.
    Handles 'ref' as a single ref (compare against HEAD) or a range (A..B).
    """
    repo = Repo(repo_path)
    
    # If ref contains '..', it's a range. Otherwise compare HEAD vs ref.
    # Note: git.diff with a single ref compares the working tree against that ref.
    if ".." in ref:
        base, target = ref.split("..")
        diff_text = repo.git.diff(base, target, unified=0)
    else:
        diff_text = repo.git.diff(ref, unified=0)
        
    patch = PatchSet(diff_text)
    hunks = []
    
    for patched_file in patch:
        # Normalise path: strip leading a/ or b/ (unidiff usually handles this)
        # Use relative path from repo root
        file_path = patched_file.path
        
        # Determine change type
        change_type = "modified"
        if patched_file.is_added_file:
            change_type = "added"
        elif patched_file.is_removed_file:
            change_type = "deleted"
            
        for hunk in patched_file:
            # We care about the target (new) side of the diff
            # hunk.target_start is 1-indexed
            hunks.append(DiffHunk(
                file=file_path,
                start_line=hunk.target_start,
                end_line=hunk.target_start + hunk.target_length - 1 if hunk.target_length > 0 else hunk.target_start,
                change_type=change_type
            ))
            
    return hunks
