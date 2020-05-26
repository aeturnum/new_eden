from os.path import join

from pydriller import RepositoryMining


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
        mc = ModuleCrawler(join(self.base, file_name))

        while not mc.done:
            mc.step()



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
