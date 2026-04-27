from typing import List

def recall_at_k(preds: List[str], truth: List[str], k: int) -> float:
    """
    Calculate Recall@K.
    Recall = (# relevant in top k) / (total relevant)
    
    Args:
        preds: List of predicted signatures.
        truth: List of relevant (ground truth) signatures.
        k: The rank threshold.
    """
    if not truth:
        return 0.0
    
    top_k_preds = preds[:k]
    relevant_retrieved = [p for p in top_k_preds if p in truth]
    return len(relevant_retrieved) / len(truth)

def hit_at_k(preds: List[str], truth: List[str], k: int) -> int:
    """
    Calculate Hit@K.
    Hit@K = 1 if any relevant result is in top k else 0
    """
    top_k_preds = preds[:k]
    for p in top_k_preds:
        if p in truth:
            return 1
    return 0

def reciprocal_rank(preds: List[str], truth: List[str]) -> float:
    """
    Calculate Reciprocal Rank (RR) for a single query.
    RR = 1 / rank_of_first_relevant (1-based)
    """
    for i, p in enumerate(preds):
        if p in truth:
            return 1.0 / (i + 1)
    return 0.0

def mean_reciprocal_rank(all_preds: List[List[str]], all_truths: List[List[str]]) -> float:
    """
    Calculate Mean Reciprocal Rank (MRR) across all queries.
    """
    if not all_preds:
        return 0.0
    
    rr_sum = 0.0
    for preds, truth in zip(all_preds, all_truths):
        rr_sum += reciprocal_rank(preds, truth)
    
    return rr_sum / len(all_preds)
