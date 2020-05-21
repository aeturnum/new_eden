
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

    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.path_to_module: Dict[str, ModuleManager] = {}
        self._shadow_paths: Dict[str, ModuleManager] =  {}
        self.module_name_to_module: Dict[str, ModuleManager] = {}

    def _get_real_path(self, module_name: str) -> Optional[str]:
        if module_name in self._git_repos:
            return self._git_repos[module_name]

        return None

    def _resolve_relative_import_path(self, imp_ref: ImportReference):
        ppw = PythonPathWrapper(imp_ref.statement_file_path)
        ppw.find_relative_import(imp_ref.level, imp_ref.module)
        # todo: this doesn't fully solve the problem, because we still use find_spec to search
        # todo: for the module name
        # todo: maybe we should filter path names when we're creating ModuleManagers
        imp_ref.resolve(ppw)

    def _get_real_manager(self, module_manager: ModuleManager) -> ModuleManager:
        real_path = self._get_real_path(module_manager.module)

        if real_path:
            # we have a git repo here somewhere
            module_manager = ModuleManager(real_path)
            self._shadow_paths[real_path] = module_manager

        return module_manager


    def module_for_path(self, path: str) -> ModuleManager:

        if path not in self.path_to_module:
            new_module = self._get_real_manager(ModuleManager(path))
            self.path_to_module[path] = new_module
            self.module_name_to_module[new_module.module] = new_module

        return self.path_to_module[path]

    def resolve_import(self, imp_ref: ImportReference):
        log = self.logger("resolve_import")
        log.v(f"{imp_ref}")
        if imp_ref.needs_resolution:
            if imp_ref.relative:
                self._resolve_relative_import_path(imp_ref)
            else:
                imp_ref.resolve()
                # imp_ref.resolve(
                #     PythonPathWrapper(self._get_real_path(imp_ref.module))
                # )


        return imp_ref

    def __str__(self):
        lines = []
        for p, m in self.path_to_module.items():

            lines.append(f"<{p}>\n{self.indent(m.symbols)}")

        return f'<PathManager>\n{self.indent(lines)}'