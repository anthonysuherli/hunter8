import pytest

from companion_api.settings import CompanionSettings


def test_origins_parses_and_strips_a_comma_list():
    settings = CompanionSettings(HUNTER8_ALLOWED_ORIGINS="https://a.com, https://b.com ,https://c.com")
    assert settings.origins() == ["https://a.com", "https://b.com", "https://c.com"]


def test_origins_rejects_a_bare_wildcard():
    settings = CompanionSettings(HUNTER8_ALLOWED_ORIGINS="*")
    with pytest.raises(ValueError):
        settings.origins()


def test_origins_rejects_a_wildcard_mixed_with_a_real_origin():
    settings = CompanionSettings(HUNTER8_ALLOWED_ORIGINS="https://a.com,*")
    with pytest.raises(ValueError):
        settings.origins()
