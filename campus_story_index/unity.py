"""Shared UnityPy fallback configuration for the extraction processes."""
import warnings

DEFAULT_UNITY_VERSION = '6000.0.77f1'
_configured_version = None


def configure_unity(version=DEFAULT_UNITY_VERSION):
    import UnityPy
    from UnityPy.exceptions import UnityVersionFallbackWarning

    global _configured_version
    if _configured_version == version:
        return
    UnityPy.config.FALLBACK_UNITY_VERSION = version
    warnings.filterwarnings('ignore', category=UnityVersionFallbackWarning)
    _configured_version = version
    print(f'UnityPy: 缺少版本信息的资源按 {version} 解包', flush=True)
