import os
import struct
import unittest
import unittest.mock as mock

import zipmeta as zipfile

# polyfills
try:
    from test.test_zipfile.test_core import (
        TESTFN,
        TESTFN2,
        ExtractTests,
        StoredTestsWithSourceFile,
        temp_cwd,
    )
except ImportError:
    # polyfill for Python < 3.12
    from test.test_zipfile import (
        TESTFN,
        TESTFN2,
        ExtractTests,
        StoredTestsWithSourceFile,
        temp_cwd,
    )


class StoredTestsWithSourceFile(StoredTestsWithSourceFile,
                                unittest.TestCase):
    compression = zipfile.ZIP_STORED
    test_low_compression = None

    def test_add_file_with_ext_timestamp(self):
        """Check that calling ZipFile.write() sets extra data according to
        with_ext_timestamps parameter."""
        mtime = 946684800.123456
        mtime_ns = 946684800_123456789
        atime_ns = 946684800_987654321
        ctime_ns = 946684800_555555555

        with mock.patch('os.stat_result.st_mtime', mtime), \
             mock.patch('os.stat_result.st_mtime_ns', mtime_ns), \
             mock.patch('os.stat_result.st_atime_ns', atime_ns), \
             mock.patch('os.stat_result.st_ctime_ns', ctime_ns):

            # with_ext_timestamps=False (default)
            with zipfile.ZipFile(TESTFN2, "w") as zipfp:
                zipfp.write(TESTFN)

            with zipfile.ZipFile(TESTFN2) as zipfp:
                zinfo = zipfp.infolist()[0]

            self.assertEqual(zinfo.extra, b'')

            # with_ext_timestamps=True
            with zipfile.ZipFile(TESTFN2, "w", with_ext_timestamps=True) as zipfp:
                zipfp.write(TESTFN)

            with zipfile.ZipFile(TESTFN2) as zipfp:
                zinfo = zipfp.infolist()[0]

            self.assertEqual(zinfo.date_time[0], 2000)

            # NTFS Extra Field (0x000a)
            ntfs_field = struct.unpack_from('<HHLHHQQQ', zinfo.extra)
            self.assertEqual(ntfs_field, (
                0x000a, 32,
                0, 0x0001, 24,
                mtime_ns // 100 + zipfile._NTFS_EXTRA_TS_DELTA,
                atime_ns // 100 + zipfile._NTFS_EXTRA_TS_DELTA,
                ctime_ns // 100 + zipfile._NTFS_EXTRA_TS_DELTA,
            ))

            # Extended timestamp (0x5455)
            ut_field = struct.unpack_from('<HHBL', zinfo.extra, struct.calcsize('<HHLHHQQQ'))
            self.assertEqual(ut_field, (0x5455, 5, 1, int(mtime)))

    def test_add_file_with_ext_timestamp_after_2038(self):
        """Extended timestamp field should exist for a timestamp after
        2038-01-19T03:14:07Z."""
        mtime = 2147483648.123456  # 2038-01-19T03:14:08.123456Z

        with mock.patch('os.stat_result.st_mtime', mtime):
            with zipfile.ZipFile(TESTFN2, "w", strict_timestamps=False,
                                 with_ext_timestamps=True) as zipfp:
                zipfp.write(TESTFN)

            with zipfile.ZipFile(TESTFN2) as zipfp:
                zinfo = zipfp.infolist()[0]

            self.assertEqual(zinfo.date_time[0], 2038)

            # Extended timestamp (0x5455)
            ntfs_field_len = struct.calcsize('<HHLHHQQQ')
            ut_field = struct.unpack_from('<HHBL', zinfo.extra, ntfs_field_len)
            self.assertEqual(ut_field, (0x5455, 5, 1, int(mtime)))

    def test_add_file_with_ext_timestamp_after_2106(self):
        """Extended timestamp field should not exist for a timestamp after
        2106-02-07T06:28:15Z."""
        mtime = 4294967296.123456  # 2106-02-07T06:28:16.123456Z

        with mock.patch('os.stat_result.st_mtime', mtime):
            with zipfile.ZipFile(TESTFN2, "w", strict_timestamps=False,
                                 with_ext_timestamps=True) as zipfp:
                zipfp.write(TESTFN)

            with zipfile.ZipFile(TESTFN2) as zipfp:
                zinfo = zipfp.infolist()[0]

            self.assertEqual(zinfo.date_time[0], 2106)

            # Only an NTFS Extra Field (0x000a) exists
            ntfs_field_len = struct.calcsize('<HHLHHQQQ')
            self.assertEqual(len(zinfo.extra), ntfs_field_len)


class ExtractTests(ExtractTests):
    def test_extract_meta_mtime(self):
        with temp_cwd():
            mtime = 946684801.123456
            with mock.patch('os.stat_result.st_mtime', mtime):
                with open(TESTFN, "wb") as fp:
                    fp.write(b'foo')
                with zipfile.ZipFile(TESTFN2, "w", strict_timestamps=False) as zipfp:
                    zipfp.write(TESTFN)

            with zipfile.ZipFile(TESTFN2, "r") as zipfp:
                zinfo = zipfp.infolist()[0]
                writtenfile = zipfp.extract(zinfo)

                mt = os.stat(writtenfile).st_mtime_ns
                expected_mtime = 946684800_000_000_000
                self.assertEqual(mt, expected_mtime)

    def test_extract_meta_extra_ext_ts(self):
        with temp_cwd():
            mtime = 2147483649.123456  # 2038-01-19T03:14:09.123456Z
            with mock.patch('os.stat_result.st_mtime', mtime):
                with open(TESTFN, "wb") as fp:
                    fp.write(b'foo')
                with zipfile.ZipFile(TESTFN2, "w", strict_timestamps=False,
                                     with_ext_timestamps=True) as zipfp:
                    zipfp.write(TESTFN)

            with zipfile.ZipFile(TESTFN2, "r") as zipfp:
                zinfo = zipfp.infolist()[0]
                zinfo.extra = zipfile._Extra.strip(zinfo.extra, (0x000a,))
                writtenfile = zipfp.extract(zinfo)

                mt = os.stat(writtenfile).st_mtime_ns
                expected_mtime = 2147483649_000_000_000
                self.assertEqual(mt, expected_mtime)

    def test_extract_meta_extra_ntfs(self):
        with temp_cwd():
            mtime = 4294967296.123456
            mtime_ns = 4294967296_123456789  # 2106-02-07T06:28:16.123456789Z
            atime_ns = 4294967296_987654321
            with mock.patch('os.stat_result.st_mtime', mtime), \
                 mock.patch('os.stat_result.st_mtime_ns', mtime_ns), \
                 mock.patch('os.stat_result.st_atime_ns', atime_ns):
                with open(TESTFN, "wb") as fp:
                    fp.write(b'foo')
                with zipfile.ZipFile(TESTFN2, "w", strict_timestamps=False,
                                     with_ext_timestamps=True) as zipfp:
                    zipfp.write(TESTFN)

            with zipfile.ZipFile(TESTFN2, "r") as zipfp:
                zinfo = zipfp.infolist()[0]
                writtenfile = zipfp.extract(zinfo)

                mt = os.stat(writtenfile).st_mtime_ns
                expected_mtime = mtime_ns // 100 * 100
                self.assertEqual(mt, expected_mtime)

                at = os.stat(writtenfile).st_atime_ns
                expected_atime = atime_ns // 100 * 100
                self.assertEqual(at, expected_atime)

    def test_extract_all_meta(self):
        test_files = [
            ('file1', b'foo', 946684801_123456789),
            ('file2', b'bar', 4294967296_123456789),
        ]

        with temp_cwd():
            with zipfile.ZipFile(TESTFN2, "w", strict_timestamps=False,
                                 with_ext_timestamps=True) as zipfp:
                for file, content, mtime_ns in test_files:
                    with mock.patch('os.stat_result.st_mtime_ns', mtime_ns), \
                         open(TESTFN, "wb") as fp:
                        fp.write(content)
                        zipfp.write(TESTFN, file)

            with zipfile.ZipFile(TESTFN2, "r") as zipfp:
                zipfp.extractall()

            for file, _, mtime_ns in test_files:
                outfile = os.path.join(os.getcwd(), file)

                mt = os.stat(outfile).st_mtime_ns
                expected_mtime = mtime_ns // 100 * 100
                self.assertEqual(mt, expected_mtime)
