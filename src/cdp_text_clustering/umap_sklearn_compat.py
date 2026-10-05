"""Adapt UMAP/HDBSCAN finite-value keywords to the installed scikit-learn API.

UMAP 0.5.12 and HDBSCAN 0.8.44 pass ``ensure_all_finite`` to ``check_array``, but this
project's scikit-learn 1.3.2 calls that argument ``force_all_finite``.
The wrapper changes only the keyword name and leaves validation unchanged.
Remove this compatibility shim after upgrading scikit-learn to a version
whose ``check_array`` accepts ``ensure_all_finite``.
"""

from __future__ import annotations

import inspect


def patch_topic_model_check_array() -> bool:
    from sklearn.utils.validation import check_array
    import umap.umap_ as umap_module
    import hdbscan.hdbscan_ as hdbscan_module

    if "ensure_all_finite" in inspect.signature(check_array).parameters:
        return False

    def check_array_compat(*args, **kwargs):
        if "ensure_all_finite" in kwargs:
            if "force_all_finite" in kwargs:
                raise TypeError("Both finite-value keyword aliases were supplied")
            kwargs["force_all_finite"] = kwargs.pop("ensure_all_finite")
        return check_array(*args, **kwargs)

    umap_module.check_array = check_array_compat
    hdbscan_module.check_array = check_array_compat
    return True
