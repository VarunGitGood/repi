from typing import List
from rank_bm25 import BM25Okapi

class BM25Retriever:
    """
    BM25 retriever for sparse text matching.
    """
    def __init__(self, documents: List[str]):
        """
        Initialize the BM25 index.
        
        Args:
            documents: List of document strings (stringified log clusters).
        """
        self.documents = documents
        self.tokenized_corpus = [doc.lower().split() for doc in documents]
        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def search(self, query: str, top_k: int = 5) -> List[int]:
        """
        Search the index for the given query.
        
        Args:
            query: The search query string.
            top_k: Number of results to return.
            
        Returns:
            List of document indices.
        """
        if not self.documents:
            return []
            
        tokenized_query = query.lower().split()
        # get_top_n returns the actual documents, but we want indices
        scores = self.bm25.get_scores(tokenized_query)
        # Sort indices by score descending
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return top_indices
