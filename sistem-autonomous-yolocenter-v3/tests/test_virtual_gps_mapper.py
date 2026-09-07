import unittest

from mod101_virtual_gps_mapper import VirtualGPSMapper


class VirtualGPSMapperTest(unittest.TestCase):
    def test_heading_90_maju_ke_timur(self):
        mapper = VirtualGPSMapper((0, 0), (-6.2, 106.8), 90)

        lintang, bujur = mapper.virtual_to_gps(0, 1)

        self.assertAlmostEqual(lintang, -6.2, places=6)
        self.assertGreater(bujur, 106.8)

    def test_round_trip(self):
        mapper = VirtualGPSMapper((0, 0), (-6.2, 106.8), 37)

        hasil = mapper.gps_to_virtual(*mapper.virtual_to_gps(3, 4))

        self.assertAlmostEqual(hasil[0], 3, places=6)
        self.assertAlmostEqual(hasil[1], 4, places=6)


if __name__ == "__main__":
    unittest.main()
