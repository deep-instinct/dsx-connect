import pytest

from shared.file_ops import parse_filter_spec
from shared.file_ops import _has_glob
from shared.file_ops import relpath_matches_filter
from shared.file_ops import compute_prefix_hints


@pytest.mark.parametrize(
    "filt, path, expect",
    [
        ("", "a/b/c.txt", True),
        ("*", "top.txt", True),
        ("*", "sub/top.txt", False),
        ("sub1", "sub1/a.txt", True),
        ("sub1", "sub2/a.txt", False),
        ("sub1/*", "sub1/a.txt", True),
        ("sub1/*", "sub1/x/y.txt", False),
        ("sub1/**", "sub1/x/y.txt", True),
        ("**/*.txt", "a.txt", True),
        ("**/*.txt", "a/b/c.txt", True),
        ("sub1 -tmp --exclude sub2", "sub1/ok.txt", True),
        ("sub1 -tmp --exclude sub2", "sub1/tmp/hide.txt", False),
        ("sub1 -tmp --exclude sub2", "sub1/sub2/hide.txt", False),
        ("'scan here' -'not here'", "scan here/a.txt", True),
        ("'scan here' -'not here'", "not here/a.txt", False),
    ],
)
def test_relpath_matches_filter(filt, path, expect):
    assert relpath_matches_filter(path, filt) is expect


@pytest.mark.parametrize(
    "filt, expected",
    [
        ("", []),
        ("*", []),
        ("sub1", ["sub1/"]),
        ("sub1/**", ["sub1/"]),
        ("sub1/*", ["sub1/"]),
        ("sub1 sub2", ["sub1/", "sub2/"]),
        ("sub1 -tmp", []),
        ("**/*.txt", []),
    ],
)
def test_compute_prefix_hints(filt, expected):
    assert compute_prefix_hints(filt) == expected
