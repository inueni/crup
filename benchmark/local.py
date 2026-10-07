# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "ada_url",
#     "can_ada",
#     "chardet",
#     "crup",
#     "pydomainextractor",
#     "pyfaup",
#     "rich",
#     "tldextract",
#     "yarl",
# ]
#
# [tool.uv.sources]
# crup = { path = "../" }
# ///

"""Run the shared benchmark with crup built from this checkout."""

from benchmark import main

if __name__ == "__main__":
    main()
