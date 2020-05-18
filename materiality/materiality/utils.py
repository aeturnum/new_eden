
from functools import partialmethod

VERBOSE = 'VERBOSE'
DEBUG = 'DEBUG'
WARN = 'WARN'
ERROR = 'ERROR'

LEVELS = {
    VERBOSE: {
        'level': 0,
        'marker': 'V'
    },
    DEBUG: {
        'level': 1,
        'marker': 'D'
    },
    WARN: {
        'level': 2,
        'marker': 'W'
    },
    ERROR: {
        'level': 3,
        'marker': '!E!'
    }
}

log_level = LEVELS[DEBUG]

def _record(level, func,s, **kwargs):
    print(f'[{level}]{func}| {s}')

def resolve_log_level(log_override = None):
    global log_level
    return log_override or log_level['level']

def log(message_log_level, func, s, **kwargs):
    if resolve_log_level(**kwargs) <= message_log_level['level']:
        _record(message_log_level['marker'], func, s, **kwargs)

def vlog(func, s, **kwargs):
    log(LEVELS[VERBOSE], func, s, **kwargs)

def dlog(func, s, **kwargs):
    log(LEVELS[DEBUG], func, s, **kwargs)

def wlog(func, s, **kwargs):
    log(LEVELS[WARN], func, s, **kwargs)

def elog(func, s, **kwargs):
    log(LEVELS[ERROR], func, s, **kwargs)

class LogContext:

    def __init__(self, class_name, function_name, own_level = None):
        self.function_name = function_name
        self.class_name = class_name
        self._own_level = own_level
        self.call_count = 0

    def _construct_log_string(self):

        return f'{self.class_name}::{self.function_name}'

    def _log(self, level, s):
        global log
        tab = ''
        if self.call_count > 0:
            tab = '  '
        log(
            LEVELS[level],
            self._construct_log_string(),
            f'{tab}{s}',
            log_override=self._own_level
        )

        self.call_count += 1

    def v(self, s):
        self._log(VERBOSE, s)

    def d(self, s):
        self._log(DEBUG, s)

    def w(self, s):
        self._log(WARN, s)

    def e(self, s):
        self._log(ERROR, s)

class Logger:
    _NAME = "Logger"

    def __init__(self, special_log_level=None):
        self._own_level = special_log_level

    def _construct_log_string(self, func):
        return f'{self._NAME}::{func}'

    def logger(self, function_name):
        return LogContext(self._NAME, function_name, self._own_level)