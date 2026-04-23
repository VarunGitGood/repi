from typing import List, Dict

def rrf(rankings: List[List[int]], k: int = 60) -> List[int]:
    """
    Reciprocal Rank Fusion (RRF) to combine multiple rankings.
    
    Args:
        rankings: List of ranked lists of document indices.
        k: Smoothing constant (default 60).
        
    Returns:
        A single fused ranking of document indices.
    """
    scores: Dict[int, float] = {}
    
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            # rank starts at 0, so rank + 1 would be the 1-based rank
            # The formula is 1 / (k + rank_1_based)
            # which is equivalent to 1 / (k + rank_0_based + 1)
            # However, the prompt says scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)
            # I will follow the prompt'S EXACT formula.
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)
            
    # Sort doc_ids by score in descending order
    return sorted(scores.keys(), key=lambda doc_id: scores[doc_id], reverse=True)
