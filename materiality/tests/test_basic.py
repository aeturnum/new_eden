from materiality import DependencyFinder

def test_basic():
    base = "/Users/ddrexler/src/python/web2py/"

    # c = DependencyFinder(base)
    # c.crawl_repo()
    #
    # for f in c.file_list:
    #     print(f)
    #
    # for a in c.author_list:
    #     print(a)

def test_module_finder():
    # base = "/Users/ddrexler/src/python/web2py/"
    base = "/Users/ddrexler/src/python/breitbart_comment_grabbing_server/bcgs/"

    c = DependencyFinder(base)
    mc = c.crawl_file_modules("server.py")
