from os import getcwd, listdir, remove
from os.path import join, splitext
from typing import Mapping, Set, List, Optional, Dict, Any, Union
from collections import namedtuple
import datetime
import csv

from .utils import Logger, td_str
from .tracking import ChangeStats
from .ast_crawler import ImportReference, ModuleManager
from .path_manager import PathManager

class StatTree(Logger):

    _NAME = "StatCrawler"
    _StatNode = namedtuple('StatNode', ['key','path', 'stats', 'git_info', 'children'])

    def __init__(self, path_manager: PathManager, **kwargs):
        super().__init__(**kwargs)

        self.pm = path_manager
        self.tree = None
        self.base_path = None
        self.visit_counts = {}
        # avoid building the same sub-tree twice
        self.tree_cache = {}

    def fill_for_file(self, path):
        if self.base_path != None:
            raise ValueError("This Tree is already full!")

        mod_manager = self.pm.module_for_path(path)
        self.tree = self._fill_tree_node([], mod_manager)

        # self._check_tree_for_cycles(self.tree)

    def _check_tree_for_cycles(self, top_node: _StatNode, previous_tops: Optional[set] = None):
        """
        I'm doing something wrong here and should go get the algorithm book but that will have to wait I think
        :param top_node:
        :param previous_tops:
        :return:
        """
        log = self.logger("_check_tree_for_cycles")
        log.d(previous_tops)
        if previous_tops and top_node.key in previous_tops:
            raise ValueError(f"Have reached {top_node.key} again! Call chain: {previous_tops}")

        new_top_list = {top_node.key}
        if previous_tops:
            new_top_list = new_top_list.union(previous_tops)

        for c in top_node.children:
            self._check_tree_for_cycles(c, new_top_list)


    def _fill_tree_node(self, chain, mod_manager: ModuleManager, symbol = None):
        log = self.logger("_fill_tree_node")
        # log.d({f"{chain}<-{mod_manager.module}.{symbol}"})
        indent = "  " * len(chain)

        visit_key = mod_manager.module
        # if symbol:
        #     visit_key = f'{visit_key}.{symbol}'

        # if visit_key in self.tree_cache:
        #     log.w(f"{indent}Using cached results for {visit_key}. Chain: {chain}")
        #     return self.tree_cache[visit_key]

        if visit_key in self.visit_counts:
            self.visit_counts[visit_key] += 1
            # log.w(f"{indent}Visit #{self.visit_counts[visit_key]} to {visit_key}  - returning slug to only count stats once. Chain: {chain}")

            # log.w(f"{indent}{visit_key} imports:")
            # for i in mod_manager.get_stat(symbol).links:
            #     log.w(f"{indent}{i}")
            # return f"Visit #{self.visit_counts[visit_key]} to {visit_key}"
            return None

        elif mod_manager.module in self.visit_counts:
            return None

        # avoid infinite recursion
        self.visit_counts[visit_key] = 1
        path = mod_manager.path.str()

        # stat = mod_manager.get_stat(symbol)
        stat = mod_manager.get_stat()
        git_info = self.pm.git_file_for_path(path)

        # log.d("{}:\n{}".format(
        #     visit_key,
        #     self.indent("\n".join([str(l) for l in stat.links]))
        # ))
        # log.d(f"{indent}{visit_key}")

        children = []
        for imp_ref in stat.links:
            # log.d(f"{indent}]{imp_ref}")
            if imp_ref.being_ignored:
                # log.w(f"{indent}-]Ignoring import")
                continue
            if not imp_ref.path:
                # log.w(f"{indent}-]Has no path")
                continue

            this_chain = chain + [visit_key]
            this_manager = self.pm.module_for_path(imp_ref.path)
            if imp_ref.symbols:
                for imp_symbol in imp_ref.symbols:
                    result = self._fill_tree_node(this_chain, this_manager, imp_symbol)
                    if result: # don't append the redundant visits
                        children.append(result)
            else:
                # no symbol
                result = self._fill_tree_node(this_chain, this_manager)
                if result:
                    children.append(result)

        result = self._StatNode(visit_key, path, stat, git_info, children)
        self.tree_cache[visit_key] = result

        return result

    def _level_str(self, node: Union[_StatNode, str]):
        if isinstance(node, str):
            return node
        children_string = "\n".join([self._level_str(c) for c in node.children])
        git_str = ''
        if node.git_info != None:
            git_str = f': {node.git_info}'
        return '{}\n{}'.format(
            f'{node.stats}(+{self.visit_counts[node.key]} repeats){git_str}',
            self.indent(children_string)
        )

    def print_tree(self):
        return self._level_str(self.tree)

    def _collect_authors(self, node: _StatNode):
        authors = set()

        if node.git_info:
            for author in node.git_info.authors:
                authors.add(author)

        for child in node.children:
            authors = authors.union(self._collect_authors(child))

    def _collect_raw_stats(self, node: _StatNode, stats: Optional[dict] = None):
        if not stats:
            stats = {
                'files': 0,
                'lines': 0,
            }

        stats['files'] += 1
        stats['lines'] += node.stats.length

        for child in node.children:
            stats = self._collect_raw_stats(child, stats)

        return stats

    def _collect_git_stats(self, node: _StatNode, stats: Optional[dict] = None):
        if not stats:
            stats = {
                'count': 0,
                'authors': set(),
                'author_changes': {},
                'added': 0,
                'removed': 0,
                'changes': 0,
                'lifetimes': [],
                'ages': []
            }

        if node.git_info:
            # print(f"key: {node.key}, authors: {node.git_info.authors}")
            for author in node.git_info.authors:
                if author not in stats['authors']:
                    stats['authors'].add(author)
                    stats['author_changes'][author] = ChangeStats()

                stats['author_changes'][author] = stats['author_changes'][author] + node.git_info.author_changes[author]


            stats['count'] += 1
            stats['added'] += node.git_info.stats.added
            stats['removed'] += node.git_info.stats.removed
            stats['changes'] += node.git_info.stats.changes

            lifetime = node.git_info.lifetime
            age = node.git_info.age

            if lifetime:
                stats['lifetimes'].append(lifetime)
            if age:
                stats['ages'].append(age)

        for child in node.children:
            stats = self._collect_git_stats(child, stats)

        return stats

    def report(self):
        # authors = self._collect_authors(self.tree)
        git_stats = self._collect_git_stats(self.tree)
        raw_stats = self._collect_raw_stats(self.tree)

        count = 0
        average = datetime.timedelta(0)
        longest = None
        shortest = None
        for td in git_stats['ages']:
            if not longest:
                longest = td
            if not shortest:
                shortest = td
            # print(td_str(td.total_seconds()))
            average += td

            if td > longest:
                longest = td
            if td < shortest:
                shortest = td

            count += 1

        authors = list(git_stats['authors'])
        authors = sorted(authors, reverse=True)
        # for author in authors:
        #     real_stats = git_stats['author_changes'][author]
        #     author.stats = real_stats

        git_percent = (git_stats['count'] / raw_stats['files']) * 100

        related_changes = 0


        with open('authors.csv', 'w', encoding="utf-8") as csvfile:
            authorwriter = csv.writer(csvfile)
            authorwriter.writerow([
                'Repository', 'Top Name', 'Top Email',
                'Related Changes', "Related Additions", "Related Removals", "Related Delta",
                'Total Change', 'Total Additions', 'Total Removals', 'Total Delta'
            ])
            for author in authors:
                total_stats : ChangeStats = author.stats
                related_stats : ChangeStats = git_stats['author_changes'][author]

                related_changes += related_stats.changes

                authorwriter.writerow([
                    author.repo.name, author.name, author.email,
                    related_stats.changes, related_stats.added, related_stats.removed, related_stats.delta,
                    total_stats.changes, total_stats.added, total_stats.removed, total_stats.delta
                ])
                author.stats = related_stats

        work_percent = (related_changes / git_stats["changes"]) * 100
        print(f'----------------------------------')
        print(f'--------------Report--------------')
        print(f'----------------------------------')
        print(f"Total files: {raw_stats['files']}({git_percent:.2f}% in git)")
        print(f"Total lines: {raw_stats['lines']}")
        print(f'----------------------------------')
        print(f'Average age: {td_str(average.total_seconds() / count)}')
        print(f'Shortest age: {td_str(shortest.total_seconds())}')
        print(f'Longest age: {td_str(longest.total_seconds())}')
        print(f'Total number of changes: {related_changes}/{git_stats["changes"]} ({work_percent:.2f})')
        print(f'Authors({len(authors)}):')
        for author in authors:
            print(f' {author}')



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
            # print(self.pm)
            # cleanup
            self._cleanup()
            self.has_results = True

    def get_import_tree_for_file(self, path):
        self.pm.crawl_git_helpers()

        st = StatTree(self.pm)
        st.fill_for_file(path)

        return st

    def report(self):
        return str(self.pm)

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
