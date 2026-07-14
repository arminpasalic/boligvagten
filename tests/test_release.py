"""Release tags must be unambiguous and match the built package."""
import pytest

from scripts.validate_release import validate


def test_release_tag_matches_package_version():
    validate("v1.2.3", "1.2.3")
    validate("v2.0.0-rc.1", "2.0.0-rc.1")


@pytest.mark.parametrize("tag", ["1.2.3", "v1.2", "v01.2.3", "v1.2.3.4", "latest"])
def test_release_tag_must_be_semver(tag):
    with pytest.raises(ValueError, match="SemVer"):
        validate(tag, "1.2.3")


def test_release_tag_must_match_package_version():
    with pytest.raises(ValueError, match="does not match"):
        validate("v1.2.4", "1.2.3")
