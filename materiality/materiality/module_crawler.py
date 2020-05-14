# from pathlib import Path, WindowsPath, PosixPath
# import json
# from importlib.util import find_spec
# from importlib.machinery import BuiltinImporter
# import sys
import ast
# from copy import deepcopy, copy
# from itertools import chain

# import os
from os import getcwd, listdir, remove
from os.path import join, splitext
from typing import Mapping, Set, List, Optional, Dict, Any

# from pydeps.target import Target
# from pydeps import pydeps
# from pydeps.py2depgraph import py2dep

from .utils import Logger
from .ast_crawler import ImportContext, ASTWrapper
from findimports import find_imports, ImportInfo, ModuleGraph

class PathWrapper(str):

    @property
    def python_file(self):
        return splitext(self)[1] in ['.py', '.pyc']

class ModuleListingWrapper(Logger):
    _NAME = 'ModuleListingWrapper'

    def __init__(self, value_dict, **kwargs):
        super().__init__(**kwargs)
        # strings
        self.imports: List[ImportContext]  = value_dict.get('imports', [])
        # strings
        self.imported_by: List[str] = value_dict.get('imported_by', [])
        self.name: str = value_dict.get('name')
        self.error: str = value_dict.get('error', None)
        self.path = None

        path = value_dict.get('path', None)
        if path is None and not self.error:
            self.elog('__init__', f'Path is None! args:{value_dict}')

        # if self.error is not None:
        #     self.wlog("__init__", f'{self.name}[ERROR] -> {self.error}')

        if path:
            self.path: PathWrapper = PathWrapper(path)

        # wrappers
        self.children: List[ModuleListingWrapper] = []

        self.implicit = False
        for imp in self.imported_by:
            # TODO: Check if this is correct
            '''
            So this is the plan here:
            If you import X.Y, Python needs to import X as well. This is (I think) because module imports have side
            effects. But the important thing to note is that module X doesn't get pulled into scope (I think). It's just
            module X.Y. So - we try to use this flag
            '''
            if self._is_submodule(imp):
                self.implicit = True

        # self.dlog('__init__', f'Creating {self.name}({id(self)})!')

    def fetch_imports(self):
        self.dlog("fetch_imports", f"({self.path})")
        if self.error:
            self.wlog("fetch_imports", f'\t-Skipping imports for {self.name} because of error: "{self.error}".')
            return

        if not self.path:
            self.wlog("fetch_imports", f'\t-Skipping imports for {self.name} path is none.')
            return

        print(f'{self} - {self.path}({type(self.path)})')
        with open(self.path, "rt") as file:
            st: ast.AST = ast.parse(file.read(), filename=self.path)
            wrap = ASTWrapper(st)
            self.imports = wrap.imports_for_symbol()
            self.dlog("fetch_imports", "->[\n\t{}\n\t]".format(
                '\n\t'.join([str(i) for i in self.imports])
            ))


    @property
    def import_names(self):
        return [name for i in self.imports for name in i.names]

    @property
    def is_imported(self):
        return len(self.imported_by) > 0

    @property
    def decendant_count(self):
        count = len(self.children)
        for c in self.children:
            try:
                count += c.decendant_count
            except RecursionError as re:
                print(f'decendant_count:{self.name}[{self.path}] - Recursion error on child: {c.name}[{c.path}]!')
                raise

        return count

    @property
    def temporary(self):
        return self.name == "__main__"

    def update_children(self, new_child):
        # update any references
        self.children = [
            new_child if new_child.name == c.name else c for c in self.children
        ]

    def get_children(self):
        # gets a flattened list
        children = set(self.children)
        for c in self.children:
            try:
                children.update(c.get_children())
            except RecursionError as re:
                print(f'get_children:{self.short_str()} - Recursion error on child: {c.short_str()}!')
                raise

        return children

    def print_children(self, level = 0):
        if level == 0:
            print(f'{self.short_str()}')
        else:
            spacers =  '     ' * (level - 1) + '|--'
            print(f'{spacers}> {self.short_str()}')

        for c in self.children[:-1]:
            c.print_children(level = level + 1)

        if len(self.children) >= 1:
            self.children[-1].print_children(level=level + 1)

    def _is_submodule(self, name: str):
        return name.startswith(self.name)

    def _str_comps(self, short=False):
        path = self.path or 'X'
        imports = ''
        import_by = ''
        impl = ''
        temp = ''
        if self.implicit:
            impl = '(IMPL)'
        if self.imports:
            if short:
                imports = f'I<{len(self.imports)}'
            else:
                imports = f'I<{self.imports}'
        if self.is_imported:
            if short:
                import_by = f'|(I)>{len(self.imported_by)}'
            else:
                import_by = f'|(I)>{self.imported_by}'
        if self.temporary:
            temp = 'T|'

        return {
            'id': id(self),
            'path': path,
            'imports': imports,
            'import_by': import_by,
            'impl': impl,
            'temp': temp
        }

    def short_str(self):
        components = self._str_comps(short=True)
        return ''.join([
            '[',
            f'{components["temp"]}({self.decendant_count})',
            f'{self.name}{components["impl"]}',
            '|',
                f'{components["path"]}] {components["imports"]}{components["import_by"]}'
        ])

    def __str__(self):
        components = self._str_comps()
        return ''.join([
            '[',
                f'{components["temp"]}({self.decendant_count})',
                f'{self.name}{components["impl"]}',
                    '|',
                    f'{components["path"]}] {components["imports"]}{components["import_by"]}'
            ])

    def __repr__(self):
        return str(self)

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
        self.module_map: Dict[str, ModuleListingWrapper] = {}
        self.path_map: Dict[str, ModuleListingWrapper] = {}
        self.paths_checked: Set[str] = set()
        self.modules_checked: Set[str] = set()
        self.next_paths: Set[str] = {target}

    @property
    def done(self):
        return len(self.next_paths) == 0

    def step(self):
        if not self.has_new_results:
            # do the thing
            target = self.next_paths.pop()
            self._generate_modules_for_target(target)
            self._check_modules_for_one_target(target)
            # cleanup
            self._cleanup()
            self.has_results = True

    def find_roots(self):
        # set of module objects
        mods: Set[ModuleListingWrapper] = set([v for v in self.module_map.values()])
        while len(mods) > 0:
            highest = sorted(mods, reverse=True, key=lambda x: x.decendant_count)[0]
            to_remove = highest.get_children()
            if not highest.temporary:
                print("Root:")
                highest.print_children()

            # gotta add the one we just printed
            to_remove.add(highest)
            mods = mods - to_remove

    def _call_findimports(self, target):
        dlog = self.gen_dlog('_call_findimports')

        dlog(f"Calling find_imports on {target}")

        result = {}
        key = None

        if target in self.path_map:
            item = self.path_map[target]
            key = item.name
            if not item.imports:
                item.fetch_imports()

            result[key] = item
        else:
            mg = ModuleGraph()
            mg.parseFile(target)


            key = next(iter(mg.modules.keys()))
            base_module = mg.modules[key]

            module_info = {
                'name': base_module.modname,
                # base_module.imports should include the proper list, but it doesn't - it includes absolutes
                # https://stackoverflow.com/questions/952914/how-to-make-a-flat-list-out-of-list-of-lists
                # this is actually 99% impossible to read but it is proper python lol
                # for i in imps, for each name in i.names, add name to list
                # 'imports': [name for i in imps for name in i.names],
                'error': None,
                'path': target,
                'imported_by': []
            }
            result[key] = ModuleListingWrapper(module_info)
            result[key].fetch_imports()

        for i in result[key].imports:
            print(i)
            for full_path, spec in i.specs.items():

                # this will be
                imp_mod_info = {
                    'impored_by': [],
                    'error': spec.error,
                    'name': spec.name,
                    'path': spec.origin or None
                }
                if spec.name not in result:
                    result[spec.name] = ModuleListingWrapper(imp_mod_info)
                    result[spec.name].fetch_imports()

        return {
            'root': {key},
            'modules': result
        }

    def _generate_modules_for_target(self, target):
        dlog = self.gen_dlog('_gen_mods_for_n_target')
        wlog = self.gen_wlog('_gen_mods_for_n_target')

        # target = self.next_paths.pop()

        raw_modules = self._call_findimports(target)
        # print(raw_modules)

        # bookkeeping
        # todo: do this somewhere else?
        self.paths_checked.add(target)

        for key, val in raw_modules['modules'].items():
            # w = ModuleListingWrapper(val) # no need, did in previous step now
            w = val

            if key in self.module_map and not w.temporary:  # already exists, or replace previous temp module
                # Sometimes replace modules we'e already seen under certain conditions
                # todo: check if this should still happen
                if w.path == target:
                    '''
                    py2dep notices more dependencies when you crawl the file specifically. This is fine because we add
                    secondary requirements to the file list after we scan the first file, but we need to update the module
                    map and also update any existing chilren!
                    '''
                    wlog(f"\tUpdating {self.module_map[key].short_str()} -> {w.short_str()}")
                    self.module_map[key] = w
                    for v in self.module_map.values():
                        v.update_children(w)
                else:
                    wlog(f"\tNot saving <{w.short_str()}>")
            else:
                dlog(f"\tAdding '{key}' to module_map")
                self.module_map[key] = w
                if w.path:
                    self.path_map[w.path] = w

        return raw_modules['root']

    def _check_modules_for_one_target(self, target):
        dlog = self.gen_dlog('_call_py2dep')
        wlog = self.gen_wlog('_call_py2dep')

        modules_checked = set()
        # modules = {self._ROOT_MODULE}  # generally a stub file created by py2dep

        current_module = self.path_map.get(target)

        # don't repeat these either
        modules_checked.add(current_module.name)
        if current_module.error:
            wlog(f'Skipping <{current_module.name}>: {current_module.error}')
        else:
            wlog(f'Checking <{current_module.name}>')

            # remember to itterate over names here
            for imp in current_module.import_names:
                if imp not in self.module_map:
                    wlog(f'\tModule "{imp}" not found in module map!')
                    continue
                import_module = self.module_map[imp]


                if import_module.error:
                    wlog(f'\t-Not checking <{import_module.name}> - Error: {import_module.error}')
                    continue
                # don't inspect the imports of implicit modules


                if import_module.name not in modules_checked:
                    if not import_module.implicit:
                        # wlog(f'\t+Adding <{import_module.name}> to list of imports to check')
                        # modules.add(import_module.name)
                        # otherwise
                        if not current_module.temporary:
                            wlog(f'\t\t+Adding {import_module.short_str()} to children of {current_module.short_str()}')
                            current_module.children.append(import_module)
                    else:
                        wlog(f'\t-Not checking imports of <{import_module.name}> - Implicit')
                else:
                    wlog(f'\t-Not checking imports of <{import_module.name}> - Already checked')


                if import_module.path and import_module.path.python_file and\
                        import_module.path not in self.paths_checked:
                    # don't double-check paths
                    if not import_module.implicit:
                        wlog(f'\t++Adding [{import_module.path}] to [FILES]')
                        self.next_paths.add(import_module.path)
                    else:
                        wlog(f'\t--Not adding [{import_module.path}] to [FILES]: Implicit import')
                else:
                    reason = 'Already crawled'
                    if import_module.path is None:
                        reason = f'Path is None: {import_module}'
                    elif not import_module.path.python_file:
                        reason =f'Not a python file: {import_module}'
                    wlog(f'\t--Not adding [{import_module.path}] to [FILES]: {reason}')


        wlog(f'Round Complete!')
        wlog(f'\tProcessed: {current_module}')
        # wlog(f'\t<modules>:{modules}')
        formatted_paths = ""
        # print(self.next_paths)
        if self.next_paths:
            formatted_paths = "\n\t".join([p for p in self.next_paths])
        wlog(f'\t[FILES]:{formatted_paths}')
        all_modules = ""
        if self.module_map:
            all_modules ="[\n\t\t" +  "\n\t\t".join([f"{v.short_str()}" for v in self.module_map.values()]) +"\n]"
        wlog(f'\tAll Modules: {all_modules}')

    def _cleanup(self):
        base = getcwd()
        files = listdir(base)
        for f in ModuleCrawler._Cleanup_Filters:
            files = filter(f, files)

        for f in files:
            # remove files from filters
            remove(join(base, f))
