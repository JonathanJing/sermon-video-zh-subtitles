"""Fail-closed, offline Xcode Cloud source admission, never Apple admission.

Only this directory is assumed available in the pre-xcodebuild environment.
No commands, network requests, writes, secrets or real release intents are used.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import sys
import xml.etree.ElementTree as ET


INTENT_ENV = "TONGXING_ARCHIVE_INTENT_JSON"
RESOURCES = (
    "project.pbxproj", "Tongxing.xcscheme", "TongxingBeta.xcscheme",
    "App-Info.plist", "Extension-Info.plist",
)
CHANNELS = {
    "production": ("Tongxing", "Release", "com.jonathanjing.tongxing.dev"),
    "beta": ("TongxingBeta", "BetaRelease", "com.jonathanjing.tongxing.beta"),
}
FIELDS = {
    "schemaVersion", "sourceCommit", "channel", "scheme", "configuration",
    "version", "sourceBuild", "cloudBuild", "issuedAt", "expiresAt", "resourcesSHA256",
}


class AdmissionError(ValueError):
    """An operator-safe diagnostic, never interpolated untrusted input."""


def require(condition, message):
    if not condition:
        raise AdmissionError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value),
            "intent timestamps must be UTC seconds ending in Z")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_project(text):
    """Parse the checked-in OpenStep subset; reject unsupported syntax/duplicates.

    Keeping this small parser here avoids installing a plist dependency or running
    xcodebuild merely to decide whether an archive may start. It does not resolve
    arbitrary Xcode settings; admission below requires explicit literal settings.
    """
    token = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[{}()=;,]|[^\s{}()=;,"]+', re.S)
    values = []
    offset = 0
    while offset < len(text):
        match = token.match(text, offset)
        require(match is not None, "unsupported project syntax")
        value = match.group()
        offset = match.end()
        require(not value.startswith("/*") or value.endswith("*/"), "unterminated project comment")
        if value.isspace() or value.startswith(("//", "/*")):
            continue
        values.append(value)
    cursor = 0

    def take(expected=None):
        nonlocal cursor
        require(cursor < len(values), "truncated project")
        value = values[cursor]
        cursor += 1
        require(expected is None or value == expected, "unsupported project structure")
        return value

    def scalar():
        value = take()
        require(value not in "{}()=;,", "invalid project scalar")
        return json.loads(value) if value.startswith('"') else value

    def value():
        require(cursor < len(values), "truncated project")
        if values[cursor] == "{":
            take("{")
            result = {}
            while cursor < len(values) and values[cursor] != "}":
                key = scalar()
                require(key not in result, "duplicate project key")
                take("=")
                result[key] = value()
                take(";")
            take("}")
            return result
        if values[cursor] == "(":
            take("(")
            result = []
            while cursor < len(values) and values[cursor] != ")":
                result.append(value())
                if cursor < len(values) and values[cursor] != ")":
                    take(",")
            take(")")
            return result
        return scalar()

    result = value()
    require(cursor == len(values), "trailing project data")
    return result


def source_settings(resources, intent, bundle_id):
    project = parse_project(resources["project.pbxproj"].decode("utf-8"))
    objects = project["objects"]
    root = objects[project["rootObject"]]
    require(root["isa"] == "PBXProject", "unsupported project root")
    targets = [objects[key] for key in root["targets"]]
    app_id = None
    for name, suffix, plist_name, plist_path in (
        ("Tongxing", "", "App-Info.plist", "App/Info.plist"),
        ("ListeningActivityExtension", ".listening-activity", "Extension-Info.plist", "ListeningActivityExtension/Info.plist"),
    ):
        matches = [item for item in targets if item.get("name") == name and item.get("isa") == "PBXNativeTarget"]
        require(len(matches) == 1, "missing or ambiguous native target")
        target = matches[0]
        if name == "Tongxing":
            app_id = next(key for key in root["targets"] if objects[key] is target)
        configs = objects[target["buildConfigurationList"]]["buildConfigurations"]
        matches = [objects[key] for key in configs if objects[key].get("name") == intent["configuration"]]
        require(len(matches) == 1, "missing or ambiguous archive configuration")
        settings = matches[0]["buildSettings"]
        expected = {
            "MARKETING_VERSION": intent["version"],
            "CURRENT_PROJECT_VERSION": intent["sourceBuild"],
            "PRODUCT_BUNDLE_IDENTIFIER": bundle_id + suffix,
            "INFOPLIST_FILE": plist_path,
            "GENERATE_INFOPLIST_FILE": "NO",
        }
        for key, expected_value in expected.items():
            require(settings.get(key) == expected_value, "source target version, build or identity mismatch")
            require(not any(k.startswith(key + "[") for k in settings), "conditional identity settings are unsupported")
        plist = plistlib.loads(resources[plist_name])
        require(all(plist.get(key) == expected_value for key, expected_value in {
            "CFBundleIdentifier": "$(PRODUCT_BUNDLE_IDENTIFIER)",
            "CFBundleShortVersionString": "$(MARKETING_VERSION)",
            "CFBundleVersion": "$(CURRENT_PROJECT_VERSION)",
        }.items()), "source Info.plist must use the checked target identity settings")
    scheme = ET.fromstring(resources[intent["scheme"] + ".xcscheme"])
    archives = scheme.findall("ArchiveAction")
    require(len(archives) == 1 and archives[0].get("buildConfiguration") == intent["configuration"],
            "scheme archive configuration mismatch")
    archive_targets = [entry.find("BuildableReference") for entry in scheme.findall("BuildAction/BuildActionEntries/BuildActionEntry")
                       if entry.get("buildForArchiving") == "YES"]
    require(len(archive_targets) == 1 and archive_targets[0] is not None
            and archive_targets[0].get("BlueprintIdentifier") == app_id
            and archive_targets[0].get("ReferencedContainer") == "container:Tongxing.xcodeproj",
            "scheme archive target mismatch")
    require(not scheme.findall(".//ExecutionAction"), "scheme actions require a new admission review")


def validate(environment, directory, now):
    raw = environment.get(INTENT_ENV, "")
    require(raw and len(raw.encode("utf-8")) <= 8192,
            "missing or oversized TONGXING_ARCHIVE_INTENT_JSON; supply a reviewed frozen candidate record")
    intent = json.loads(raw, object_pairs_hook=unique_object)
    require(type(intent) is dict and set(intent) == FIELDS, "unknown or missing intent fields")
    require(type(intent["schemaVersion"]) is int and intent["schemaVersion"] == 1, "unsupported intent schema")
    require(all(type(intent[key]) is str for key in FIELDS - {"schemaVersion", "resourcesSHA256"}), "invalid intent field types")
    require(re.fullmatch(r"[0-9a-f]{40}", intent["sourceCommit"]), "sourceCommit must be a full lowercase Git SHA")
    require(re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", intent["version"]), "invalid version")
    require(all(re.fullmatch(r"[1-9][0-9]*", intent[key]) for key in ("sourceBuild", "cloudBuild")), "invalid build number")
    issued, expires = timestamp(intent["issuedAt"]), timestamp(intent["expiresAt"])
    require(issued <= now < expires and timedelta(0) < expires - issued <= timedelta(hours=24),
            "intent is stale, future-dated or exceeds the 24-hour admission window")
    require(intent["channel"] in CHANNELS, "unsupported channel")
    scheme, configuration, bundle_id = CHANNELS[intent["channel"]]
    require((intent["scheme"], intent["configuration"]) == (scheme, configuration), "channel/scheme/configuration mismatch")
    for key, expected in {
        "CI_XCODE_CLOUD": "TRUE", "CI_XCODEBUILD_ACTION": "archive",
        "CI_COMMIT": intent["sourceCommit"], "CI_XCODE_SCHEME": scheme,
        "CI_BUILD_NUMBER": intent["cloudBuild"], "CI_BUNDLE_ID": bundle_id,
        "CI_PRODUCT_PLATFORM": "iOS",
    }.items():
        require(environment.get(key) == expected, "missing or mismatched " + key)
    # The checkout need not exist here; compare Cloud's lexical POSIX paths only.
    cloud_paths = {}
    for key in ("CI_PRIMARY_REPOSITORY_PATH", "CI_PROJECT_FILE_PATH"):
        raw_path = environment.get(key, "")
        require(raw_path.startswith("/") and not raw_path.startswith("//")
                and ".." not in raw_path.split("/") and "\\" not in raw_path and "\x00" not in raw_path,
                "missing or invalid " + key)
        cloud_paths[key] = PurePosixPath(raw_path)
    require(cloud_paths["CI_PROJECT_FILE_PATH"] == cloud_paths["CI_PRIMARY_REPOSITORY_PATH"]
            / "apps" / "tongxing-ios" / "Tongxing.xcodeproj", "Cloud project path does not match the frozen project")
    require(environment.get("CI_START_CONDITION") in {"manual", "manual_rebuild", "push", "schedule"}
            and not environment.get("CI_PULL_REQUEST_NUMBER"),
            "missing or unsupported start condition; pull-request merge archives are not frozen candidates")
    hashes = intent["resourcesSHA256"]
    require(type(hashes) is dict and set(hashes) == set(RESOURCES), "invalid frozen resource manifest")
    resources = {}
    for name in RESOURCES:
        require(type(hashes[name]) is str and re.fullmatch(r"[0-9a-f]{64}", hashes[name]), "invalid resource SHA-256")
        with (directory / name).open("rb") as stream:
            data = stream.read(2 * 1024 * 1024 + 1)
        require(len(data) <= 2 * 1024 * 1024 and hashlib.sha256(data).hexdigest() == hashes[name], "missing or changed frozen CI resource")
        resources[name] = data
    source_settings(resources, intent, bundle_id)


def main():
    try:
        validate(os.environ, Path(__file__).resolve().parent, datetime.now(timezone.utc))
    except AdmissionError as error:
        print("error: archive admission blocked: " + str(error), file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError, RecursionError, ET.ParseError):
        # Parser/IO exceptions can contain raw intent data or private paths.
        print("error: archive admission blocked: malformed intent or unavailable/unsupported source resources", file=sys.stderr)
        return 1
    print("Archive source intent matched. Apple version/train/build admission and upload remain unverified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
