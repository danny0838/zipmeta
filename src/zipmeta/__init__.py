import inspect
from zipfile import *  # noqa: F403
from zipfile import __all__  # noqa: F401

if inspect.signature(ZipFile.__init__).parameters.get('with_ext_timestamps') is None:
    from .zipmeta import (  # noqa: F401
        _NTFS_EXTRA_TS_DELTA,
        ZipFile,
        ZipInfo,
        _Extra,
    )
