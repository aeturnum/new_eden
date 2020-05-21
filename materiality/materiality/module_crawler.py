from os import getcwd, listdir, remove
from os.path import join, splitext
from typing import Mapping, Set, List, Optional, Dict, Any

from .utils import Logger
from .ast_crawler import ImportStatement, ASTWrapper, ImportReference, ModuleManager
from .path_manager import PathManager
from findimports import find_imports, ImportInfo, ModuleGraph

class PathWrapper(str):

    @property
    def python_file(self):
        return splitext(self)[1] in ['.py', '.pyc']

class FakeSpec(ImportReference):
    def __init__(self, module: str, path: str, **kwargs):
        super().__init__(module, **kwargs)
        self.module = module
        self._path = path

    def _resolve_spec(self):
        pass

    @property
    def origin(self):
        return self._path

class ModuleCrawler(Logger):

    _NAME = 'ModuleCrawler'

    # to get all libraries
    # '--pylib-all', '--pylib'
    ARGS = ['--no-config', '--noshow']

    _ROOT_MODULE = '__main__'

    _Cleanup_Filters = [
        # find any _dummy files
        lambda x: x.startswith('_dummy') and x.endswith('.py')
    ]

    def __init__(self, target: str, **kwargs):
        super().__init__(**kwargs)

        self.has_new_results: bool = False
        # self.module_map: Dict[str, ModuleListingWrapper] = {}
        # self.path_map: Dict[str, ModuleListingWrapper] = {}
        self.paths_checked: Set[str] = set()
        self.modules_checked: Set[str] = set()
        self.next_paths: Set[str] = {target}
        self.has_results = False

        self.pm = PathManager()

    @property
    def done(self):
        return len(self.next_paths) == 0

    def step(self):
        if not self.has_new_results:
            # do the thing
            target = self.next_paths.pop()
            self._check_modules_for_target(target)
            print(self.pm)
            # cleanup
            self._cleanup()
            self.has_results = True

    def _check_modules_for_target(self, target):
        log = self.logger("_check_modules_for_target")
        log.d(f"{target}")

        mod_manage = self.pm.module_for_path(target)

        self.paths_checked.add(target)

        for imp in mod_manage.imports:
            self.pm.resolve_import(imp)

        for p in mod_manage.valid_import_paths:
            if p not in self.paths_checked:
                self.next_paths.add(p)

    def _cleanup(self):
        base = getcwd()
        files = listdir(base)
        for f in ModuleCrawler._Cleanup_Filters:
            files = filter(f, files)

        for f in files:
            # remove files from filters
            remove(join(base, f))
