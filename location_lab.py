"""HarmonyOS location experiments through HDC; Python standard library only."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from app_version import VERSION

NS = 'http://www.topografix.com/GPX/1/1'
ET.register_namespace('', NS)


class LabError(RuntimeError):
    pass


def validate_point(latitude, longitude):
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise LabError('γ�ȱ����� -90 �� 90 ֮�䡣')
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise LabError('���ȱ����� -180 �� 180 ֮�䡣')
    return float(latitude), float(longitude)


def load_gpx(file):
    file = Path(file)
    if file.stat().st_size > 2 * 1024 * 1024:
        raise LabError('GPX �ļ����ܳ��� 2 MB��')
    root = ET.parse(file).getroot()
    try:
        points = [validate_point(float(p.attrib['lat']), float(p.attrib['lon']))
                  for p in root.iter() if p.tag.split('}')[-1] in ('trkpt', 'rtept', 'wpt')]
    except (KeyError, ValueError) as exc:
        raise LabError('GPX �е�λ�õ�ȱ����Ч�ľ�γ�ȡ�') from exc
    if not points or len(points) > 10000:
        raise LabError('GPX ��Ҫ���� 1�C10000 ��λ�õ㡣')
    return points


def gpx_bytes(points, interval, stamp=None):
    stamp = stamp or datetime.now(timezone.utc)
    root = ET.Element(f'{{{NS}}}gpx', version='1.1', creator='HarmonyOSLocationLab')
    segment = ET.SubElement(ET.SubElement(root, f'{{{NS}}}trk'), f'{{{NS}}}trkseg')
    for i, p in enumerate(points):
        lat, lon = validate_point(*p)
        point = ET.SubElement(segment, f'{{{NS}}}trkpt', lat=f'{lat:.9f}', lon=f'{lon:.9f}')
        ET.SubElement(point, f'{{{NS}}}ele').text = '0'
        ET.SubElement(point, f'{{{NS}}}time').text = (stamp + timedelta(seconds=i*interval)).strftime('%Y-%m-%dT%H:%M:%SZ')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def parse_devices(output):
    result = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] in ('USB', 'TCP'):
            result.append({'id': parts[0], 'transport': parts[1], 'status': parts[2]})
    return result


class Hdc:
    def __init__(self, executable='hdc', device=None):
        self.executable = shutil.which(str(executable))
        if not self.executable:
            raise LabError('�Ҳ��� HDC�������� PATH��HDC_PATH �� --hdc��')
        self.device = device

    def run(self, *args):
        command = [self.executable] + (['-t', self.device] if self.device else []) + list(map(str, args))
        try:
            done = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=20, **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        except subprocess.TimeoutExpired as exc:
            raise LabError('HDC ��Ӧ��ʱ���������ӣ��ָ����Ӻ��ִ�� stop��') from exc
        output = (done.stdout + done.stderr).strip()
        listing = args[:2] == ('list', 'targets')
        markers = ('[fail]', 'error:', 'unknown command', 'not supported') + (() if listing else ('unauthorized',))
        if done.returncode or any(s in output.lower() for s in markers):
            raise LabError('HDC δȷ�ϲ����ɹ���' + output[:500])
        return output

    def select(self):
        # Device listing must work even while an explicit target is unauthorized.
        device, self.device = self.device, None
        try:
            devices = parse_devices(self.run('list', 'targets', '-v'))
        finally:
            self.device = device
        selected = [p for p in devices if p['id'] == device] if device else devices
        if not selected:
            raise LabError('û���ҵ�Ŀ���豸���������ֻ������� USB ���ԡ�')
        if len(selected) != 1:
            raise LabError('��⵽����豸������ --device ָ��Ŀ�ꡣ')
        if selected[0]['status'].lower() != 'connected':
            raise LabError('�ֻ���δ��Ȩ��������ֻ���������̨���Ե��ԡ�')
        self.device = selected[0]['id']


def run_session(hdc, points, duration=60, interval=1, loop=False, batch_size=30,
                clock=time.monotonic, sleeper=time.sleep, report=print, cancel=None):
    if not points:
        raise LabError('û��λ�õ㡣')
    points = [validate_point(*p) for p in points]
    if not isinstance(interval, int) or not 1 <= interval <= 60 or not 1 <= duration <= 3600:
        raise LabError('�����ΧΪ 1�C60 �룬ʱ����ΧΪ 1�C3600 �롣')
    if not 2 <= batch_size <= 90:
        raise LabError('ÿ������������ 2�C90 ֮�䡣')
    if cancel is not None and cancel.is_set():
        return 0
    duration = min(duration, len(points)*interval) if not loop else duration
    remote = '/data/local/tmp/harmony-location-' + uuid.uuid4().hex + '.gpx'
    attempted, primary_error = False, None
    batches = 0
    try:
        hdc.run('shell', 'testhelper', 'disable-location-mock')
        if cancel is not None and cancel.is_set():
            return 0
        attempted = True
        hdc.run('shell', 'testhelper', 'enable-location-mock')
        with tempfile.TemporaryDirectory(prefix='harmony-location-') as folder:
            local = Path(folder)/'batch.gpx'
            start = clock()
            while clock()-start < duration and not (cancel is not None and cancel.is_set()):
                elapsed = clock()-start
                cursor = int(elapsed//interval)
                count = batch_size if loop else min(batch_size, len(points)-cursor)
                if count <= 0:
                    break
                batch = [points[(cursor+i) % len(points)] for i in range(count)]
                local.write_bytes(gpx_bytes(batch, interval))
                hdc.run('file', 'send', str(local), remote)
                if cancel is not None and cancel.is_set():
                    break
                answer = hdc.run('shell', 'testhelper', 'set-mocked-locations', remote, str(interval))
                if 'set mocked locations successfully' not in answer.lower():
                    raise LabError('ϵͳû�з���Ԥ�ڵ�λ���ύȷ�ϡ�')
                batches += 1
                report(f'�� {batches} ���ѱ�ϵͳ���ܣ�Ӧ���Ƿ��ȡ��Ҫ���ֻ���ȷ�ϡ�')
                # Resubmit ahead of exhaustion. Slow USB calls can still cause gaps.
                refill = elapsed + max(1, count-min(10, count-1))*interval
                while clock()-start < min(duration, refill) and not (cancel is not None and cancel.is_set()):
                    wait = min(duration, refill)-(clock()-start)
                    if wait <= 0:
                        break
                    sleeper(min(.25, wait))
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        failures = []
        if attempted:
            try:
                hdc.run('shell', 'testhelper', 'disable-location-mock')
                report('ϵͳ�ѽ��ܹر�ģ�����������Ӧ����ȷ��������λ��')
            except Exception:
                failures.append('�ر�ģ��δ��ȷ�ϣ���ָ����Ӻ�ִ�� stop����Ҫʱ���ֻ��Ϲرյ��Բ�������λ��')
        try:
            hdc.run('shell', 'rm', remote)
        except Exception:
            failures.append('��ʱ GPX �ļ�δȷ��ɾ����')
        for failure in failures:
            report(failure)
        if failures and primary_error is None:
            raise LabError('���Խ�������������������')
    return batches


def main(argv=None):
    parser = argparse.ArgumentParser(description='����λ��ģ���� GPX �켣���Թ��ߣ�ʵ��棩')
    parser.add_argument('--version', action='version', version=f'HarmonyOS Location Lab {VERSION}')
    parser.add_argument('--hdc', default=os.getenv('HDC_PATH', 'hdc'))
    parser.add_argument('--device', help='ָ���豸����д����ڼ�⵽һ̨�������豸ʱ�Զ�ѡ��')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('devices', help='�г��豸��������ģ��')
    sub.add_parser('stop', help='�ر�ָ���豸��ģ�ⶨλ')
    for name in ('hold', 'play'):
        cmd = sub.add_parser(name)
        if name == 'hold':
            cmd.add_argument('--lat', type=float, required=True)
            cmd.add_argument('--lon', type=float, required=True)
        else:
            cmd.add_argument('gpx', type=Path)
            cmd.add_argument('--loop', action='store_true')
        cmd.add_argument('--duration', type=int, default=60)
        cmd.add_argument('--interval', type=int, default=1)
        cmd.add_argument('--dry-run', type=Path, metavar='OUTPUT_GPX', help='ֻ�������� GPX���������ֻ�')
    args = parser.parse_args(argv)
    try:
        if args.command in ('hold', 'play'):
            points = [validate_point(args.lat, args.lon)] if args.command == 'hold' else load_gpx(args.gpx)
            if not 1 <= args.interval <= 60 or not 1 <= args.duration <= 3600:
                raise LabError('�����ΧΪ 1�C60 �룬ʱ����ΧΪ 1�C3600 �롣')
            if args.dry_run:
                args.dry_run.write_bytes(gpx_bytes(points[:30], args.interval))
                print('������ GPX��û�������ֻ����޸Ķ�λ��')
                return 0
        hdc = Hdc(args.hdc, args.device)
        if args.command == 'devices':
            print(hdc.run('list', 'targets', '-v'))
            return 0
        hdc.select()
        if args.command == 'stop':
            hdc.run('shell', 'testhelper', 'disable-location-mock')
            print('���ύ�ر�ģ�����������´�Ӧ��ȷ�϶�λ�ָ���')
        else:
            run_session(hdc, points, args.duration, args.interval, args.command == 'hold' or args.loop)
        return 0
    except KeyboardInterrupt:
        print('���жϲ��ԣ��������Ϸ��Ļָ������', file=sys.stderr)
        return 130
    except (LabError, OSError, ValueError, ET.ParseError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
