import datetime
import logging
import unittest

from app.service.system_service import TEHRAN_TZ, TehranTimeFormatter, LOG_BUFFER, log_buffer_handler


class TehranTimezoneTests(unittest.TestCase):
    def test_offset_is_3_30(self):
        self.assertEqual(TEHRAN_TZ.utcoffset(None), datetime.timedelta(hours=3, minutes=30))

    def test_formatter_uses_tehran_time(self):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
        record.created = 0.0  # 1970-01-01 00:00:00 UTC
        stamp = TehranTimeFormatter().formatTime(record)
        self.assertEqual(stamp, "1970-01-01 03:30:00")

    def test_buffer_entry_time_is_tehran(self):
        record = logging.LogRecord("tz.test", logging.INFO, __file__, 1, "tz-msg", None, None)
        record.created = 0.0
        log_buffer_handler.emit(record)
        entry = LOG_BUFFER[-1]
        self.assertEqual(entry["time"], "1970-01-01 03:30:00")
        self.assertIn("1970-01-01 03:30:00", entry["raw"])


if __name__ == "__main__":
    unittest.main()
