import os
from haystack import Pipeline
from haystack.components.embedders import SentenceTransformersTextEmbedder
from haystack.components.retrievers.in_memory import InMemoryEmbeddingRetriever
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack.components.builders import PromptBuilder
from haystack.components.generators import OpenAIGenerator
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack.utils import Secret

class RagPipeline:
    def __init__(self):
        # Qdrant Setup
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        
        self.document_store = QdrantDocumentStore(
            url=qdrant_url,
            api_key=Secret.from_token(qdrant_api_key) if qdrant_api_key else None,
            index="documents",
            embedding_dim=768 # Match Indexer's embedding dim
        )

        # Template
        template = """
        Answer the question based strictly on the following context. If the answer is not in the context, say "I don't have enough information from the documents."
        
        Context:
        {% for document in documents %}
            {{ document.content }}
        {% endfor %}
        
        Question: {{ question }}
        Answer:
        """

        # LLM Setup (Defaulting to OpenAI for V1, can be swapped for Ollama)
        openai_key = os.getenv("OPENAI_API_KEY")
        
        # Pipeline Definition
        self.pipeline = Pipeline()
        self.pipeline.add_component("text_embedder", SentenceTransformersTextEmbedder(model="sentence-transformers/all-mpnet-base-v2"))
        self.pipeline.add_component("retriever", QdrantEmbeddingRetriever(document_store=self.document_store))
        self.pipeline.add_component("prompt_builder", PromptBuilder(template=template))
        
        # Determine Generator
        if openai_key:
            self.pipeline.add_component("generator", OpenAIGenerator(api_key=Secret.from_token(openai_key), model="gpt-4-turbo-preview"))
        else:
            # Fallback or Ollama logic (simplified for now)
            raise ValueError("OPENAI_API_KEY is required for this version.")

        self.pipeline.connect("text_embedder.embedding", "retriever.query_embedding")
        self.pipeline.connect("retriever", "prompt_builder.documents")
        self.pipeline.connect("prompt_builder", "generator")

    def run(self, query: str, top_k: int = 5, filters: dict = None):
        """
        Runs the RAG pipeline.
        filters: Qdrant filters for ACLs (future use).
        """
        result = self.pipeline.run(
            {
                "text_embedder": {"text": query},
                "retriever": {"top_k": top_k, "filters": filters},
                "prompt_builder": {"question": query}
            }
        )
        
        answer = result["generator"]["replies"][0]
        # Extract sources from retriever result (needs a slightly different access pattern usually, 
        # but Haystack 2.x passes documents through. We might need to inspect 'retriever' output if we want citations separately)
        # For simplicity, we just return the answer here. To get sources, we'd inspect the flow or modify the return.
        
        # Valid retrieval of sources requires accessing the 'documents' used in prompt_builder
        # BUT pipeline.run returns the output of the leaf node. 
        # To get sources, we can include the retriever output in the final result? 
        # Actually, standard way is to trust the answer or run a debug/include_outputs.
        
        return {
            "answer": answer,
            # Ideally we want to return sources here. 
            # In Haystack 2, we can request component outputs.
        }
