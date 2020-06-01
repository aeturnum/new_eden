import datetime
from typing import Dict

from .utils import Logger, dlog, wlog, PythonPathWrapper


class ChangeStats(Logger):
    _NAME = "ChangeStats"

    def __init__(self, added = 0, removed = 0, **kwargs):
        super().__init__(**kwargs)
        self.added = added
        self.removed = removed
        self.count = 0
        # self._added = [added]
        # self._removed = [removed]

    @property
    def changes(self):
        return self.added + self.removed

    @property
    def delta(self):
        return self.added - self.removed

    # @property
    # def count(self):
    #     return len(self._added)

    def merge_change(self, change):
        # self._added.extend(change.stats._added)
        # self._removed.extend(change.stats._removed)
        self.added += change.stats.added
        self.removed += change.stats.removed
        self.count += 1

    def add_mod(self, mod):
        self.add_numbers(mod.added, mod.removed)

    def add_numbers(self, added, removed):
        # self._added.append(added)
        # self._removed.append(removed)

        self.added += added
        self.removed += removed

    def __add__(self, other) -> 'ChangeStats':
        if not isinstance(other, ChangeStats):
            raise ValueError("Must add two changestats")

        combo = ChangeStats()
        combo.added = self.added + other.added
        combo.removed = self.removed + other.removed
        combo.count = self.count + other.count
        return combo

    def __str__(self):
        return f'(+{self.added},-{self.removed})'

    def __repr__(self):
        return str(self)

class Repo:
    def __init__(self, name, root_directory):
        self.name = name
        self.root_directory = root_directory

    def __str__(self):
        return f'R[{self.name}]'

class ObjectAge(Logger):
    def __init__(self,  **kwargs):
        super().__init__(**kwargs)
        self.age_events = []
        self.event_index = {}
        self.start_time = None
        self.end_time = None

    def add_event(self, date, data):
        self.age_events.append(date)
        self.event_index[date] = data

        self.age_events = sorted(self.age_events)
        if not self.start_time:
            self.start_time = self.age_events[0]
        if not self.end_time:
            self.end_time = self.age_events[0]

    def expand_time_horizon(self, event_ts:datetime):
        if event_ts < self.start_time:
            self.start_time = event_ts
        if event_ts > self.end_time:
            self.end_time = event_ts

    @property
    def age(self):
        if len(self.age_events) > 1:
            return self.end_time - self.age_events[0]

        return None

    @property
    def created_after(self):
        return self.age_events[0] - self.start_time

    @property
    def lifetime(self):
        if len(self.age_events) > 2:
            return self.age_events[-1] - self.age_events[0]

        return None


class Author(ObjectAge):
    _NAME = "Author"

    authors = []

    def __init__(self, repo: Repo, name=None, email=None, changes=None, index=None, **kwargs):
        super().__init__(**kwargs)
        self.repo = repo
        self.names = set()
        self.emails = set()
        self.counts = {
            'names': {},
            'emails': {}
        }
        self._top_name = name
        self._top_email = email
        self.changes = changes or []
        self.stats = ChangeStats(0, 0)

        self._merge(name, email)

        if index is None:
            index = Author.authors
        index.append(self)

    def merge(self, author):
        self._merge(author.name, author.email)

    @property
    def ects(self):
        return self.counts['emails']

    @property
    def ncts(self):
        return self.counts['names']

    def _merge(self, name, email):
        if name not in self.names:
            self.names.add(name)
        if email not in self.emails:
            self.emails.add(email)

        if name not in self.counts['names']:
            self.ncts[name] = 0
        if name not in self.counts['emails']:
            self.ects[email] = 0

        self.ncts[name] += 1
        self.ects[email] += 1

        self._sift()

    def _sift(self):
        self._top_name = sorted(
            list(self.ncts.items()),
            key=lambda x: x[1], reverse=True
        )[0][0]
        self._top_email = sorted(
            list(self.ects.items()),
            key=lambda x: x[1], reverse=True
        )[0][0]

    @property
    def name(self):
        return self._top_name

    @property
    def email(self):
        return self._top_email

    def add_change(self, change):
        log = self.logger("add change")
        # log.d(f'<- {change}')
        self.changes.append(change)
        self.stats.merge_change(change)

        self.add_event(change.date, change)

    def __lt__(self, other):
        if not isinstance(other, Author):
            raise ValueError(f"{other} is not an Author!")

        return self.stats.count < other.stats.count

    def __le__(self, other):
        if not isinstance(other, Author):
            raise ValueError(f"{other} is not an Author!")

        return self.stats.count <= other.stats.count

    def __gt__(self, other):
        if not isinstance(other, Author):
            raise ValueError(f"{other} is not an Author!")

        return self.stats.count > other.stats.count

    def __str__(self):
        email = str(self.email)
        name = str(self.name)

        if len(self.emails) > 1:
            email += f'(+{len(self.emails) - 1})'
        if len(self.names) > 1:
            name += f'(+{len(self.names) - 1})'

        return f'{self.repo}{name}<{email}>[{self.stats.count}={self.stats}]'

    def __repr__(self):
        return str(self)


class Change(Logger):

    _NAME = "Change"

    # todo: figure out how to avoid duplicate changes
    @staticmethod
    def from_commit_and_mod(commit, mod):
        path = mod.new_path
        if path is None:  # file deleted, use old path
            path = mod.old_path

        return Change(path, mod.added, mod.removed, commit)

    def __init__(self, path, added, removed, commit, **kwargs):
        super().__init__(**kwargs)
        log = self.logger("__init__")
        self.path = path
        self.stats = ChangeStats(added, removed)
        self.date = commit.author_date

        # log.d(f'Created')

    def get_author_from_index(self, commit, author_index):
        self.author = author_index.find_author(commit.author)
        self.author.add_change(self)

    def __str__(self):
        return f'Change[{self.path}]{self.stats}'

    def __repr__(self):
        return str(self)

class File(ObjectAge):

    _NAME = "File"

    files = {}

    @staticmethod
    def get_file(mod):
        path = mod.new_path
        if path is None:  # file deleted, use old path
            path = mod.old_path

        if path in File.files:
            return File.files[path]

        File.files[path] = File(path)
        return File.files[path]

    def __init__(self, repo: Repo, path, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        # self.changes = []
        self.authors = set()
        self.author_changes: Dict[Author, ChangeStats] = {}
        self.stats = ChangeStats()
        self.repo = repo

    def add_change(self, change: Change):
        log = self.logger("add_change")
        # self.changes.append(change)
        self.stats.merge_change(change)
        self.add_event(change.date, change)
        if change.author not in self.authors:
            self.author_changes[change.author] = ChangeStats()
            self.authors.add(change.author)
        self.author_changes[change.author].merge_change(change)

    def __str__(self):
        # p = PythonPathWrapper(self.path).short_version
        return f'{self.repo}File[{self.path}][{len(self.authors)} authors]{self.stats}'

    def __repr__(self):
        return str(self)