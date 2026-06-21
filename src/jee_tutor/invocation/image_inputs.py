import base64
import logging
from pathlib import Path
from urllib.parse import urlparse

import boto3


SUPPORTED_IMAGE_FORMATS = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}
logger = logging.getLogger(__name__)


class ImageInputResolver:
    def __init__(self, s3_client=None):
        self.s3_client = s3_client

    def resolve(
        self,
        *,
        image_data_uri: str | None = None,
        image_s3_prefix: str | None = None,
    ) -> list[str]:
        sources = [source for source in [image_s3_prefix, image_data_uri] if source]
        if len(sources) != 1:
            raise ValueError("Send exactly one image input: image_s3_prefix or image_data_uri.")
        if image_data_uri:
            return [image_data_uri]
        return self._s3_prefix_data_uris(str(image_s3_prefix))

    def _s3_prefix_data_uris(self, image_s3_prefix: str) -> list[str]:
        bucket, prefix = self._parse_s3_uri(image_s3_prefix)
        keys = [
            key
            for key in self._list_s3_keys(bucket, prefix)
            if Path(key).suffix.lower() in SUPPORTED_IMAGE_FORMATS
        ]
        if not keys:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
            raise ValueError(
                f"S3 prefix contains no supported images ({supported}): {image_s3_prefix}"
            )

        sorted_keys = sorted(keys)
        logger.info(
            "resolved_s3_image_prefix bucket=%s prefix=%s image_count=%s keys=%s",
            bucket,
            prefix,
            len(sorted_keys),
            sorted_keys,
        )
        return [self._s3_object_data_uri(f"s3://{bucket}/{key}") for key in sorted_keys]

    def _s3_object_data_uri(self, image_s3_uri: str) -> str:
        bucket, key = self._parse_s3_uri(image_s3_uri)
        suffix = Path(key).suffix.lower()
        if suffix not in SUPPORTED_IMAGE_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
            raise ValueError(f"Unsupported S3 image format ({supported}): {image_s3_uri}")

        response = self._s3().get_object(Bucket=bucket, Key=key)
        encoded = base64.b64encode(response["Body"].read()).decode("ascii")
        image_format = SUPPORTED_IMAGE_FORMATS[suffix]
        return f"data:image/{image_format};base64,{encoded}"

    def _list_s3_keys(self, bucket: str, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._s3().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            keys.extend(
                obj["Key"] for obj in page.get("Contents", []) if not obj["Key"].endswith("/")
            )
        return keys

    def _s3(self):
        if self.s3_client is None:
            self.s3_client = boto3.client("s3")
        return self.s3_client

    @staticmethod
    def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
        parsed = urlparse(s3_uri)
        if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.strip("/"):
            raise ValueError(f"Invalid S3 URI: {s3_uri}")
        return parsed.netloc, parsed.path.lstrip("/")
