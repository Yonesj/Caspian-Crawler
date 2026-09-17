"""The one place that knows which adapters exist.

Adding a source means adding an entry here and a ``Source`` value in
``core.sources.enums`` — no other module changes.
"""

from .adapters.divar import DivarAdapter
from .adapters.sheypoor import SheypoorAdapter
from .base import SourceAdapter
from .enums import Source
from .errors import UnknownSourceError

ADAPTERS: dict[str, type[SourceAdapter]] = {
    Source.DIVAR: DivarAdapter,
    Source.SHEYPOOR: SheypoorAdapter,
}


def get_adapter(source: str, **kwargs) -> SourceAdapter:
    adapter_class = ADAPTERS.get(str(source))
    if adapter_class is None:
        raise UnknownSourceError(f'No adapter registered for source {source!r}')
    return adapter_class(**kwargs)


def available_sources() -> tuple[str, ...]:
    return tuple(ADAPTERS)
