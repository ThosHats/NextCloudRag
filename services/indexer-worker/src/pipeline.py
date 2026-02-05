import os
from haystack import Pipeline
from haystack.components.converters import TextFileToDocument, PyPDFToDocument
from haystack.components.preprocessors import DocumentSplitter, DocumentCleaner
from haystack.components.embedders import SentenceTransformersDocumentEmbedder
from haystack.components.writers import DocumentWriter
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack.utils import Secret

# Note: For production, we need a custom Component that takes a stream from WebDAV
# For this simplified version, we assume the worker writes the stream to a temp file first.

class IndexingPipeline:
    def __init__(self):
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        
        self.document_store = QdrantDocumentStore(
            url=qdrant_url,
            api_key=Secret.from_token(qdrant_api_key) if qdrant_api_key else None,
            index="documents",
            embedding_dim=768, # e.g. for all-mpnet-base-v2
            recreate_index=False
        )

        # Basic PDF Pipeline
        self.pdf_pipeline = Pipeline()
        self.pdf_pipeline.add_component("converter", PyPDFToDocument())
        self.pdf_pipeline.add_component("cleaner", DocumentCleaner())
        self.pdf_pipeline.add_component("splitter", DocumentSplitter(split_by="word", split_length=200, split_overlap=20))
        self.pdf_pipeline.add_component("embedder", SentenceTransformersDocumentEmbedder(model="sentence-transformers/all-mpnet-base-v2"))
        self.pdf_pipeline.add_component("writer", DocumentWriter(document_store=self.document_store))

        self.pdf_pipeline.connect("converter", "cleaner")
        self.pdf_pipeline.connect("cleaner", "splitter")
        self.pdf_pipeline.connect("splitter", "embedder")
        self.pdf_pipeline.connect("embedder", "writer")

    def run(self, file_path: str, meta: dict):
        """
        Runs the pipeline on a local file.
        """
        # Extend meta with whatever is needed
        result = self.pdf_pipeline.run(
            {"converter": {"sources": [file_path], "meta": meta}}
        )
        return result
