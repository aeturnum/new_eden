from materiality import Crawler

def test_basic():
    base = "/Users/ddrexler/src/python/web2py/"

    files = [
        "LICENSE",
        "ABOUT",
        "CHANGELOG",
        "Makefile",
        "README.markdown"
    ]

    c = Crawler(base)
    for file_name in files:
        c.crawl_file(file_name)

    for a in c.authors:
        print(a)
