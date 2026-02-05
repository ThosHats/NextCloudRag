import os
import logging
from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)

class QdrantUpdater:
    def __init__(self):
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")
        
        self.client = QdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key
        )
        self.collection_name = "documents"

    def update_acl(self, file_id: str, acl_data: dict):
        """
        Updates the ACL payload for all chunks associated with a file_id.
        acl_data should contain keys like 'owner', 'allowed_users', 'allowed_groups'.
        """
        try:
            # We filter points by file_id
            filter_condition = models.Filter(
                must=[
                    models.FieldCondition(
                        key="file_id",
                        match=models.MatchValue(value=str(file_id))
                    )
                ]
            )

            # Set Payload
            self.client.set_payload(
                collection_name=self.collection_name,
                payload=acl_data,
                points=filter_condition,
                wait=True
            )
            logger.info(f"Updated ACL for file {file_id}: {acl_data}")
        except Exception as e:
            logger.error(f"Failed to update ACL for {file_id}: {e}")
            raise
