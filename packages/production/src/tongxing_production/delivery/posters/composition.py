#!/usr/bin/env python3
"""Composition lint for generated poster artwork, based on macOS Vision saliency.

The poster template reserves the upper 40% for the title and the lower third for
the QR/badge footer, and asks for the primary subject around 40-66% of image
height. 2026-10-25 showed that concept selection alone is not enough: the stone
throne was placed so low that the footer covered its base.

This module asks Vision for objectness-based saliency boxes, converts them to
top-origin ratios, and classifies the subject band against the template's safe
area. It is a lint record, never a content approval: ``unknown`` means Vision is
unavailable or found no object; ``ok``/``edge``/``low``/``high`` describe where
the visible subject sits.
"""
from __future__ import annotations

import argparse
from importlib import resources
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SAFE_CENTRE = (0.38, 0.66)
SAFE_BOTTOM = 0.70
EDGE_BOTTOM = 0.74
LOW_CENTRE = 0.68
HIGH_CENTRE = 0.35
MIN_CONFIDENCE = 0.30


class CompositionError(ValueError):
    pass


def swift_path():
    return os.environ.get('SERMON_SWIFT') or shutil.which('swift')


def script_path():
    override = os.environ.get('SERMON_SALIENCY_SCRIPT')
    if override:
        return Path(override)
    return Path(str(resources.files(__package__) / 'saliency_lint.swift'))


def vision_boxes(image, swift=None):
    swift = swift or swift_path()
    if not swift or not Path(swift).is_file():
        return None
    script = script_path()
    if not script.is_file():
        return None
    cache = Path(tempfile.gettempdir()) / 'sermon-poster-swift-cache'
    try:
        process = subprocess.run([str(swift), '-module-cache-path', str(cache), str(script), str(image)],
                                 capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0:
        return None
    try:
        boxes = json.loads(process.stdout)
    except ValueError:
        return None
    return boxes if isinstance(boxes, list) else None


def classify(boxes):
    """Convert Vision boxes (origin bottom-left) into a top-origin subject band."""
    usable = [box for box in boxes
              if isinstance(box, dict) and isinstance(box.get('confidence'), (int, float))
              and box['confidence'] >= MIN_CONFIDENCE
              and all(isinstance(box.get(key), (int, float)) for key in ('x', 'y', 'w', 'h'))]
    if not usable:
        return dict(placement='unknown', method='vision_objectness', objects=0,
                    reason='no salient object above the confidence floor', warnings=[])
    top = 1 - max(box['y'] + box['h'] for box in usable)
    bottom = 1 - min(box['y'] for box in usable)
    left = min(box['x'] for box in usable)
    right = max(box['x'] + box['w'] for box in usable)
    centre = (top + bottom) / 2
    if centre < HIGH_CENTRE:
        placement = 'high'
    elif bottom > EDGE_BOTTOM or centre > LOW_CENTRE:
        placement = 'low'
    elif bottom > SAFE_BOTTOM or not (SAFE_CENTRE[0] <= centre <= SAFE_CENTRE[1]):
        placement = 'edge'
    else:
        placement = 'ok'
    warnings = []
    if placement == 'low':
        warnings.append('subject_covered_by_footer')
    elif placement == 'high':
        warnings.append('subject_too_high_for_title_area')
    elif placement == 'edge':
        warnings.append('subject_touches_footer')
    return dict(placement=placement, method='vision_objectness', objects=len(usable),
                bandTopRatio=round(top, 3), bandBottomRatio=round(bottom, 3),
                centreRatio=round(centre, 3), horizontalSpan=[round(left, 3), round(right, 3)],
                safeArea=dict(centre=SAFE_CENTRE, bottom=SAFE_BOTTOM), warnings=warnings)


def analyse(image, objects=None):
    """Lint one generated PNG; ``objects`` skips Vision and is used by tests."""
    path = Path(image)
    if not path.is_file():
        raise CompositionError('artwork does not exist: ' + str(path))
    if objects is None:
        objects = vision_boxes(path)
        if objects is None:
            return dict(placement='unknown', method='vision_objectness', objects=0,
                        reason='macOS Vision saliency is unavailable', warnings=[])
    return classify(objects)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--art', required=True, help='generated PNG to lint')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(analyse(args.art), ensure_ascii=False, sort_keys=True))
    except (CompositionError, OSError, ValueError) as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main()
