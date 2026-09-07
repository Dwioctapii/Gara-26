import importlib.util
import unittest


WEBSOCKETS_TERSEDIA = importlib.util.find_spec("websockets") is not None


@unittest.skipUnless(WEBSOCKETS_TERSEDIA, "websockets belum terpasang")
class SerialPacketTest(unittest.TestCase):
    def test_paket_enam_byte_dan_checksum(self):
        from mod06_serial_worker import buat_paket

        paket = buat_paket(1500, 1, 3)

        self.assertEqual(len(paket), 6)
        self.assertEqual(paket[0], 0xAA)
        self.assertEqual(paket[-1], paket[1] ^ paket[2] ^ paket[3] ^ paket[4])


if __name__ == "__main__":
    unittest.main()
