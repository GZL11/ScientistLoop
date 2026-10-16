"""为隔离的 NatureBench evaluator 子进程安装依赖兼容别名。"""
from __future__ import annotations

import importlib
import sys


def _install_numpy_core_aliases() -> None:
    """允许 NumPy 1.x 读取由 NumPy 2.x 写出的常见 pickle。"""

    try:
        numpy = importlib.import_module("numpy")
        numpy_core = importlib.import_module("numpy.core")
    except ImportError:
        return

    # NumPy 2.x 把 pickle 中的内部模块路径写成 ``numpy._core``。旧版 NumPy
    # 的实现仍在 ``numpy.core``，这里只增加导入别名，不修改数据或评分逻辑。
    sys.modules.setdefault("numpy._core", numpy_core)
    if not hasattr(numpy, "_core"):
        setattr(numpy, "_core", numpy_core)
    for module_name in (
        "_multiarray_umath",
        "fromnumeric",
        "multiarray",
        "numeric",
        "numerictypes",
        "overrides",
        "shape_base",
        "umath",
    ):
        try:
            module = importlib.import_module(f"numpy.core.{module_name}")
        except ImportError:
            continue
        sys.modules.setdefault(f"numpy._core.{module_name}", module)


def _install_anndata_null_reader() -> None:
    """Read H5AD ``encoding-type=null`` elements with older anndata builds.

    Some NatureBench reference H5AD files were written by a newer anndata
    release. Older evaluator images fail before looking at the candidate with
    ``No read method registered for IOSpec(..., encoding_type='null')``. The
    null element carries no prediction data and is safely represented by
    ``None``; registering the reader keeps the official evaluator unchanged.
    """

    try:
        import h5py
        from anndata._io.specs import IOSpec
        from anndata._io.specs import registry as registry_module
    except (ImportError, AttributeError):
        return

    _REGISTRY = getattr(registry_module, "_REGISTRY", None)
    register_read = getattr(_REGISTRY, "register_read", None)
    if not callable(register_read):
        return

    def read_null(_elem, *, _reader):
        del _reader
        return None

    for source_type in (h5py.Dataset, h5py.Group):
        try:
            decorator = register_read(
                source_type,
                IOSpec(encoding_type="null", encoding_version="0.1.0"),
            )
            decorator(read_null)
        except Exception:  # noqa: BLE001 - compatibility is best effort
            # A newer anndata already registers this spec, or a particular
            # release uses a narrower source type. Keep trying the other type.
            continue


_install_numpy_core_aliases()
_install_anndata_null_reader()
