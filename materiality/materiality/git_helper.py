import pickle
import sys
from pathlib import Path

from pydriller import RepositoryMining, Commit

from .utils import Logger
from .tracking import File, Change, Author, Repo

class GitHelper(Logger):
    _name = 'GitHelper'

    _FIDX = "file_index"
    _AIDX = "author_index"
    _CMTS = "commits"

    def __init__(self, name, directory, **kwargs):
        super().__init__(**kwargs)
        self.repo: Repo = Repo(name, directory)
        self.repo_miner = RepositoryMining(directory)
        self.indexed = False

        self.file_index = {}
        self.author_index = []
        # self.commits = []
        self._pickle_load()

    def _pickle_name(self, member):
        return str(self.repo.root_directory).replace("/", "_") + f"_{member}"

    def _pickle_load(self):
        log = self.logger("_pickle_load")

        file_pickle = Path("./", self._pickle_name(self._FIDX))
        author_pickle = Path("./", self._pickle_name(self._AIDX))

        if all([file_pickle.exists(), author_pickle.exists()]):
            log.d(f"{self.repo}: Loading pickled state")
            self.file_index = pickle.load(file_pickle.open("rb"))
            self.author_index = pickle.load(author_pickle.open("rb"))
            self.indexed = True
        else:
            log.d(f"{self.repo}: No pickled state to load")


    def _pickle_save(self):
        log = self.logger("_pickle_save")
        sys.setrecursionlimit(10000)
        if self.indexed:
            file_pickle = Path("./", self._pickle_name(self._FIDX))
            author_pickle = Path("./", self._pickle_name(self._AIDX))
            # comment_pickle = Path("./", self._pickle_name(self._CMTS))

            log.d(f"{file_pickle}")
            pickle.dump(self.file_index, file_pickle.open("wb"))
            log.d(f"{file_pickle} - dumped")
            log.d(f"{author_pickle}")
            pickle.dump(self.author_index, author_pickle.open("wb"))
            log.d(f"{author_pickle} - dumped")

    def file_from_path(self, path: str):
        path = path.strip("/")
        if path in self.file_index:
            return self.file_index[path]

        return None

    def get_file_from_modification(self, modification):
        path = modification.new_path
        if path is None:  # file deleted, use old path
            path = modification.old_path

        if path not in self.file_index:
            self.file_index[path] = File(self.repo, path)

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

        return Author(self.repo, commit_author.name, commit_author.email, index=self.author_index)

    def _set_start(self, timestamp):
        for v in self.file_index.values():
            v.expand_time_horizon(timestamp)
        for v in self.author_index:
            v.expand_time_horizon(timestamp)

    def index(self):
        if not self.indexed:
            for commit in self.repo_miner.traverse_commits():
                # self.commits.append(commit)
                for m in commit.modifications:
                    f = self.get_file_from_modification(m)
                    c = Change.from_commit_and_mod(commit, m)
                    c.get_author_from_index(commit, self)
                    f.add_change(c)

                self._set_start(commit.author_date)

            # self.commits = sorted(self.commits, key=lambda c: c.author_date)
            self.indexed = True
            self._pickle_save()

    @property
    def start(self):
        return None


class GitFile(Logger):
    _name = 'GitHelper'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
