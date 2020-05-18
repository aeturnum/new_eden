from os import getcwd, listdir, remove
from os.path import join, splitext
from typing import Mapping, Set, List, Optional, Dict, Any

from .utils import Logger
from .ast_crawler import ImportStatement, ASTWrapper, ImportReference, ast_wrapper_for_file
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

class ModuleListingWrapper(Logger):
    """
    Wrapper to manage import links

    The problem that I need to address next is that there's no difference between two different kinds of imports:
        - import X
        - from X import Y
    In the graph represented by ModuleListingWrapper.
    The SpecWrappers can differentiate between them and the ASTWrappers' symbol tables should be useful here, and is
    probably what I need in order to avoid cycles in the import graph.

    The other option is that I change the system so that I'm using different systems to track:
        - Which files I have scanned and which imports they contain
        - The Import graph

    """
    _NAME = 'ModuleListingWrapper'

    def __init__(self, import_ref, **kwargs):
        super().__init__(**kwargs)
        log = self.logger("__init__")

        # strings
        self.imports: List[ImportStatement] = []
        # strings
        self.imported_by: List[str] = []
        self.spec: ImportReference = import_ref
        # self.name: str = value_dict.get('name')
        # self.ignore_reason: str = value_dict.get('ignore_reason', None)
        self.path = None

        path = import_ref.origin
        if path == "built-in":
            path = None

        if path is None and not self.ignore_reason:
            log.e(f'Path is None! args:{import_ref}')

        # if self.error is not None:
        #     self.wlog(f'{self.name}[ERROR] -> {self.error}')

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

        # self.dlog(f'Creating {self.name}({id(self)})!')

    @property
    def name(self):
        return self.spec.module

    @property
    def ignore_reason(self):
        return self.spec.ignore_reason

    def fetch_imports(self):
        log = self.logger("fetch_imports")
        log.d(f"{self.path}")

        if self.ignore_reason:
            log.d(f'-Ignoring {self.name}: "{self.ignore_reason}".')
            return

        if not self.path:
            log.d(f'-Skipping imports for {self.name} path is none.')
            return

        wrap = ast_wrapper_for_file(self.path)
        self.imports = wrap.imports_for_symbol()
        log.d("->[\n\t{}\n\t]".format(
            '\n\t'.join([str(i) for i in self.imports])
        ))


    @property
    def import_names(self):
        return [ref.module for i in self.imports for ref in i.references]

    @property
    def is_imported(self):
        return len(self.imported_by) > 0

    @property
    def decendant_count(self):
        count = len(self.children)
        # for c in self.children:
        #     try:
        #         count += c.decendant_count
        #     except RecursionError as re:
        #         print(f'decendant_count:{self.name}[{self.path}] - Recursion error on child: {c.name}[{c.path}]!')
        #         raise

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
        log = self.logger("get_children")
        children = set(self.children)
        for c in self.children:
            try:
                children.update(c.get_children())
            except RecursionError as re:
                log.e(f'{self.short_str()} - Recursion error on child: {c.short_str()}!')
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
        if self.ignore_reason:
            path = self.ignore_reason
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
        self.has_results = False

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
                # print("Root:")
                highest.print_children()

            # gotta add the one we just printed
            to_remove.add(highest)
            mods = mods - to_remove

    def _call_findimports(self, target):
        log = self.logger("_call_findimports")

        log.v(f"Calling find_imports on {target}")

        result = {}
        key = None

        if target in self.path_map:
            item = self.path_map[target]
            log.v(f"Found previously existing object: {item}")
            key = item.name
            if not item.imports:
                item.fetch_imports()

            result[key] = item
        else:
            log.v(f"Using module graph")
            mg = ModuleGraph()
            mg.parseFile(target)

            key = next(iter(mg.modules.keys()))
            base_module = mg.modules[key]

            spec = FakeSpec(base_module.modname, target)
            result[key] = ModuleListingWrapper(spec)
            result[key].fetch_imports()

        for i in result[key].imports:
            for import_ref in i.references:

                if import_ref.name not in result:
                    result[import_ref.name] = ModuleListingWrapper(import_ref)
                    result[import_ref.name].fetch_imports()

        return {
            'root': {key},
            'modules': result
        }

    def _generate_modules_for_target(self, target):
        log = self.logger("_gen_mods_for_n_target")
        log.v(f"{target}")

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
                    log.w(f"Updating {self.module_map[key].short_str()} -> {w.short_str()}")
                    self.module_map[key] = w
                    for v in self.module_map.values():
                        v.update_children(w)
                else:
                    log.w(f"Not saving <{w.short_str()}>")
            else:
                log.d(f"Adding '{key}' to module_map")
                self.module_map[key] = w
                if w.path:
                    self.path_map[w.path] = w

        return raw_modules['root']

    def _check_modules_for_one_target(self, target):
        log = self.logger("_check_modules_for_one_target")
        log.v(f"{target}")

        modules_checked = set()
        # modules = {self._ROOT_MODULE}  # generally a stub file created by py2dep

        current_module = self.path_map.get(target)

        # don't repeat these either
        modules_checked.add(current_module.name)
        if current_module.ignore_reason:
            log.w(f'Skipping <{current_module.name}>: {current_module.ignore_reason}')
        else:
            log.d(f'Checking <{current_module.name}>')

            # remember to itterate over names here
            for imp in current_module.import_names:
                if imp not in self.module_map:
                    log.w(f'\tModule "{imp}" not found in module map!')
                    continue
                import_module = self.module_map[imp]


                if import_module.ignore_reason:
                    log.w(f'\t-Ignoring <{import_module.name}>: {import_module.ignore_reason}')
                    continue
                # don't inspect the imports of implicit modules


                if import_module.name not in modules_checked:
                    if not import_module.implicit:
                        # wlog(f'\t+Adding <{import_module.name}> to list of imports to check')
                        # modules.add(import_module.name)
                        # otherwise
                        if not current_module.temporary:
                            log.d(f'\t\t+Adding {import_module.short_str()} to children of {current_module.short_str()}')
                            current_module.children.append(import_module)
                    else:
                        log.d(f'\t-Not checking imports of <{import_module.name}> - Implicit')
                else:
                    log.d(f'\t-Not checking imports of <{import_module.name}> - Already checked')


                if import_module.path and import_module.path.python_file and\
                        import_module.path not in self.paths_checked:
                    # don't double-check paths
                    if not import_module.implicit:
                        log.d(f'\t++Adding [{import_module.path}] to [FILES]')
                        self.next_paths.add(import_module.path)
                    else:
                        log.d(f'\t--Not adding [{import_module.path}] to [FILES]: Implicit import')
                else:
                    reason = 'Already crawled'
                    if import_module.path is None:
                        reason = f'Path is None: {import_module}'
                    elif not import_module.path.python_file:
                        reason =f'Not a python file: {import_module}'
                    log.d(f'\t--Not adding [{import_module.path}] to [FILES]: {reason}')


        log.d(f'Round Complete!')
        log.d(f'\tProcessed: {current_module}')
        # wlog(f'\t<modules>:{modules}')
        formatted_paths = ""
        # print(self.next_paths)
        if self.next_paths:
            formatted_paths = "\n\t".join([p for p in self.next_paths])
        log.d(f'\t[FILES]:{formatted_paths}')
        all_modules = ""
        if self.module_map:
            all_modules ="[\n\t\t" +  "\n\t\t".join([f"{v.short_str()}" for v in self.module_map.values()]) +"\n]"
        log.d(f'\tAll Modules: {all_modules}')

    def _cleanup(self):
        base = getcwd()
        files = listdir(base)
        for f in ModuleCrawler._Cleanup_Filters:
            files = filter(f, files)

        for f in files:
            # remove files from filters
            remove(join(base, f))
