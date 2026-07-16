import os
import struct
import time
from unittest import mock
from zipfile import *  # noqa: F403

_NTFS_EXTRA_TS_DELTA = 116444736_000_000_000

_ZipInfo = ZipInfo
_ZipFile = ZipFile

try:
    from zipfile import _Extra
    _Extra.iter
except (ImportError, AttributeError):
    class _Extra:
        FIELD_STRUCT = struct.Struct('<HH')

        @classmethod
        def iter(cls, data, validate=False):
            """Iter through and yield each (field, id)."""
            # early return for empty extra data
            if not data:
                return

            pos, data_len = 0, len(data)
            while pos < data_len:
                try:
                    xid, xlen = cls.FIELD_STRUCT.unpack_from(data, pos)
                except struct.error:
                    xid, xlen = None, 0
                else:
                    if validate and pos + 4 + xlen > data_len:
                        raise BadZipFile(
                            "Corrupt extra field %04x (size=%d)" % (xid, xlen))
                yield data[pos:pos + 4 + xlen], xid
                pos += 4 + xlen

        @classmethod
        def strip(cls, data, xids):
            """Remove Extra fields with specified IDs."""
            return b''.join(
                ex
                for ex, xid in cls.iter(data)
                if xid not in xids
            )

        @classmethod
        def update(cls, data, extra):
            """Insert fields from extra and strip duplicates."""
            # early return for empty data
            if not data:
                return extra

            extras = {
                xid: ex
                for ex, xid in cls.iter(extra)
                if xid is not None
            }
            # New fields first since data may have a corrupted tail that renders
            # following fields inaccessible.  (The caller is responsible for making
            # sure that extra is valid.)
            return b''.join(extras.values()) + cls.strip(data, extras)


class ZipInfo(_ZipInfo):
    @classmethod
    def from_file(cls, filename, *args, with_ext_timestamps=False, **kwargs):
        st = os.stat(filename)

        with mock.patch('os.stat', return_value=st):
            zinfo = super().from_file(filename, *args, **kwargs)

        if with_ext_timestamps:
            # NTFS Extra Field (0x000a)
            ft_mtime = st.st_mtime_ns // 100 + _NTFS_EXTRA_TS_DELTA
            ft_atime = st.st_atime_ns // 100 + _NTFS_EXTRA_TS_DELTA
            ft_ctime = st.st_ctime_ns // 100 + _NTFS_EXTRA_TS_DELTA
            ntfs_tag = struct.pack('<LHHQQQ', 0, 0x0001, 24, ft_mtime, ft_atime, ft_ctime)
            extra = struct.pack('<HH', 0x000a, len(ntfs_tag)) + ntfs_tag

            # Extended timestamp (0x5455)
            # According to libzip's doc, the timestamps should be 4-byte
            # unsigned integers:
            # https://libzip.org/specifications/extrafld.txt
            mtime = int(st.st_mtime)
            if 0 <= mtime <= 0xFFFF_FFFF:
                extra += struct.pack('<HHBL', 0x5455, 5, 0x01, mtime)

            zinfo.extra = extra

        return zinfo


class ZipFile(_ZipFile):
    def __init__(self, *args, with_ext_timestamps=False, **kwargs):
        super().__init__(*args, **kwargs)
        self._with_ext_timestamps = with_ext_timestamps

    def write(self, *args, **kwargs):
        orig_from_file = _ZipInfo.from_file

        def from_file(*args, **kwargs):
            with mock.patch('zipfile.ZipInfo.from_file', orig_from_file):
                return ZipInfo.from_file(
                    *args, **kwargs, with_ext_timestamps=self._with_ext_timestamps)

        with mock.patch('zipfile.ZipInfo.from_file', from_file):
            return super().write(*args, **kwargs)

    def _extract_member(self, *args, **kwargs):
        orig_zopen = _ZipFile.open

        def m_zopen(self, member, *args, **kwargs):
            nonlocal zinfo
            zinfo = member
            return orig_zopen(self, member, *args, **kwargs)

        zinfo = None
        with mock.patch('zipfile.ZipFile.open', m_zopen):
            targetpath = super()._extract_member(*args, **kwargs)

        ns_time = self._get_mtime(zinfo)
        os.utime(targetpath, None, ns=ns_time)

        return targetpath

    def _get_mtime(self, zinfo):
        unpack_from = struct.unpack_from
        for extra, tp in _Extra.iter(zinfo.extra, True):
            pos = 4
            if tp == 0x000a:
                # NTFS Extra Field (0x000a)
                fmt = '<LHH'
                while True:
                    try:
                        _, ntfs_id, ntfs_len = unpack_from(fmt, extra, pos)
                    except struct.error:
                        break

                    if ntfs_id != 0x0001:
                        continue

                    pos += struct.calcsize(fmt)
                    ft_mtime, ft_atime, ft_ctime = unpack_from('<QQQ', extra, pos)
                    return (
                        (ft_atime - _NTFS_EXTRA_TS_DELTA) * 100,
                        (ft_mtime - _NTFS_EXTRA_TS_DELTA) * 100,
                    )

            elif tp == 0x5455:
                # Extended timestamp (0x5455)
                ut_bits, ut_mtime = unpack_from('<BL', extra, pos)
                if ut_bits & 0x01:
                    ut = ut_mtime * 1_000_000_000
                    return ut, ut

        ut = int(time.mktime(zinfo.date_time + (0, 0, -1))) * 1_000_000_000
        return ut, ut
