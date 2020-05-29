from pathlib import  Path
from typing import Set, List, Optional, Dict, Any
from collections import namedtuple

from .utils import Logger, PythonPathWrapper
from .ast_crawler import ModuleManager, ImportReference, StatNode
from .git_helper import GitHelper, File

ModPaths = namedtuple("ModPaths",["common_root", "module_path", "git_path"])

class PathManager(Logger):
    """
    Class to track:
        - where modules have been scanned
        - git repositories and what modules they're related to
        - help with relative imports
    """
    _NAME = "PathManager"

    # locations
    _module_map : Dict[str, ModPaths] = {
        'web2py': ModPaths('/Users/ddrexler/src/python/web2py/', 'web2py.py', ''),
        'eden': ModPaths('/Users/ddrexler/masters/Source/', '__init__.py', ''),
        'gluon': ModPaths('/Users/ddrexler/src/python/web2py/gluon/', '__init__.py', '../'),
        'pydal': ModPaths('/Users/ddrexler/src/python/web2py/gluon/packages/dal/', 'pydal/__init__.py', ''),
        'yatl': ModPaths('/Users/ddrexler/src/python/web2py/gluon/packages/yatl/', 'yatl/__init__.py', ''),
        'bcgs': ModPaths('/Users/ddrexler/src/python/breitbart_comment_grabbing_server/', 'bcgs/server.py', '')
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.path_to_module: Dict[str, ModuleManager] = {}
        # self.module_name_to_module: Dict[str, ModuleManager] = {}
        self.git_helpers: Dict[str, GitHelper] = {k:GitHelper(k, str(Path(v.common_root, v.git_path))) for k, v in self._module_map.items()}
        self._helpers_have_been_spun = False

    def crawl_git_helpers(self):
        if not self._helpers_have_been_spun:
            for h in self.git_helpers.values():
                h.index()
            self._helpers_have_been_spun = True

    def _search_for_module(self, full_module_path:str) -> Optional[ModPaths]:
        # todo: this needs to replace the root of the rest of the module path
        log = self.logger("_search_for_module")
        partial_mod_name = None
        match = None
        for section in full_module_path.split("."):
            if not partial_mod_name:
                partial_mod_name = section
            else:
                partial_mod_name = f'{partial_mod_name}.{section}'

            if partial_mod_name in self._module_map:
                match = self._module_map[partial_mod_name]

        log.v(f'found {full_module_path} -> {match}')
        return match

    def _get_create_mm(self, path: str) -> ModuleManager:
        if path not in self.path_to_module:
            self.path_to_module[path] = ModuleManager(path)

        return self.path_to_module[path]

    def module_path(self, module_name: str) -> Optional[str]:
        map_entry = self._search_for_module(module_name)
        if map_entry:
            root = Path(map_entry.common_root) / map_entry.module_path
            return str(root)

        return None

    def has_module_path(self, module_name):
        return self._search_for_module(module_name) is not None

    def path_stat_tree(self, path):
        mod_manager = self.module_for_path(path)

        root = mod_manager.get_stat()


    def set_external_path_if_exists(self, imp_ref: ImportReference) -> None:
        ext_path = self.module_path(imp_ref.module)
        if ext_path:
            imp_ref.set_external_path(ext_path)

    def module_for_import(self, imp_ref: ImportReference) -> ModuleManager:

        self.set_external_path_if_exists(imp_ref)
        return self._get_create_mm(imp_ref.path)

    def git_file_for_path(self, path: str) -> Optional[File]:
        log = self.logger("git_file_for_path")
        log.v(f"{path}")
        git_key = None
        git_path = None
        for key, repo_paths in self._module_map.items():
            this_path = str(Path(repo_paths.common_root, repo_paths.git_path))
            # log.d(f"This path: {this_path}")
            # log.d(f"Git  path: {path}")
            # log.d(f"?in      : {this_path in path}")
            if this_path in path:
                # log.d(f"Found git key: {key}")
                git_key = key
                git_path = this_path

        if git_key:
            git_repo = self.git_helpers[git_key]
            internal_path = path.replace(git_path, '')
            # log.d(f"Internal path: {internal_path}")
            return git_repo.file_from_path(internal_path)

        return None

    def module_for_path(self, path: str) -> ModuleManager:
        log = self.logger("module_for_path")

        path_wrapper = PythonPathWrapper(path)
        ext_path = self.module_path(path_wrapper.module_guess)

        if ext_path:
            log.v(f"Swapping path {path_wrapper} -> {ext_path} ")
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