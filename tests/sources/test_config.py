import pytest

from core.sources.config import DEFAULT_POLICIES, build_policies, policy_for
from core.sources.errors import UnknownSourceError


def env_from(mapping):
    def env_str(name, default=None):
        return mapping.get(name, default)

    def env_bool(name, default=False):
        value = mapping.get(name)
        return default if value is None else str(value).lower() in {'1', 'true', 'yes', 'on'}

    return env_str, env_bool


def test_defaults_are_conservative():
    assert DEFAULT_POLICIES['divar'].requests_per_second == 0.5
    assert DEFAULT_POLICIES['sheypoor'].requests_per_second == pytest.approx(1 / 3)


def test_policy_for_falls_back_to_defaults():
    assert policy_for('divar') == DEFAULT_POLICIES['divar']


def test_policy_for_unknown_source():
    with pytest.raises(UnknownSourceError):
        policy_for('kijiji')


def test_environment_overrides_are_applied():
    env_str, env_bool = env_from(
        {
            'CRAWL_DIVAR_MAX_ATTEMPTS': '7',
            'CRAWL_DIVAR_REQUESTS_PER_SECOND': '2.5',
            'CRAWL_DIVAR_ENABLED': 'false',
        }
    )

    policies = build_policies(env_str, env_bool)

    assert policies['divar'].max_attempts == 7
    assert policies['divar'].requests_per_second == 2.5
    assert policies['divar'].enabled is False
    assert policies['sheypoor'] == DEFAULT_POLICIES['sheypoor']


def test_invalid_environment_values_are_rejected():
    env_str, env_bool = env_from({'CRAWL_DIVAR_MAX_ATTEMPTS': 'many'})

    with pytest.raises(ValueError):
        build_policies(env_str, env_bool)


def test_impossible_policy_is_rejected():
    with pytest.raises(ValueError):
        DEFAULT_POLICIES['divar'].__class__(**{**DEFAULT_POLICIES['divar'].__dict__, 'burst': 0})
