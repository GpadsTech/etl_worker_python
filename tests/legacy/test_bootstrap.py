import unittest

from legacy.bootstrap import BootstrapReader


class TestBootstrap(unittest.TestCase):

    def test_read(self):

        bootstrap = BootstrapReader()

        sensors = bootstrap.load_sensors()

        buoys = bootstrap.load_buoys()

        self.assertIsInstance(sensors, dict)

        self.assertIsInstance(buoys, dict)


if __name__ == "__main__":
    unittest.main()
