from os import getcwd, listdir, remove
from os.path import join, splitext
from typing import Mapping, Set, List, Optional, Dict, Any, Union
from collections import namedtuple

from .utils import Logger
from .ast_crawler import ImportReference, ModuleManager
from .path_manager import PathManager

class StatTree(Logger):

    _NAME = "StatCrawler"
    _StatNode = namedtuple('StatNode', ['stats', 'children'])

    def __init__(self, path_manager: PathManager, **kwargs):
        super().__init__(**kwargs)

        self.pm = path_manager
        self.tree = None
        self.base_path = None
        self.visited = set()

    def fill_for_file(self, path):
        if self.base_path != None:
            raise ValueError("This Tree is already full!")

        mod_manager = self.pm.module_for_path(path)
        self.tree = self._fill_tree_node([], mod_manager)

    def _fill_tree_node(self, chain, mod_manager: ModuleManager, symbol = None):
        log = self.logger("_fill_tree_node")
        # log.d({f"{chain}<-{mod_manager.module}.{symbol}"})
        indent = "  " * len(chain)
        visit_key = mod_manager.module
        if symbol:
            visit_key = f'{visit_key}.{symbol}'
        if visit_key in self.visited:
            log.w(f"{indent}Appear to be visiting {visit_key} twice - skipping. Chain: {chain}")
            log.w(f"{indent}{visit_key} imports:")
            for i in mod_manager.get_stat(symbol).links:
                log.w(f"{indent}{i}")
            return f"Ignoring: {visit_key}"

        # avoid infinite recursion
        self.visited.add(visit_key)

        stat = mod_manager.get_stat(symbol)

        # log.d("{}:\n{}".format(
        #     visit_key,
        #     self.indent("\n".join([str(l) for l in stat.links]))
        # ))
        log.d(f"{indent}{visit_key}")

        children = []
        for imp_ref in stat.links:
            log.d(f"{indent}]{imp_ref}")
            if imp_ref.being_ignored:
                log.w(f"{indent}-]Ignoring import")
                continue
            if not imp_ref.path:
                log.w(f"{indent}-]Has no path")
                continue

            this_chain = chain + [visit_key]
            this_manager = self.pm.module_for_path(imp_ref.path)
            if imp_ref.symbols:
                for imp_symbol in imp_ref.symbols:
                    children.append(
                        self._fill_tree_node(this_chain, this_manager, imp_symbol)
                    )
            else:
                # no symbol
                children.append(
                    self._fill_tree_node(this_chain, this_manager)
                )

        return self._StatNode(stat, children)

    def _level_str(self, node: Union[_StatNode, str]):
        if isinstance(node, str):
            return node
        children_string = "\n".join([self._level_str(c) for c in node.children])
        return '{}\n{}'.format(
            str(node.stats),
            self.indent(children_string)
        )

    def report(self):
        return self._level_str(self.tree)


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

    def get_import_tree_for_file(self, path):
        st = StatTree(self.pm)
        st.fill_for_file(path)

        return st

    def _check_modules_for_target(self, target):
        log = self.logger("_check_modules_for_target")
        log.v(f"{target}")

        mod_manage = self.pm.module_for_path(target)

        self.paths_checked.add(target)

        for imp in mod_manage.imports:
            self.pm.set_external_path_if_exists(imp)
            # self.pm.resolve_import(imp)

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
