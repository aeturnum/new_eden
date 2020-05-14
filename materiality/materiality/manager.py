from os.path import join
from os import getcwd, listdir
import findimports
from importlib.util import find_spec
from imp import find_module
from sys import path

from pydriller import RepositoryMining
# from modulefinder import ModuleFinder
from pydeps import pydeps
from pydeps.py2depgraph import py2dep
from pydeps.target import Target


from .utils import Logger
from .module_crawler import ModuleCrawler
from .tracking import File, Change, Author


class DependencyFinder(Logger):
    def __init__(self, base, **kwargs):
        super().__init__(**kwargs)
        self.base = base

    def crawl_file(self, file_name):
        for commit in RepositoryMining(self.base, filepath=file_name).traverse_commits():
            # author = Author.find_author(commit.author)
            for m in commit.modifications:
                f = File.get_file(m)
                # if m.new_path == file_name:
                f.add_change(Change.from_commit_and_mod(commit, m))
                    # author.add_change(change)

    def crawl_file_modules(self, file_name):
        # print(path)
        # print(find_module("gluon", path))
        # print(find_spec("gluon.widget"))

        mc = ModuleCrawler(join(self.base, file_name))
        # mc.step()
        while not mc.done:
            mc.step()
        #
        # mc.find_roots()
        # mc.step()
        # mc.step()
        # mc.step()
        # print(mc.results)
        # # mf = ModuleFinder()
        # p = join(self.base, file_name)
        # t = Target(join(self.base, file_name))
        # # args = pydeps.cli.parse_args([p, '--no-config', '--noshow', '--include-missing'])
        # # need to include both '--pylib-all', '--pylib' to get python libs
        # args = pydeps.cli.parse_args([p, '--no-config', '--noshow', '--pylib-all', '--pylib'])
        # args.pop('fname')
        # # print(args)
        # # args.update({})
        # print(py2dep(t, **args))
        # print(t.workdir)
        # print(getcwd())
        # print(listdir(getcwd()))
        # # mf.run_script()
        # # module_names = {k:"" for k in mf.modules["__main__"].globalnames.keys()}
        # # print(module_names)
        # # for path, mod in mf.modules.items():
        # #     if path == "__main__":
        # #         print(f'{path}: {", ".join([gn for gn in mod.globalnames.keys()])}')
        #     # import pudb.b
        # # mf.report()

    def crawl_repo(self):
        for commit in RepositoryMining(self.base).traverse_commits():
            for m in commit.modifications:
                f = File.get_file(m)
                f.add_change(Change.from_commit_and_mod(commit, m))

    @property
    def file_list(self):
        return File.files.values()

    @property
    def author_list(self):
        return Author.authors
