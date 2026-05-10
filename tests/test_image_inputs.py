import base64
import unittest

from image_inputs import ImageInputResolver


class FakeBody:
    def __init__(self, data: bytes):
        self.data = data

    def read(self) -> bytes:
        return self.data


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages


class FakeS3Client:
    def __init__(self, objects: dict[tuple[str, str], bytes], pages=None):
        self.objects = objects
        self.paginator = FakePaginator(pages or [])
        self.get_object_calls = []

    def get_object(self, **kwargs):
        self.get_object_calls.append(kwargs)
        return {"Body": FakeBody(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

    def get_paginator(self, name: str):
        if name != "list_objects_v2":
            raise AssertionError(f"Unexpected paginator: {name}")
        return self.paginator


class ImageInputResolverTest(unittest.TestCase):
    def test_s3_uri_loads_single_image_as_data_uri(self):
        client = FakeS3Client({("attempt-bucket", "student/attempt.png"): b"png-bytes"})
        resolver = ImageInputResolver(s3_client=client)

        image_data_uris = resolver.resolve(image_s3_uri="s3://attempt-bucket/student/attempt.png")

        self.assertEqual(
            image_data_uris,
            ["data:image/png;base64," + base64.b64encode(b"png-bytes").decode("ascii")],
        )
        self.assertEqual(
            client.get_object_calls,
            [{"Bucket": "attempt-bucket", "Key": "student/attempt.png"}],
        )

    def test_s3_prefix_loads_supported_images_in_key_order(self):
        client = FakeS3Client(
            {
                ("attempt-bucket", "attempts/01.png"): b"first",
                ("attempt-bucket", "attempts/02.jpg"): b"second",
            },
            pages=[
                {
                    "Contents": [
                        {"Key": "attempts/02.jpg"},
                        {"Key": "attempts/notes.txt"},
                        {"Key": "attempts/01.png"},
                        {"Key": "attempts/subfolder/"},
                    ]
                }
            ],
        )
        resolver = ImageInputResolver(s3_client=client)

        image_data_uris = resolver.resolve(image_s3_prefix="s3://attempt-bucket/attempts/")

        self.assertEqual(
            image_data_uris,
            [
                "data:image/png;base64," + base64.b64encode(b"first").decode("ascii"),
                "data:image/jpeg;base64," + base64.b64encode(b"second").decode("ascii"),
            ],
        )
        self.assertEqual(
            client.paginator.calls,
            [{"Bucket": "attempt-bucket", "Prefix": "attempts/"}],
        )

    def test_invalid_s3_uri_is_rejected(self):
        resolver = ImageInputResolver(s3_client=FakeS3Client({}))

        with self.assertRaisesRegex(ValueError, "Invalid S3 URI"):
            resolver.resolve(image_s3_uri="https://example.com/attempt.png")

    def test_s3_uri_with_unsupported_extension_is_rejected_before_fetch(self):
        client = FakeS3Client({})
        resolver = ImageInputResolver(s3_client=client)

        with self.assertRaisesRegex(ValueError, "Unsupported S3 image format"):
            resolver.resolve(image_s3_uri="s3://attempt-bucket/student/notes.txt")

        self.assertEqual(client.get_object_calls, [])


if __name__ == "__main__":
    unittest.main()
