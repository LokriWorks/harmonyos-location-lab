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

NS = 'http://www.topografix.com/GPX/1/1'
ET.register_namespace('', NS)


class LabError(RuntimeError):
    pass


def validate_point(latitude, longitude):
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise LabError('纬度必须在 -90 到 90 之间。')
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise LabError('经度必须在 -180 到 180 之间。')
    return float(latitude), float(longitude)


def load_gpx(file):
    file = Path(file)
    if file.stat().st_size > 2 * 1024 * 1024:
        raise LabError('GPX 文件不能超过 2 MB。')
    root = ET.parse(file).getroot()
    try:
        points = [validate_point(float(p.attrib['lat']), float(p.attrib['lon']))
                  for p in root.iter() if p.tag.split('}')[-1] in ('trkpt', 'rtept', 'wpt')]
    except (KeyError, ValueError) as exc:
        raise LabError('GPX 中的位置点缺少有效的经纬度。') from exc
    if not points or len(points) > 10000:
        raise LabError('GPX 需要包含 1–10000 个位置点。')
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
            raise LabError('找不到 HDC，请配置 PATH、HDC_PATH 或 --hdc。')
        self.device = device

    def run(self, *args):
        command = [self.executable] + (['-t', self.device] if self.device else []) + list(map(str, args))
        try:
            done = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', timeout=20, **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))
        except subprocess.TimeoutExpired as exc:
            raise LabError('HDC 响应超时，请检查连接；恢复连接后可执行 stop。') from exc
        output = (done.stdout + done.stderr).strip()
        listing = args[:2] == ('list', 'targets')
        markers = ('[fail]', 'error:', 'unknown command', 'not supported') + (() if listing else ('unauthorized',))
        if done.returncode or any(s in output.lower() for s in markers):
            raise LabError('HDC 未确认操作成功：' + output[:500])
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
            raise LabError('没有找到目标设备，请连接手机并开启 USB 调试。')
        if len(selected) != 1:
            raise LabError('检测到多个设备，请用 --device 指定目标。')
        if selected[0]['status'].lower() != 'connected':
            raise LabError('手机尚未授权，请解锁手机并允许这台电脑调试。')
        self.device = selected[0]['id']


def run_session(hdc, points, duration=60, interval=1, loop=False, batch_size=30,
                clock=time.monotonic, sleeper=time.sleep, report=print):
    if not points:
        raise LabError('没有位置点。')
    points = [validate_point(*p) for p in points]
    if not isinstance(interval, int) or not 1 <= interval <= 60 or not 1 <= duration <= 3600:
        raise LabError('间隔范围为 1–60 秒，时长范围为 1–3600 秒。')
    if not 2 <= batch_size <= 90:
        raise LabError('每批点数必须在 2–90 之间。')
    duration = min(duration, len(points)*interval) if not loop else duration
    remote = '/data/local/tmp/harmony-location-' + uuid.uuid4().hex + '.gpx'
    attempted, primary_error = False, None
    batches = 0
    try:
        hdc.run('shell', 'testhelper', 'disable-location-mock')
        attempted = True
        hdc.run('shell', 'testhelper', 'enable-location-mock')
        with tempfile.TemporaryDirectory(prefix='harmony-location-') as folder:
            local = Path(folder)/'batch.gpx'
            start = clock()
            while clock()-start < duration:
                elapsed = clock()-start
                cursor = int(elapsed//interval)
                count = batch_size if loop else min(batch_size, len(points)-cursor)
                if count <= 0:
                    break
                batch = [points[(cursor+i) % len(points)] for i in range(count)]
                local.write_bytes(gpx_bytes(batch, interval))
                hdc.run('file', 'send', str(local), remote)
                answer = hdc.run('shell', 'testhelper', 'set-mocked-locations', remote, str(interval))
                if 'set mocked locations successfully' not in answer.lower():
                    raise LabError('系统没有返回预期的位置提交确认。')
                batches += 1
                report(f'第 {batches} 批已被系统接受；应用是否读取需要在手机上确认。')
                # Resubmit ahead of exhaustion. Slow USB calls can still cause gaps.
                refill = elapsed + max(1, count-min(10, count-1))*interval
                while clock()-start < min(duration, refill):
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
                report('系统已接受关闭模拟的请求，请在应用中确认正常定位。')
            except Exception:
                failures.append('关闭模拟未获确认：请恢复连接后执行 stop，必要时在手机上关闭调试并重启定位。')
        try:
            hdc.run('shell', 'rm', remote)
        except Exception:
            failures.append('临时 GPX 文件未确认删除。')
        for failure in failures:
            report(failure)
        if failures and primary_error is None:
            raise LabError('测试结束，但清理不完整。')
    return batches


def main(argv=None):
    parser = argparse.ArgumentParser(description='鸿蒙位置模拟与 GPX 轨迹测试工具（实验版）')
    parser.add_argument('--version', action='version', version='HarmonyOS Location Lab 0.1.0-draft')
    parser.add_argument('--hdc', default=os.getenv('HDC_PATH', 'hdc'))
    parser.add_argument('--device', help='指定设备；不写则仅在检测到一台已连接设备时自动选择')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('devices', help='列出设备，不开启模拟')
    sub.add_parser('stop', help='关闭指定设备的模拟定位')
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
        cmd.add_argument('--dry-run', type=Path, metavar='OUTPUT_GPX', help='只生成样例 GPX，不连接手机')
    args = parser.parse_args(argv)
    try:
        if args.command in ('hold', 'play'):
            points = [validate_point(args.lat, args.lon)] if args.command == 'hold' else load_gpx(args.gpx)
            if not 1 <= args.interval <= 60 or not 1 <= args.duration <= 3600:
                raise LabError('间隔范围为 1–60 秒，时长范围为 1–3600 秒。')
            if args.dry_run:
                args.dry_run.write_bytes(gpx_bytes(points[:30], args.interval))
                print('已生成 GPX，没有连接手机或修改定位。')
                return 0
        hdc = Hdc(args.hdc, args.device)
        if args.command == 'devices':
            print(hdc.run('list', 'targets', '-v'))
            return 0
        hdc.select()
        if args.command == 'stop':
            hdc.run('shell', 'testhelper', 'disable-location-mock')
            print('已提交关闭模拟请求，请重新打开应用确认定位恢复。')
        else:
            run_session(hdc, points, args.duration, args.interval, args.command == 'hold' or args.loop)
        return 0
    except KeyboardInterrupt:
        print('已中断测试；请留意上方的恢复结果。', file=sys.stderr)
        return 130
    except (LabError, OSError, ValueError, ET.ParseError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
