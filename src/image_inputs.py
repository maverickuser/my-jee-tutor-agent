import base64
from pathlib import Path

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
    def resolve(
        self,
        *,
        image_data_uri: str | None = None,
        image_data_uris: list[str] | None = None,
        image_folder: str | None = None,
        media: ImageMediaPayload | None = None,
    ) -> list[str]:
        resolved_images = list(image_data_uris or [])
        if image_data_uri:
            resolved_images.append(image_data_uri)
        if media_data_uri := self._media_data_uri(media):
            resolved_images.append(media_data_uri)
        if image_folder:
            resolved_images.extend(self._folder_data_uris(image_folder))
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
