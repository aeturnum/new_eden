from .utils import Logger, dlog, wlog


class ChangeStats(Logger):
    def __init__(self, added = 0, removed = 0, **kwargs):
        super().__init__(**kwargs)
        self.added = added
        self.removed = removed
        self._added = [added]
        self._removed = [removed]

    @property
    def changes(self):
        return self.added + self.removed

    @property
    def delta(self):
        return self.added - self.removed

    @property
    def count(self):
        return len(self._added)

    def merge_change_stat(self, cs):
        self._added.extend(cs._added)
        self._removed.extend(cs._removed)
        self.added += cs.added
        self.removed += cs.removed

    def add_mod(self, mod):
        self.add_numbers(mod.added, mod.removed)

    def add_numbers(self, added, removed):
        self._added.append(added)
        self._removed.append(removed)

        self.added += added
        self.removed += removed

    def __str__(self):
        return f'(+{self.added},-{self.removed})'

    def __repr__(self):
        return str(self)

class Author(Logger):
    _NAME = "Change"

    authors = []



    @staticmethod
    def find_author(commit_author):
        dlog(f'Author::find_author', f'({commit_author.name, commit_author.email})')
        for a in Author.authors:
            if a.name == commit_author.name or a.email == commit_author.email:
                if commit_author.name not in a.names or commit_author.email not in a.email:
                    if commit_author.name not in a.names:
                        wlog(f'\tAuthor::find_author', f'incomplete match[name] {commit_author.name} not in {a.names} ')
                    if commit_author.email not in a.emails:
                        wlog(f'\tAuthor::find_author', f'incomplete match[email] {commit_author.email} not in {a.emails}')
                dlog(f'Author::find_author', f'found: {a}')
                a.merge(commit_author)
                return a

        return Author(commit_author.name, commit_author.email)

    def __init__(self, name=None, email=None, changes=None, **kwargs):
        super().__init__(**kwargs)
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

        Author.authors.append(self)

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
        self.dlog('add_change', f'<- {change}')
        self.changes.append(change)
        self.stats.merge_change_stat(change.stats)

    def __str__(self):
        email = str(self.email)
        name = str(self.name)

        if len(self.emails) > 1:
            email += f'(+{len(self.emails) - 1})'
        if len(self.names) > 1:
            name += f'(+{len(self.names) - 1})'

        return f'{name}<{email}>[{len(self.changes)}={self.stats}]'

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
        self.path = path
        self.stats = ChangeStats(added, removed)
        self.date = commit.author_date
        # todo: decide if I really wanna do this here
        self.author = Author.find_author(commit.author)
        self.author.add_change(self)

        self.dlog(f'__init__', f'Created')

    def __str__(self):
        return f'Change[{self.path}]{self.stats}'

    def __repr__(self):
        return str(self)

class File(Logger):

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

    def __init__(self, path, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.changes = []
        self.authors = set()
        self.stats = ChangeStats()

    def add_change(self, change):
        self.dlog(f'add_change', f'Adding {change} to {self}')
        self.changes.append(change)
        self.stats.merge_change_stat(change.stats)
        self.authors.add(change.author)

    def __str__(self):
        return f'File[{self.path}][{len(self.authors)} authors]{self.stats}'

    def __repr__(self):
        return str(self)