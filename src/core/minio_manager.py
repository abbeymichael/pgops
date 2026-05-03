"""
minio_manager.py  —  COMPATIBILITY SHIM

MinIO has been replaced by RustFS throughout PGOps.
This file exists only so that any third-party code or old pickled configs that
import from `core.minio_manager` continue to work without an ImportError.

All symbols are re-exported from core.rustfs_manager.
New code should import directly from core.rustfs_manager.
"""

from core.rustfs_manager import (  # noqa: F401  (re-export everything)
    RustFSManager as MinIOManager,   # legacy alias
    RustFSManager,
    rustfs_bin      as minio_bin,
    mc_bin,
    is_binaries_available,
    is_mc_available,
    get_rustfs_dir  as get_minio_dir,
    get_data_dir,
    get_assets_dir,
    RUSTFS_DOWNLOAD as MINIO_DOWNLOAD,
    MC_DOWNLOAD     as MINIO_CLIENT_DOWNLOAD,
    RUSTFS_BUNDLED  as MINIO_BUNDLED,
    MC_BUNDLED,
)
