
from .utils import Logger, PythonPathWrapper
from .ast_crawler import ModuleManager, ImportReference

from typing import Set, List, Optional, Dict, Any

class PathManager(Logger):
    """
    Class to track:
        - where modules have been scanned
        - git repositories and what modules they're related to
        - help with relative imports
    """
    _NAME = "PathManager"

    # locations
    _git_repos = {
        'web2py': '/Users/ddrexler/src/python/web2py/web2py.py',
        'eden': '/Users/ddrexler/masters/Source/__init__.py',
        'gluon': '/Users/ddrexler/src/python/web2py/gluon/__init__.py',
        'pydal':'/Users/ddrexler/src/python/web2py/gluon/packages/dal/pydal/__init__.py',
        'yatl': '/Users/ddrexler/src/python/web2py/gluon/packages/yatl/yatl/__init__.py'
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.path_to_module: Dict[str, ModuleManager] = {}
        self._shadow_paths: Dict[str, ModuleManager] =  {}
        self.module_name_to_module: Dict[str, ModuleManager] = {}

    # def _get_real_path(self, module_name: str) -> Optional[str]:
    #     if module_name in self._git_repos:
    #         return self._git_repos[module_name]
    #
    #     return None

    # def _resolve_relative_import_path(self, imp_ref: ImportReference):
    #     ppw = PythonPathWrapper(imp_ref.statement_file_path)
    #     ppw.find_relative_import(imp_ref.level, imp_ref.module)
    #     # todo: this doesn't fully solve the problem, because we still use find_spec to search
    #     # todo: for the module name
    #     # todo: maybe we should filter path names when we're creating ModuleManagers
    #     imp_ref.resolve(ppw)

    def _search_for_git_module(self, full_module_path):
        # todo: this needs to replace the root of the rest of the module path
        log = self.logger("_search_for_git_module")
        partial_path = None
        match = None
        for section in full_module_path.split("."):
            if not partial_path:
                partial_path = section
            else:
                partial_path = f'{partial_path}.{section}'

            if partial_path in self._git_repos:
                match = self._git_repos[partial_path]

        log.w(f'found {full_module_path} -> {match}')
        return match

    def _get_create_mm(self, path: str) -> ModuleManager:
        if path not in self.path_to_module:
            self.path_to_module[path] = ModuleManager(path)

        return self.path_to_module[path]

    def external_path(self, module_name):
        return self._search_for_git_module(module_name)

    def has_external_path(self, module_name):
        return self._search_for_git_module(module_name) is not None

    # def check_for_external_path(self, imp_ref : ImportReference):
    #     if self.has_external_path(imp_ref.module):

    def set_external_path_if_exists(self, imp_ref: ImportReference) -> None:
        ext_path = self.external_path(imp_ref.module)
        if ext_path:
            imp_ref.set_external_path(ext_path)

    def module_for_import(self, imp_ref: ImportReference) -> ModuleManager:

        self.set_external_path_if_exists(imp_ref)
        return self._get_create_mm(imp_ref.path)


    def module_for_path(self, path: str) -> ModuleManager:
        log = self.logger("module_for_path")

        path_wrapper = PythonPathWrapper(path)
        ext_path = self.external_path(path_wrapper.module_guess)

        if ext_path:
            log.w(f"Swapping path {path_wrapper} -> {ext_path} ")
            path = path_wrapper.swap_root(ext_path).str()

        return self._get_create_mm(path)

    # def resolve_import(self, imp_ref: ImportReference):
    #     log = self.logger("resolve_import")
    #     log.v(f"{imp_ref}")
    #     if imp_ref.needs_resolution:
    #         if imp_ref.relative:
    #             self._resolve_relative_import_path(imp_ref)
    #         else:
    #             imp_ref.resolve()
    #             # imp_ref.resolve(
    #             #     PythonPathWrapper(self._get_real_path(imp_ref.module))
    #             # )
    #
    #
    #     return imp_ref

    def __str__(self):
        lines = []
        for p, m in self.path_to_module.items():

            lines.append(f"<{p}>\n{self.indent(m.symbols)}")

        return f'<PathManager>\n{self.indent(lines)}'