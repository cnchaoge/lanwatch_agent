"""
版本号管理。
"""
version = "1.0.1"
__version_info__ = (1, 0, 1)
__release_date__ = "2026-04-30"
author = "cnchaoge"
license = "MIT"


def get_version() -> str:
    return version


def get_version_info() -> dict:
    return {
        "version": version,
        "release_date": __release_date__,
        "author": author,
        "license": license,
    }
