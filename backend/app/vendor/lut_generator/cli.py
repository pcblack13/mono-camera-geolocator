"""Command-line entry point.

    python -m lut_generator build    config/site_108.json [--zip]
    python -m lut_generator inspect  output/site_108_lut
    python -m lut_generator template config/new_site.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .builder import build_lut
from .bundle import archive_bundle, write_bundle
from .config import BuildConfig, write_template
from .dem import DEM
from .logging_setup import setup_logging
from .pose import pose_from_project
from .validator import validate_lut

log = logging.getLogger("lut_generator")


def cmd_build(args) -> int:
    cfg = BuildConfig.load(args.config)
    log.info("=" * 78)
    log.info("LUT BUILD  site '%s'", cfg.site_name)
    log.info("  project : %s", cfg.project_json)
    log.info("  DEM     : %s", cfg.dem_path)
    log.info("=" * 78)

    dem = DEM(cfg.dem_path)
    log.info("DEM loaded: EPSG:%d, %.3f m, %d x %d", dem.epsg, dem.res,
             dem.width, dem.height)

    pose = pose_from_project(cfg.project_json, cfg.image_width, cfg.image_height)
    log.info(pose.summary())
    if pose.reproj_mean_px > 25:
        log.warning("reprojection mean is %.1f px - the pose looks weak; "
                    "the LUT will inherit that error", pose.reproj_mean_px)

    lut = build_lut(cfg, pose, dem)
    report = validate_lut(lut, cfg, pose, dem)
    if not report["passed"] and not args.force:
        log.error("validation FAILED - bundle not written (use --force to override)")
        return 2

    out = write_bundle(lut, cfg, pose, dem, report)
    if args.zip:
        archive_bundle(out)
    log.info("done.")
    return 0


def cmd_inspect(args) -> int:
    path = os.path.join(args.bundle, "manifest.json")
    if not os.path.isfile(path):
        log.error("no manifest.json in %s", args.bundle)
        return 1
    with open(path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    print(json.dumps(m, indent=2))
    return 0


def cmd_template(args) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(args.path)), exist_ok=True)
    write_template(args.path)
    log.info("template written: %s", args.path)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="lut_generator",
        description="Build a full-resolution pixel -> lat/lon lookup table "
                    "for a fixed camera, ready to deploy on a Raspberry Pi.")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build a LUT bundle from a config file")
    b.add_argument("config", help="path to the build config JSON")
    b.add_argument("--zip", action="store_true", help="also produce a .zip for upload")
    b.add_argument("--force", action="store_true",
                   help="write the bundle even if validation fails")
    b.set_defaults(func=cmd_build)

    i = sub.add_parser("inspect", help="print a bundle manifest")
    i.add_argument("bundle", help="path to a *_lut folder")
    i.set_defaults(func=cmd_inspect)

    t = sub.add_parser("template", help="write a starter config file")
    t.add_argument("path", help="where to write it")
    t.set_defaults(func=cmd_template)

    args = p.parse_args(argv)
    setup_logging(verbose=args.verbose)
    try:
        return args.func(args)
    except Exception as exc:              # noqa: BLE001 - top level guard
        log.error("%s: %s", type(exc).__name__, exc)
        if args.verbose:
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
