import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import location_lab as lab

POINT = (48.8582599, 2.2945006)


class FakeClock:
    def __init__(self): self.value = 0
    def now(self): return self.value
    def sleep(self, value): self.value += value


class FakeHdc:
    def __init__(self, failure=None): self.calls, self.failure = [], failure
    def run(self, *args):
        self.calls.append(args)
        if 'set-mocked-locations' in args:
            if self.failure: raise self.failure
            return 'Set mocked locations successfully.'
        return 'ok'


class LocationTests(unittest.TestCase):
    def test_invalid_input_never_touches_device(self):
        for point in [(math.nan, 1), (91, 1), (1, math.inf), (1, 181)]:
            hdc = FakeHdc()
            with self.assertRaises(lab.LabError):lab.run_session(hdc, [point])
            self.assertEqual(hdc.calls, [])

    def test_gpx_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder)/'route.gpx'
            file.write_bytes(lab.gpx_bytes([POINT, (48.859, 2.295)], 2))
            self.assertEqual(lab.load_gpx(file), [POINT, (48.859, 2.295)])

    def test_malformed_gpx_is_reported_without_key_error(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'broken.gpx'
            file.write_text('<gpx><wpt lat="1"/></gpx>')
            with self.assertRaises(lab.LabError):lab.load_gpx(file)

    def test_hold_replenishes_before_batch_exhaustion_and_cleans_up(self):
        hdc, clock = FakeHdc(), FakeClock()
        batches = lab.run_session(hdc, [POINT], duration=45, loop=True,
                                  clock=clock.now, sleeper=clock.sleep, report=lambda s:None)
        self.assertEqual(batches, 3)
        self.assertEqual(clock.value, 45)
        self.assertEqual(hdc.calls[-2][2], 'disable-location-mock')
        self.assertEqual(hdc.calls[-1][1], 'rm')

    def test_finite_track_ends_without_replaying_forever(self):
        hdc, clock = FakeHdc(), FakeClock()
        lab.run_session(hdc, [POINT, (48.859, 2.295)], duration=60,
                        clock=clock.now, sleeper=clock.sleep, report=lambda s:None)
        self.assertEqual(clock.value, 2)

    def test_submit_failure_and_interrupt_both_attempt_disable(self):
        for error in [lab.LabError('submission failed'), KeyboardInterrupt()]:
            hdc = FakeHdc(error)
            with self.assertRaises(type(error)):
                lab.run_session(hdc, [POINT], loop=True, report=lambda s:None)
            self.assertEqual(hdc.calls[-2][2], 'disable-location-mock')

    def test_cleanup_failure_is_not_reported_as_success(self):
        class Broken(FakeHdc):
            def run(self,*args):
                if 'disable-location-mock' in args and self.calls:raise lab.LabError('offline')
                return super().run(*args)
        hdc, clock = Broken(), FakeClock()
        with self.assertRaises(lab.LabError):
            lab.run_session(hdc,[POINT],duration=1,clock=clock.now,sleeper=clock.sleep,report=lambda s:None)

    def test_device_status_and_multiple_devices(self):
        output='DEMO-DEVICE USB Connected localhost hdc\nOTHER-DEVICE USB Unauthorized localhost hdc'
        self.assertEqual([d['status'] for d in lab.parse_devices(output)],['Connected','Unauthorized'])
        with patch.object(lab.shutil,'which',return_value='hdc'):
            hdc=lab.Hdc()
            with patch.object(hdc,'run',return_value=output):
                with self.assertRaisesRegex(lab.LabError,'多个设备'):hdc.select()
            hdc.device='OTHER-DEVICE'
            with patch.object(hdc,'run',return_value=output):
                with self.assertRaisesRegex(lab.LabError,'尚未授权'):hdc.select()

    def test_listing_can_report_unauthorized_devices(self):
        from subprocess import CompletedProcess
        output='DEMO-DEVICE USB Unauthorized localhost hdc'
        with patch.object(lab.shutil,'which',return_value='hdc'), patch.object(lab.subprocess,'run',return_value=CompletedProcess([],0,output,'')):
            hdc=lab.Hdc()
            self.assertEqual(hdc.run('list','targets','-v'),output)
            with self.assertRaises(lab.LabError):hdc.run('shell','testhelper','enable-location-mock')

    def test_dry_run_does_not_construct_hdc(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(lab,'Hdc',side_effect=AssertionError('Must stay offline')):
            output=Path(folder)/'example.gpx'
            self.assertEqual(lab.main(['hold','--lat','48.8582599','--lon','2.2945006','--dry-run',str(output)]),0)
            self.assertTrue(output.exists())


if __name__ == '__main__':unittest.main()
