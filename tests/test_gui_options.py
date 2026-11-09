from pathlib import Path
import tempfile
import unittest
from gui import session_options
from location_lab import LabError, gpx_bytes


class GuiOptionsTests(unittest.TestCase):
    def test_bad_form_never_becomes_device_action(self):
        for lat, lon, duration, interval in [('abc', '2', '60', '1'), ('nan', '2', '60', '1'),
                                             ('48', '181', '60', '1'), ('48', '2', '3601', '1'),
                                             ('48', '2', '60', '0'), ('48', '2', '1.5', '1')]:
            with self.assertRaises(LabError):
                session_options('hold', lat, lon, '', duration, interval, False)

    def test_route_and_fixed_modes_keep_different_end_behavior(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'route.gpx'
            file.write_bytes(gpx_bytes([(48, 2), (49, 3)], 1))
            fixed = session_options('hold', '48', '2', '', '60', '1', False)
            route = session_options('play', '', '', str(file), '60', '2', False)
            self.assertTrue(fixed['loop'])
            self.assertFalse(route['loop'])
            self.assertEqual(route['points'], [(48, 2), (49, 3)])
            self.assertEqual(route['interval'], 2)
        with self.assertRaisesRegex(LabError, '选择 GPX'):
            session_options('play', '', '', '', '60', '1', False)
