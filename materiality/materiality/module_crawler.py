from pathlib import Path, WindowsPath, PosixPath
import json
from importlib.util import find_spec

import os
from os import getcwd, listdir, remove
from os.path import join, splitext
from typing import Mapping, Set, List

from pydeps.target import Target
from pydeps import pydeps
from pydeps.py2depgraph import py2dep

from .utils import Logger
from findimports import find_imports, ImportInfo, ModuleGraph

# because Path does subclassing v weird

# class PosixPathWrapper(PosixPath):
#     def _init(self, is_none):
#         self._none = is_none
#
#     @property
#     def python_file(self):
#         if self._none:
#             # none paths are not python files
#             return False
#         return self.suffix in ['.py', 'pyc']
#
# class WindowsPathWrapper(WindowsPath):
#     def _init(self, is_none):
#         self._none = is_none
#
#     @property
#     def python_file(self):
#         if self._none:
#             # none paths are not python files
#             return False
#         return self.suffix in ['.py', 'pyc']
#
# class PathWrapper(Path):
#
#     def __new__(cls, *args, **kwargs):
#         none = False
#         if args[0] is None:
#             args = list(args)
#             args[0] = ""  # keep Path happy
#             none = True
#
#         if cls is PathWrapper:
#             cls = WindowsPathWrapper if os.name == 'nt' else PosixPathWrapper
#         self = cls._from_parts(args, init=False)
#         if not self._flavour.is_supported:
#             raise NotImplementedError("cannot instantiate %r on your system"
#                                       % (cls.__name__,))
#         self._init(none)
#         return self

class PathWrapper(str):

    @property
    def python_file(self):
        return splitext(self)[1] in ['.py', '.pyc']

class ModuleListingWrapper(Logger):
    _NAME = 'ModuleListingWrapper'

    def __init__(self, value_dict, **kwargs):
        super().__init__(**kwargs)
        # strings
        self.imports: List[str]  = value_dict.get('imports', [])
        # strings
        self.imported_by: List[str] = value_dict.get('imported_by', [])
        self.name: str = value_dict.get('name')
        path = value_dict.get('path', None)
        if path is None:
            self.elog('__init__', f'Path is None! args:{value_dict}')

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

        self.dlog('__init__', f'Creating {self.name}({id(self)})!')

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
        self.module_map: Mapping[str, ModuleListingWrapper] = {}
        # self.path_map: Mapping[str, ModuleListingWrapper] = {}
        self.paths_checked: Set[str] = set()
        self.modules_checked: Set[str] = set()
        self.next_paths: Set[str] = {target}

    @property
    def done(self):
        return len(self.next_paths) == 0

    def step(self):
        if not self.has_new_results:
            # do the thing
            root = self._generate_modules_for_target()
            self._check_modules_for_one_targer(root)
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


    def _make_args(self, target):
        a = [target] # have a path to keep arg parse happy
        # use class args
        a.extend(self.ARGS)
        a = pydeps.cli.parse_args(a)
        # get rid of name because we're going to use the target object
        a.pop('fname')
        return a

    def _call_py2deps(self, target):
        dlog = self.gen_dlog('_call_py2deps')
        # wlog = self.gen_wlog('_call_py2deps')

        dlog(f"Calling py2deps on {target}")
        raw_results = py2dep(Target(target), **self._make_args(target))

        # turn into my structure
        # todo: this isn't actually correct but it's very easy
        return {
            'root': {self._ROOT_MODULE},
            'modules': json.loads(repr(raw_results))
        }

    def _call_findimports(self, target):
        dlog = self.gen_dlog('_call_findimports')

        dlog(f"Calling find_imports on {target}")
        imps: List[ImportInfo] = find_imports(target)
        print(imps)

        mg = ModuleGraph()
        mg.parseFile(target)
        if len(mg.modules.keys()) != 1:
            msg = f"Multiple modules in {target}!: {mg.modules}"
            self.elog('_call_findimports', msg)
            # stop everything
            raise Exception(msg)

        key = next(iter(mg.modules.keys()))
        base_module = mg.modules[key]
        # transform into something
        result = {}

        result[key] = {
            'name': base_module.modname,
            # base_module.imports should include the proper list, but it doesn't - it includes absolutes
            'imports': [i.name for i in imps],
            'path': base_module.filename,
            'imported_by': []
        }
        from multiprocessing import freeze_support
        for i in imps:
            spec = find_spec(i.name)
            if spec:
                print(spec.origin)
            else:
                print(f"Could not find spec for {i}")
            result[i.name] = {
                'imports': [],
                'impored_by': [],
                'name': i.name,
                'path': None
            }
        print(result)

        return {
            'root': {base_module.modname},
            'modules': result
        }

    def _generate_modules_for_target(self):
        # dlog = self.gen_dlog('_gen_mods_for_n_target')
        wlog = self.gen_wlog('_gen_mods_for_n_target')

        target = self.next_paths.pop()
        # raw_modules = self._call_findimports(target)
        # module_paths = self._call_py2deps(target)
        #
        # for module in raw_modules["modules"].values():
        #     wlog(f'{module["path"]}')
        #     wlog(f'{module_paths["modules"]}')
        #     wlog(f'Swapping path from {module["path"]} -> {module_paths["modules"][module["name"]]}')
        #     module['path'] = module_paths['modules'][module['name']]

        raw_modules = self._call_findimports(target)
        print(raw_modules)

        # bookkeeping
        self.paths_checked.add(target)

        for key, val in raw_modules['modules'].items():
            w = ModuleListingWrapper(val)

            if key in self.module_map and not w.temporary:  # already exists, or replace previous temp module
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
                self.module_map[key] = w

        return raw_modules['root']


    def _check_modules_for_one_targer(self, modules):
        dlog = self.gen_dlog('_call_py2dep')
        wlog = self.gen_wlog('_call_py2dep')


        # target = self.next_paths.pop()
        # dlog(f"Calling py2deps on {target}")
        # raw_results = py2dep(Target(target), **self._make_args(target))
        #
        # # bookkeeping
        # self.paths_checked.add(target)
        #
        # # turn into my structure
        # # todo: this isn't actually correct but it's very easy
        # raw_results = json.loads(repr(raw_results))
        #
        # for key, val in raw_results.items():
        #     w = ModuleListingWrapper(val)
        #
        #     if key in self.module_map and not w.temporary: # already exists, or replace previous temp module
        #         if w.path == target:
        #             '''
        #             py2dep notices more dependencies when you crawl the file specifically. This is fine because we add
        #             secondary requirements to the file list after we scan the first file, but we need to update the module
        #             map and also update any existing chilren!
        #             '''
        #             wlog(f"\tUpdating {self.module_map[key].short_str()} -> {w.short_str()}")
        #             self.module_map[key] = w
        #             for v in self.module_map.values():
        #                 v.update_children(w)
        #         else:
        #             wlog(f"\tNot saving <{w.short_str()}>")
        #     else:
        #         self.module_map[key] = w

        modules_checked = set()
        # modules = {self._ROOT_MODULE}  # generally a stub file created by py2dep
        while len(modules) > 0:
            module_name = modules.pop()
            current_module = self.module_map.get(module_name)
            wlog(f'Checking <{current_module.name}>')

            # don't repeat these either
            modules_checked.add(current_module.name)

            for imp in current_module.imports:
                import_module = self.module_map[imp]

                # don't inspect the imports of implicit modules
                if not import_module.implicit and import_module.name not in modules_checked:
                    wlog(f'\tAdding <{import_module.name}> to list of imports to check')
                    modules.add(import_module.name)
                    # otherwise
                    if not current_module.temporary:
                        wlog(f'\t\tAdding {import_module.short_str()} to children of {current_module.short_str()}')
                        current_module.children.append(import_module)
                else:
                    wlog(f'\tNot checking imports of <{import_module.name}> - Implicit')

                if import_module.path and\
                        import_module.path.python_file and\
                        import_module.path not in self.paths_checked:
                    # don't double-check paths
                    if not import_module.implicit:
                        wlog(f'\tAdding [{import_module.path}] to [FILES]')
                        self.next_paths.add(import_module.path)
                    else:
                        wlog(f'\tNot adding [{import_module.path}] to [FILES]: Implicit import')
                else:
                    reason = 'Already crawled'
                    if import_module.path is None:
                        reason = f'Path is None: {import_module}'
                    if not import_module.path.python_file:
                        reason =f'Not a python file: {import_module}'
                    wlog(f'\tNot adding [{import_module.path}] to [FILES]: {reason}')


            wlog(f'Round Complete!')
            wlog(f'\tProcessed: {current_module}')
            wlog(f'\t<modules>:{modules}')
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
