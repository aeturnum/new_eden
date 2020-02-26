from .utils import Logger, dlog, wlog

class ChangeStats(Logger):
    def __init__(self, added, removed, **kwargs):
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

    def add_mod(self, mod):
        self.add_numbers(mod.added, mod.removed)


    def add_numbers(self, added, removed):
        self._added.append(added)
        self._removed.append(removed)

        self.added += added
        self.removed += removed


class Change(Logger):
    @staticmethod
    def from_commit_and_mod(commit, mod):
        path = mod.new_path
        if path == None: # file deleted, use old path
            path = mod.old_path

        return Change(path, mod.added, mod.removed, commit.author_date)

    def __init__(self, path, added, removed, date, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.added = added
        self.removed = removed
        self.date = date

        self.dlog(f'Creating {self}')

    def __str__(self):
        return f'Change[{self.path}](+{self.added},-{self.removed})'

    def __repr__(self):
        return str(self)

class Author(Logger):

    authors = []

    @staticmethod
    def find_author(commit_author):
        dlog(f'Author::find_author ({commit_author.name, commit_author.email})')
        for a in Author.authors:
            if (a.name == commit_author.name or a.email == commit_author.email):
                if (a.name != commit_author.name or a.email != commit_author.email):
                    if (a.name != commit_author.name):
                        wlog(f'\tAuthor::find_author|incomplete match[name] {a.name} != {commit_author.name}')
                    if (a.email != commit_author.email):
                        wlog(f'\tAuthor::find_author|incomplete match[email] {a.email} != {commit_author.email}')
                dlog(f'Author::find_author found: {a}')
                a.merge(commit_author)
                return a

        return Author(commit_author.name, commit_author.email)

    def __init__(self, name=None, email=None, changes = None, **kwargs):
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

        self._merge(name, email)

        Author.authors.append(self)

    def merge(self, author):
        self._merge(author.name, author.email)

    def _merge(self, name, email):
        if name not in self.names:
            self.names.add(name)
        if email not in self.emails:
            self.emails.add(email)

        if (name not in self.counts['names']):
            self.counts['names'][name] = 0
        if (name not in self.counts['emails']):
            self.counts['emails'][email] = 0

        self.counts['names'][name] += 1
        self.counts['emails'][email] = 1

        self._sift()

    def _sift(self):
        self._top_name = sorted(
            list(self.counts['names'].items()),
            key=lambda x: x[1], reverse=True
        )[0][0]
        self._top_email = sorted(
            list(self.counts['emails'].items()),
            key=lambda x: x[1], reverse=True
        )[0][0]

    @property
    def name(self):
        return self._top_name

    @property
    def email(self):
        return self._top_email

    def add_change(self, change):
        self.dlog(f'{self}::add_change <- {change}')
        self.changes.append(change)

    def __str__(self):
        email = str(self.email)
        name = str(self.name)

        if len(self.emails) > 1:
            email += f'(+{len(self.emails) - 1})'
        if len(self.names) > 1:
            name += f'(+{len(self.names) - 1})'

        return f'{name}<{email}>[{len(self.changes)}]'

    def __repr__(self):
        return str(self)