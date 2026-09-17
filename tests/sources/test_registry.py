import pytest

from core.sources.adapters.divar import DivarAdapter
from core.sources.adapters.sheypoor import SheypoorAdapter
from core.sources.enums import Source
from core.sources.errors import UnknownSourceError
from core.sources.registry import available_sources, get_adapter


def test_every_source_has_an_adapter():
    assert available_sources() == (Source.DIVAR, Source.SHEYPOOR)
    assert isinstance(get_adapter(Source.DIVAR), DivarAdapter)
    assert isinstance(get_adapter(Source.SHEYPOOR), SheypoorAdapter)


def test_unknown_source_is_rejected():
    with pytest.raises(UnknownSourceError):
        get_adapter('kijiji')


def test_adapters_expose_their_source():
    assert get_adapter('divar').source == Source.DIVAR
    assert get_adapter('sheypoor').source == Source.SHEYPOOR
