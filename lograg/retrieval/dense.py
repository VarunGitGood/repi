import numpy as np
import faiss
from typing import List
from sentence_transformers import SentenceTransformer

class DenseRetriever:
    """
    Dense retriever for vector-based semantic search.
    """
    def __init__(self, documents: List[str], model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize the dense index.
        
        Args:
            documents: List of document strings.
            model_name: Sentence-transformers model name.
        """
        self.documents = documents
        self.model = SentenceTransformer(model_name)
        
        if not documents:
            self.index = None
            return

        # Generate embeddings
        embeddings = self.model.encode(documents, convert_to_numpy=True)
        
        # Normalize embeddings for cosine similarity
        faiss.normalize_L2(embeddings)
        
        # Initialize FAISS index (Inner Product on normalized vectors is Cosine Similarity)
        dimension = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)
        self.index.add(embeddings.astype('float32'))

    def search(self, query: str, top_k: int = 5) -> List[int]:
        """
        Search the index for the given query.
        
        Args:
            query: The search query string.
            top_k: Number of results to return.
            
        Returns:
            List of document indices.
        """
        if not self.documents or self.index is None:
            return []
            
        # Encode and normalize query
        query_embedding = self.model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)
        
        # Search index
        scores, indices = self.index.search(query_embedding.astype('float32'), top_k)
        
        # FAISS returns -1 if not enough results
        return [int(idx) for idx in indices[0] if idx != -1]
