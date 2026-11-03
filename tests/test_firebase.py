import unittest

from app.firebase.client import FirebaseClient


class TestFirebase(unittest.TestCase):

    def test_connect(self):

        client = FirebaseClient()

        app = client.connect()

        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()