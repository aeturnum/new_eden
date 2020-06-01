
from os.path import basename
from pathlib import Path, PurePath

from typing import Optional, List

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
        # if self.call_count > 0:
        #     tab = '  '
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
        log = self.logger("__init__")
        log.v(f"{str_path}")
        # self._o_path = Path(str_path)
        self.path_obj: Path = Path(str_path)
        self._root = None
        self._stem = None
        self._parse()

        self._encoding = None

    def _parse(self):
        log = self.logger("_parse")
        log.v(f"{self.path_obj}")
        parts = 1

        directory = self.path_obj.parent
        while self._does_directory_have_init(directory):
            parts += 1
            directory = directory.parent

        # log.w(f"root: {self._root} -> {Path(*self.path_obj.parts[:-parts])}")
        # log.w(f"stem: {self._stem} -> {Path(*self.path_obj.parts[-parts:])}")
        self._root = Path(*self.path_obj.parts[:-parts])
        self._stem = Path(*self.path_obj.parts[-parts:])

    def _raise_exception_if_not_py(self):
        if not self.is_py_file:
            raise ValueError(f"{self} doesn't appear to be a python file!")

    def _detect_py_file_encoding(self) -> str:
        # https://stackoverflow.com/questions/17912307/u-ufeff-in-python-string
        enc = None
        with self.path_obj.open() as file:
            first_line = file.readline()
            if "-*- coding: utf-8 -*-" in first_line:
                enc = self._ENC_UTF8
                if ord(first_line[0]) == 65279:  # \ufeff - byte order mark
                    enc = self._ENC_UTF8BOM

        self._encoding = enc
        return enc

    def _join_python_file(self, path: Path, name):

        if '.py' not in name:
            name = f"{name}.py"

        path = path / name
        if not path.exists():
            raise ValueError(f"{path} does not exist!")

        return path

    def _is_python_file(self, path: Path, name: str):
        if not path.is_dir():
            return False

        new_path = path / name
        if new_path.exists() and new_path.suffix == "py":
            return True
        else:
            new_path = new_path.with_suffix(".py")
            return new_path.exists()

    def _does_directory_have_init(self, path: Path):
        if not path.is_dir():
            raise ValueError(f"{path}: not a directory")

        path = path / "__init__.py"
        if not path.exists():
            return False

        return True

    def read(self):
        self._raise_exception_if_not_py()
        self._detect_py_file_encoding()
        with self.path_obj.open(encoding=self._encoding) as file:
            return file.read()

    def swap_root(self, new_root: str) -> 'PythonPathWrapper':
        # first need to
        new_path = PythonPathWrapper(str(new_root))
        new_path = new_path._root
        new_path = new_path / self._stem
        # mod_replace_parts = modules_to_replace.split(".")
        # for idx, part in enumerate(self._stem.parts):
        #     if mod_replace_parts[idx] == part:
        #         new_path / part

        self.path_obj = new_path
        self._parse()

        return self

    def _merge_remainging_modules_and_symbols(self, module_parts: List[str], symbols) -> List[str]:
        """
        Sometimes python paths do not cleanly terminate at the file boundary, like:
            From package.package.file import symbol
        Instead, they will sometimes work like this:
            From file.symbol.symbol.symbol import symbol

        This makes sense, because to python there's a clean transition between package / file / symbols. The
        system treats them all as if they are flat.

        :param module_parts:
        :param symbols:
        :return:
        """
        if not module_parts:
            return symbols

        module_path = ".".join(module_parts)
        if not symbols:
            # easy!
            return [module_path]

        # todo: is this correct? Who knows
        return [f"{module_path}.{symbol}" for symbol in symbols]


    def find_relative_import(self, level, target_module, symbols = None) -> List[str]:
        """

        :param level: how many levels to go up
        :param target_module: module string
        :param symbols: symbol string (s)
        :return:
        """
        log = self.logger("find_relative_import")
        log.v(f"{level}, {target_module}, {symbols}")
        base_dir = self.path_obj

        if not level > 0:
            raise ValueError(f"Cannot find relative import with level of {level}")

        while level:
            base_dir = base_dir.parent
            if not self._is_python_file(base_dir, "__init__"):
                raise ValueError(f"Relative import call has passed into non-python directory: {base_dir}")
            level -= 1

        # now we try to find the target file, which should include the entire module and may include the symbols
        path_parts = []
        if target_module:
            if "." in target_module:
                # break into directory names
                path_parts.extend(target_module.split("."))
            else:
                # a single module
                path_parts.append(target_module)


        maybe_file: Path = Path(base_dir)
        # if we have more than one path part we should iterate through the possibilities

        last_pass = False
        while path_parts:
            # get a part out
            part = path_parts.pop(0)

            # if we find a python file early, exit
            if self._is_python_file(maybe_file, part):
                # we're done
                self.path_obj = self._join_python_file(maybe_file, part)
                self._parse()
                return self._merge_remainging_modules_and_symbols(path_parts, symbols)

            if not last_pass:
                # when the module_path has not been consumed we expect to keep finding directories
                if not maybe_file.exists():
                    raise ValueError(f"Something went wrong finding a relative import! base: {base_dir}, {maybe_file} does not exist! parts: {path_parts}")

                # add what we expect to be a directory
                maybe_file = maybe_file / part
                # log.d(f"  {maybe_file}")

                # mark if we are on the last pass to avoid throwing an exception if the current value of maybe_file doesn't exist
                if len(path_parts) == 1:
                    last_pass = True
            else:
                # this is the last path part and we're up to the symbols now
                maybe_file = maybe_file / part
                break

        # log.d(f"@symbols:{maybe_file}")
        if symbols:
            if len(symbols) == 1:
                # symbol might be name of python file we want
                if self._is_python_file(maybe_file, symbols[0]):
                    self.path_obj = self._join_python_file(maybe_file, symbols[0])
                    self._parse()
                    return []

            # this is a path to the __init__.py and the symbols are inside it
            if not self._is_python_file(maybe_file, "__init__.py"):
                raise ValueError(f"Expected directory {maybe_file} to be a python package with the __init__.py containing symbols: {symbols}")

            self.path_obj = maybe_file / "__init__.py"
            self._parse()
            return symbols

        if self._is_python_file(maybe_file, "__init__.py"):
            self.path_obj = maybe_file / "__init__.py"
            self._parse()
            return symbols

        raise ValueError(f"Could not find relative import: [{self.path_obj}] {level}, {target_module}, {symbols}")

    @property
    def module_guess(self):
        log = self.logger("module_guess")
        # log.w(f'{self.path_obj} | {self._stem}')
        parts = list(self._stem.parts[:-1])
        if self.path_obj.name != "__init__.py":
            parts.append(self.path_obj.stem)

        log.v(f'{self.path_obj} -> {".".join(parts)}')
        return ".".join(parts)

    def str(self):
        return str(self)

    @property
    def is_py_file(self):
        is_py = self.path_obj.suffix in self._python_exts
        if not is_py: # check if we're in a package
            try:
                is_py = self._does_directory_have_init(self.path_obj)
            except ValueError:
                # just return false
                pass
        return is_py

    @property
    def short_version(self):
        log = self.logger("short_version")

        return f"/{self._root.parts[-1]}/{'/'.join(self._stem.parts)}"
        # except Exception as e:
        #     log.e(f"Raised Exception! {e}: {self.path_obj}")


    def __str__(self):
        return str(self.path_obj)



#https://gist.github.com/thatalextaylor/7408395
def td_str(seconds):
    sign_string = '-' if seconds < 0 else ''
    seconds = abs(int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    if days > 365:
        years, days = divmod(days, 365)
        return '%s%dy %dd %dh %dm %ds' % (sign_string, years, days, hours, minutes, seconds)
    if days > 0:
        return '%s%dd %dh %dm %ds' % (sign_string, days, hours, minutes, seconds)
    elif hours > 0:
        return '%s%dh %dm %ds' % (sign_string, hours, minutes, seconds)
    elif minutes > 0:
        return '%s%dm %ds' % (sign_string, minutes, seconds)
    else:
        return '%s%ds' % (sign_string, seconds)