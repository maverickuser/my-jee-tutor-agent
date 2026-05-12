import base64
from pathlib import Path
from urllib.parse import urlparse

import boto3

from pydantic import BaseModel


SUPPORTED_IMAGE_FORMATS = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}


class ImageMediaPayload(BaseModel):
    type: str
    format: str
    data: str

    def to_data_uri(self) -> str | None:
        if self.type != "image":
            return None
        return f"data:image/{self.format};base64,{self.data}"


class ImageInputResolver:
    def __init__(self, s3_client=None):
        self.s3_client = s3_client

    def resolve(
        self,
        *,
        image_data_uri: str | None = None,
        image_data_uris: list[str] | None = None,
        image_folder: str | None = None,
        image_s3_uri: str | None = None,
        image_s3_prefix: str | None = None,
        media: ImageMediaPayload | None = None,
    ) -> list[str]:
        resolved_images = list(image_data_uris or [])
        if image_data_uri:
            resolved_images.append(image_data_uri)
        if media_data_uri := self._media_data_uri(media):
            resolved_images.append(media_data_uri)
        if image_folder:
            resolved_images.extend(self._folder_data_uris(image_folder))
        if image_s3_uri:
            resolved_images.append(self._s3_object_data_uri(image_s3_uri))
        if image_s3_prefix:
            resolved_images.extend(self._s3_prefix_data_uris(image_s3_prefix))
        return resolved_images

    @staticmethod
    def _media_data_uri(media: ImageMediaPayload | None) -> str | None:
        if not media:
            return None
        return media.to_data_uri()

    @staticmethod
    def _folder_data_uris(image_folder: str) -> list[str]:
        folder = Path(image_folder).expanduser()
        if not folder.is_dir():
            raise ValueError(f"Image folder does not exist or is not a directory: {image_folder}")

        image_paths = sorted(
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_FORMATS
        )
        if not image_paths:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
            raise ValueError(
                f"Image folder contains no supported images ({supported}): {image_folder}"
            )

        return [
            ImageInputResolver._image_file_data_uri(
                path,
                SUPPORTED_IMAGE_FORMATS[path.suffix.lower()],
            )
            for path in image_paths
        ]

    @staticmethod
    def _image_file_data_uri(path: Path, image_format: str) -> str:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/{image_format};base64,{encoded}"

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

        return [self._s3_object_data_uri(f"s3://{bucket}/{key}") for key in sorted(keys)]

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
