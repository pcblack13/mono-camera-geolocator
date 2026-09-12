"""Vendored third-party/standalone cores shipped inside the backend.

★ THE RULE: a package here is copied VERBATIM from its standalone home and is fixed
THERE, then re-copied — divergence between the two is a defect. Three qualify:

* ``lut_generator`` — the LUT Generator core (``backend/LUT_Generator/src``).
* ``geo_accuracy`` — the field tool's measure-and-correct core (one permitted
  substitution, ``_interp.py``, documented in its own header).
* ``drift_monitor`` — the camera drift monitor (engine-agnostic; the engine is
  ``app.services.drift_service``).

★ ``object_geolocator`` is NO LONGER HERE (2026-09-02). It had been edited in place
five times and was a fork, not a vendored copy; it now lives as
``app.services.detection`` with its tests, and is fixed there.
"""
