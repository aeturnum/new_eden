
VERBOSE = 0
DEBUG = 1
WARN = 2
ERROR = 3

log_level = WARN


def _record(s, **kwargs):
    print(s)

def level(log_override = None):
    global log_level
    return log_override or log_level

def dlog(s, **kwargs):
    global level
    if level(**kwargs) <= DEBUG:
        _record(s, **kwargs)

def wlog(s, **kwargs):
    global level
    if level(**kwargs) <= WARN:
        _record(s, **kwargs)

class Logger:
    VERBOSE = VERBOSE
    DEBUG = DEBUG
    WARN = WARN
    ERROR = ERROR

    def __init__(self, special_log_level=None):
        self._own_level = special_log_level

    def dlog(self, s):
        global dlog
        dlog(s, log_override = self._own_level)

    def wlog(self, s):
        global dlog
        wlog(s, log_override = self._own_level)
