from materiality import Author, Change

from pydriller import RepositoryMining

def test_basic():
    base = "/Users/ddrexler/src/python/web2py/"

    files = [
        "LICENSE",
        "ABOUT",
        "CHANGELOG",
        "Makefile",
        "README.markdown"
    ]

    for file_name in files:
        for commit in RepositoryMining(base, filepath=file_name).traverse_commits():
            author = Author.find_author(commit.author)
            for m in commit.modifications:
                if (m.new_path == file_name):
                    change = Change.from_commit_and_mod(commit, m)
                    author.add_change(change)

    for a in Author.authors:
        print(a)
