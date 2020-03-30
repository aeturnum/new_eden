
from functools import partialmethod

VERBOSE = 0
DEBUG = 1
WARN = 2
ERROR = 3

log_level = DEBUG


def _record(level, func,s, **kwargs):
    print(f'[{level}]{func}| {s}')

def level(log_override = None):
    global log_level
    return log_override or log_level

def dlog(func, s, **kwargs):
    global level
    if level(**kwargs) <= DEBUG:
        _record('D', func, s, **kwargs)

def wlog(func, s, **kwargs):
    global level
    if level(**kwargs) <= WARN:
        _record('W', func, s, **kwargs)

def elog(func, s, **kwargs):
    global level
    if level(**kwargs) <= ERROR:
        _record('!!E!!', func, s, **kwargs)

class Logger:
    VERBOSE = VERBOSE
    DEBUG = DEBUG
    WARN = WARN
    ERROR = ERROR

    _NAME = "Logger"

    def __init__(self, special_log_level=None):
        self._own_level = special_log_level

    def _construct_log_string(self, func):
        return f'{self._NAME}::{func}'

    def gen_dlog(self, func):
        global dlog
        override = self._own_level
        log_str = self._construct_log_string(func)
        return lambda s: dlog(log_str, s, log_override = override)

    def gen_wlog(self, func):
        global dlog
        override = self._own_level
        log_str = self._construct_log_string(func)
        return lambda s: wlog(log_str, s, log_override = override)

    def dlog(self, func, s):
        global dlog
        dlog(self._construct_log_string(func), s, log_override = self._own_level)

    def wlog(self, func, s):
        global dlog
        wlog(self._construct_log_string(func), s, log_override = self._own_level)

    def elog(self, func, s):
        global dlog
        elog(self._construct_log_string(func), s, log_override = self._own_level)
