from typing import List
from sentence_transformers import CrossEncoder

class CrossEncoderReranker:
    """
    Reranker using a Cross-Encoder model for higher precision ranking.
    """
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Load the cross-encoder model.
        
        Args:
            model_name: The name of the cross-encoder model to use.
        """
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, documents: List[str], top_k: int) -> List[int]:
        """
        Rerank a set of documents based on a query.
        
        Args:
            query: The user query string.
            documents: List of document strings to rerank.
            top_k: Number of top results to return.
            
        Returns:
            List of indices of the top_k reranked documents.
        """
        if not documents:
            return []

        # Build pairs of (query, document)
        pairs = [(query, doc) for doc in documents]
        
        # Predict relevance scores
        # scores will be a numpy array of shape (len(documents),)
        scores = self.model.predict(pairs)
        
        # Sort indices by score in descending order
        # We want to return indices relative to the input documents list
        import numpy as np
        ranked_indices = np.argsort(scores)[::-1]
        
        return ranked_indices[:top_k].tolist()
