from webdav4.client import Client
import io
import os
import logging

logger = logging.getLogger(__name__)

class NextcloudClient:
    def __init__(self, base_url: str, auth: tuple):
        self.client = Client(base_url, auth=auth)

    def download_file(self, path: str) -> io.BytesIO:
        """
        Downloads a file from Nextcloud and returns it as a BytesIO object.
        """
        try:
            target = io.BytesIO()
            self.client.download_fileobj(path, target)
            target.seek(0)
            return target
        except Exception as e:
            logger.error(f"Failed to download file {path}: {e}")
            raise
    
    def exists(self, path: str) -> bool:
        return self.client.exists(path)
