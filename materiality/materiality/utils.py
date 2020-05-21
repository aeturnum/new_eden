
from os.path import basename
from pathlib import Path

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

    def indent(self, s, num = 1, indent = "  ", converted = False):
        if isinstance(s, str):
            return indent * num + f"\n{indent * num}".join(s.split("\n"))
        elif isinstance(s, list):
            return "\n".join([self.indent(list_str, num, indent) for list_str in s])
        elif not converted:
            return self.indent(str(s), num, indent, True)
        else:
            raise ValueError(f"Don't know how to handle indenting: {s}")

class PythonPathWrapper(Logger):

    _NAME = "PPW"

    _ENC_UTF8 = 'utf-8'
    _ENC_UTF8BOM = 'utf-8-sig'

    _python_exts = ['.py', '.pyc']

    def __init__(self, str_path:str, **kwargs):
        super().__init__(**kwargs)
        self._o_path = Path(str_path)
        self._m_path = Path(str_path)

        self._encoding = None

    def _raise_exception_if_not_py(self):
        if not self.is_py_file:
            raise ValueError(f"{self} doesn't appear to be a python file!")

    def _detect_py_file_encoding(self) -> str:
        # https://stackoverflow.com/questions/17912307/u-ufeff-in-python-string
        enc = None
        with self._m_path.open() as file:
            first_line = file.readline()
            if "-*- coding: utf-8 -*-" in first_line:
                enc = self._ENC_UTF8
                if ord(first_line[0]) == 65279:  # \ufeff - byte order mark
                    enc = self._ENC_UTF8BOM

        self._encoding = enc
        return enc

    def read(self):
        self._raise_exception_if_not_py()
        self._detect_py_file_encoding()
        with self._m_path.open(encoding=self._encoding) as file:
            return file.read()

    def find_relative_import(self, level, target_module):
        dir = self._m_path

        if not level > 0:
            raise ValueError(f"Cannot find relative import with level of {level}")

        while level:
            dir = dir.parent
            if not self._does_directory_have_init(dir):
                raise ValueError(f"Relative import call has passed into non-python directory: {dir}")
            level -= 1
        for ext in self._python_exts:
            dir = dir / f'{target_module}{ext}'
            print(dir)
            if dir.exists() and dir.is_file():
                self._m_path = dir
                return True

        return False


    def _does_directory_have_init(self, path: Path):
        if not path.is_dir():
            raise ValueError(f"{path}: not a directory")

        path = path / "__init__.py"
        if not path.exists():
            return False

        return True

    @property
    def module_guess(self):
        parts = 1
        include_name = True
        if self._m_path.name == "__init__.py":
            include_name = False  # ignore file name if the file name is the module package

        directory = self._m_path.parent
        while self._does_directory_have_init(directory):
            parts += 1
            directory = directory.parent

        parts = list(self._m_path.parts[-parts:-1])
        if include_name:
            parts.append(self._m_path.stem)

        return '.'.join(parts)

    def str(self):
        return str(self)

    @property
    def is_py_file(self):
        return self._m_path.suffix in self._python_exts

    @property
    def short_version(self):
        included_sections = []

        for section in self._m_path.parts:
            if "python" in section or included_sections:
                included_sections.append(section)
                continue

        return f"/{'/'.join(included_sections)}"


    def __str__(self):
        return str(self._m_path)
