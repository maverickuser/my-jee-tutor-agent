import base64
import unittest

from jee_tutor.invocation.image_inputs import ImageInputResolver


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
    def test_image_data_uri_is_returned_as_single_image(self):
        image_data_uri = "data:image/png;base64,ZmFrZQ=="

        image_data_uris = ImageInputResolver().resolve(image_data_uri=image_data_uri)

        self.assertEqual(image_data_uris, [image_data_uri])

    def test_s3_prefix_loads_supported_images_in_key_order(self):
        client = FakeS3Client(
            {
                ("attempt-bucket", "attempts/Question_6.png"): b"first",
                ("attempt-bucket", "attempts/Question_19.jpg"): b"second",
            },
            pages=[
                {
                    "Contents": [
                        {"Key": "attempts/Question_19.jpg"},
                        {"Key": "attempts/notes.txt"},
                        {"Key": "attempts/Question_6.png"},
                        {"Key": "attempts/profile-smoke/run-1/Question_6.png"},
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
        self.assertEqual(
            client.get_object_calls,
            [
                {"Bucket": "attempt-bucket", "Key": "attempts/Question_6.png"},
                {"Bucket": "attempt-bucket", "Key": "attempts/Question_19.jpg"},
            ],
        )

    def test_s3_prefix_resolves_image_metadata(self):
        client = FakeS3Client(
            {
                ("attempt-bucket", "attempts/Question_006.png"): b"first",
                ("attempt-bucket", "attempts/Question_19.jpg"): b"second",
            },
            pages=[
                {
                    "Contents": [
                        {"Key": "attempts/Question_19.jpg"},
                        {"Key": "attempts/Question_006.png"},
                    ]
                }
            ],
        )

        images = ImageInputResolver(s3_client=client).resolve_images(
            image_s3_prefix="s3://attempt-bucket/attempts/"
        )

        self.assertEqual([image.file_name for image in images], ["Question_006.png", "Question_19.jpg"])
        self.assertEqual([image.question_number for image in images], ["6", "19"])
        self.assertEqual(
            [image.source_uri for image in images],
            [
                "s3://attempt-bucket/attempts/Question_006.png",
                "s3://attempt-bucket/attempts/Question_19.jpg",
            ],
        )

    def test_invalid_s3_uri_is_rejected(self):
        resolver = ImageInputResolver(s3_client=FakeS3Client({}))

        with self.assertRaisesRegex(ValueError, "Invalid S3 URI"):
            resolver.resolve(image_s3_prefix="https://example.com/attempts/")

    def test_exactly_one_image_source_is_required(self):
        resolver = ImageInputResolver(s3_client=FakeS3Client({}))

        with self.assertRaisesRegex(ValueError, "exactly one image input"):
            resolver.resolve()

        with self.assertRaisesRegex(ValueError, "exactly one image input"):
            resolver.resolve(
                image_data_uri="data:image/png;base64,ZmFrZQ==",
                image_s3_prefix="s3://attempt-bucket/attempts/",
            )

    def test_s3_prefix_does_not_fetch_unsupported_objects(self):
        client = FakeS3Client(
            {("attempt-bucket", "attempts/page-1.png"): b"prefix-image"},
            pages=[{"Contents": [{"Key": "attempts/page-1.png"}, {"Key": "attempts/notes.txt"}]}],
        )

        ImageInputResolver(s3_client=client).resolve(
            image_s3_prefix="s3://attempt-bucket/attempts/",
        )

        self.assertEqual(
            client.get_object_calls,
            [{"Bucket": "attempt-bucket", "Key": "attempts/page-1.png"}],
        )

    def test_s3_prefix_ignores_nested_image_objects(self):
        client = FakeS3Client(
            {
                ("eval-bucket", "cd-evals-images/Physics_Q13.png"): b"physics",
                ("eval-bucket", "cd-evals-images/Chemistry_Q34.png"): b"chemistry",
                ("eval-bucket", "cd-evals-images/Maths_Q36.png"): b"maths",
            },
            pages=[
                {
                    "Contents": [
                        {"Key": "cd-evals-images/Physics_Q13.png"},
                        {
                            "Key": (
                                "cd-evals-images/profile-smoke/run-1/users/student/"
                                "Mock/tests/CD/subjects/Physics/questions/Physics_Q13.png"
                            )
                        },
                        {"Key": "cd-evals-images/Chemistry_Q34.png"},
                        {
                            "Key": (
                                "cd-evals-images/profile-smoke/run-1/users/student/"
                                "Mock/tests/CD/subjects/Physics/questions/Chemistry_Q34.png"
                            )
                        },
                        {"Key": "cd-evals-images/Maths_Q36.png"},
                    ]
                }
            ],
        )

        images = ImageInputResolver(s3_client=client).resolve_images(
            image_s3_prefix="s3://eval-bucket/cd-evals-images/"
        )

        self.assertEqual(
            [image.object_key for image in images],
            [
                "cd-evals-images/Physics_Q13.png",
                "cd-evals-images/Chemistry_Q34.png",
                "cd-evals-images/Maths_Q36.png",
            ],
        )

    def test_s3_prefix_without_supported_images_is_rejected(self):
        client = FakeS3Client({}, pages=[{"Contents": [{"Key": "attempts/notes.txt"}]}])

        with self.assertRaisesRegex(ValueError, "contains no supported images"):
            ImageInputResolver(s3_client=client).resolve(
                image_s3_prefix="s3://attempt-bucket/attempts/"
            )

    def test_lazy_s3_client_is_created_once(self):
        fake_client = FakeS3Client(
            {("bucket", "images/image.png"): b"image"},
            pages=[{"Contents": [{"Key": "images/image.png"}]}],
        )

        with unittest.mock.patch(
            "jee_tutor.invocation.image_inputs.boto3.client", return_value=fake_client
        ) as client:
            resolver = ImageInputResolver()
            resolver.resolve(image_s3_prefix="s3://bucket/images/")
            resolver.resolve(image_s3_prefix="s3://bucket/images/")

        client.assert_called_once_with("s3")


if __name__ == "__main__":
    unittest.main()
