# logbuffer.py
# ログ保持用のファイル
import logging
from collections import deque

class LogBuffer(logging.Handler):
    def __init__(self, maxlen=100):
        super().__init__()
        self.logs = deque(maxlen=maxlen)

    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append(log_entry)
