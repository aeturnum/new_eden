from pydriller import RepositoryMining

from .utils import Logger
from .tracking import Author, Change

class Crawler(Logger):

    def __init__(self, base, **kwargs):
        super().__init__(**kwargs)
        self.base = base

    def crawl_file(self, file_name):
        for commit in RepositoryMining(self.base, filepath=file_name).traverse_commits():
            author = Author.find_author(commit.author)
            for m in commit.modifications:
                if (m.new_path == file_name):
                    change = Change.from_commit_and_mod(commit, m)
                    author.add_change(change)
    @property
    def authors(self):
        return Author.authors