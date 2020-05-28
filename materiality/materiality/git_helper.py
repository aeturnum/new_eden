

from pydriller import RepositoryMining, Commit

from .utils import Logger
from .tracking import File, Change, Author

class GitHelper(Logger):
    _name = 'GitHelper'

    def __init__(self, directory, **kwargs):
        super().__init__(**kwargs)
        self.root = directory
        self.repo_miner = RepositoryMining(self.root)
        self.indexed = False

        self.file_index = {}
        self.author_index = []

    def get_file(self, modification):
        path = modification.new_path
        if path is None:  # file deleted, use old path
            path = modification.old_path

        if path not in self.file_index:
            self.file_index[path] = File(path)

        return self.file_index[path]

    def find_author(self, commit_author):
        log = self.logger("find_author")
        # log.d(f'({commit_author.name, commit_author.email})')
        for a in self.author_index:
            if a.name == commit_author.name or a.email == commit_author.email:
                if commit_author.name not in a.names or commit_author.email not in a.email:
                    if commit_author.name not in a.names:
                        log.w(f'incomplete match[name] {commit_author.name} not in {a.names} ')
                    if commit_author.email not in a.emails:
                        log.w(f'incomplete match[email] {commit_author.email} not in {a.emails}')
                # log.d(f'found: {a}')
                a.merge(commit_author)
                return a

        return Author(commit_author.name, commit_author.email, index=self.author_index)

    def index(self):
        if not self.indexed:
            for commit in self.repo_miner.traverse_commits():
                for m in commit.modifications:
                    f = self.get_file(m)
                    c = Change.from_commit_and_mod(commit, m)
                    c.get_author_from_index(self)
                    f.add_change(c)

            self.indexed = True



class GitFile(Logger):
    _name = 'GitHelper'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
