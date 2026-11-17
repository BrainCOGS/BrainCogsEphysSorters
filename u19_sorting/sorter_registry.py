"""Allow-list of pinned sorter versions a job may request.

A job selects a sorter version with a registry key ("<sorter>@<version>") in the
"sorter_version" field of its process params. Keys are resolved here, once, before the
sorter runs; anything not in the registry is refused (no free-text env or image paths).

Registry entries (sorter_registry.json, override with U19_SORTER_REGISTRY):

  native:    runs in the job's own python env; the installed package version must match.
             {"mode": "native", "sorter": "kilosort4", "version": "4.1.7"}

  container: runs through SpikeInterface inside a pre-built Apptainer image.
             {"mode": "container", "sorter": "kilosort3",
              "image": "docker://spikeinterface/kilosort3-compiled-base:<tag>",
              "digest": "sha256:<64 hex>"}

A container entry names only the base image (by tag, for the file name) and its digest (what
is pulled). The SpikeInterface inside the image is the job's own: the image file is
"<image name>_<tag>_si-<spikeinterface version>.sif", with the version the job has installed
(uv.lock), so a SpikeInterface bump needs new images but no registry change. The host
serializes the recording and the image's SpikeInterface loads it, so resolve() takes the
image built for the installed version; failing that, one built for another patch release of
the same minor release (with a warning). An image for another minor release is refused.

Container images are never pulled on compute nodes (no internet there). They are built
into the shared sif dir by scripts/sorter_image.sh (fetch on a login node, build on a
compute node), and a missing image is an error here rather than a pull.

Entries are append-only: never change an existing key, add a new one instead.
"""

import dataclasses
import importlib.metadata
import json
import os
import pathlib
import re
import warnings

from u19_sorting import config

NATIVE_SORTERS = {"kilosort4"}
CONTAINER_SORTERS = {"kilosort2", "kilosort2_5", "kilosort3", "kilosort4"}

_KEY_RE = re.compile(r"^([a-z0-9_]+)@([A-Za-z0-9._+-]+)$")
_DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
_DIGEST_FIELD_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# What goes into an image file name: the image name and tag, and a version.
_NAME_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# The release segment of a version ("0.105.0" in "0.105.0rc1").
_RELEASE_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")

_FIELDS = {
    "native": {"mode", "sorter", "version", "description"},
    "container": {"mode", "sorter", "image", "digest", "description"},
}


class SorterRegistryError(ValueError):
    """Invalid registry entry, or a job that doesn't match its registry entry."""


class UnknownSorterVersionError(SorterRegistryError):
    """The requested key is not in the allow-list."""


class MissingSorterImageError(SorterRegistryError):
    """No usable container image for a key is cached on shared storage."""


class SorterImageVersionWarning(UserWarning):
    """The image's SpikeInterface is another patch release than the job's."""


def build_commands(key):
    """How to build a key's image for the installed SpikeInterface (see scripts/sorter_image.sh)."""

    return (
        f"`scripts/sorter_image.sh fetch {key}` on a login node, then "
        f"`sbatch scripts/sorter_image.sh build {key}`, from the checkout"
    )


def installed_spikeinterface():
    """The SpikeInterface version installed in this environment, or None."""

    try:
        return importlib.metadata.version("spikeinterface")
    except importlib.metadata.PackageNotFoundError:
        return None


def release(version):
    """(major, minor, patch) of a version string, or None if it has no such release segment."""

    match = _RELEASE_RE.match(version) if isinstance(version, str) else None
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


@dataclasses.dataclass(frozen=True)
class SorterEntry:
    key: str
    mode: str
    sorter: str
    version: str | None = None
    image: str | None = None
    digest: str | None = None
    description: str | None = None

    @property
    def pull_ref(self):
        """The image by digest, the reference that is pulled: docker://<name>@sha256:..."""

        name = self.image.rpartition("/")
        repository = name[0] + name[1] + name[2].partition(":")[0]
        return f"{repository}@{self.digest}"

    @property
    def sif_prefix(self):
        """'<image name>_<tag>': the part of the image file name that the entry fixes."""

        name, _, tag = self.image.rpartition("/")[2].partition(":")
        return f"{name}_{tag}"

    def sif_name(self, spikeinterface_version):
        """File name of this entry's image built with the given SpikeInterface version."""

        if not isinstance(spikeinterface_version, str) or not _NAME_PART_RE.match(
            spikeinterface_version
        ):
            raise SorterRegistryError(
                f"{self.key}: not a spikeinterface version: {spikeinterface_version!r}"
            )
        return f"{self.sif_prefix}_si-{spikeinterface_version}.sif"

    def sif_version(self, filename):
        """The SpikeInterface version in one of this entry's image file names, or None."""

        head, tail = f"{self.sif_prefix}_si-", ".sif"
        if not (filename.startswith(head) and filename.endswith(tail)):
            return None
        version = filename[len(head) : -len(tail)]
        return version if release(version) is not None else None


@dataclasses.dataclass(frozen=True)
class ResolvedSorter:
    entry: SorterEntry
    sif_path: pathlib.Path | None = None
    # SpikeInterface baked into the image (from its file name); None for native entries.
    spikeinterface: str | None = None

    def provenance(self):
        """JSON-able record of exactly what ran, stored next to the sorter output."""

        prov = {
            "sorter_version": self.entry.key,
            "sorter": self.entry.sorter,
            "mode": self.entry.mode,
        }
        if self.entry.mode == "native":
            prov["version"] = self.entry.version
        else:
            prov["image"] = self.entry.pull_ref
            prov["spikeinterface"] = self.spikeinterface
            prov["sif_path"] = str(self.sif_path)
            if self.sif_path.is_file():
                prov["sif_size_bytes"] = self.sif_path.stat().st_size
        return prov


def default_registry_file():
    return pathlib.Path(
        os.environ.get("U19_SORTER_REGISTRY", config.sorter_registry_file)
    )


def default_sif_dir():
    return pathlib.Path(
        os.environ.get("U19_APPTAINER_SIF_DIR", config.apptainer_sif_dir)
    )


def is_pinned_docker_image(image):
    """docker://<ref> with an explicit tag other than `latest`, or a sha256 digest."""

    if not isinstance(image, str) or not image.startswith("docker://"):
        return False
    ref = image[len("docker://") :]
    if _DIGEST_RE.search(ref):
        return True
    # The tag lives in the last path component; a ':' earlier is a registry port.
    name, _, tag = ref.rpartition("/")[2].partition(":")
    return bool(name) and bool(tag) and tag != "latest"


def is_tagged_docker_image(image):
    """docker://<name>:<tag>, no digest, with a tag other than `latest` that can go in a file name."""

    if not is_pinned_docker_image(image) or "@" in image:
        return False
    name, _, tag = image.rpartition("/")[2].partition(":")
    return bool(_NAME_PART_RE.match(name)) and bool(_NAME_PART_RE.match(tag))


def parse_entry(key, raw):
    """Validate one registry entry and return it as a SorterEntry."""

    if not isinstance(raw, dict):
        raise SorterRegistryError(
            f"{key!r}: entry must be an object, got {type(raw).__name__}"
        )

    match = _KEY_RE.match(key) if isinstance(key, str) else None
    if not match:
        raise SorterRegistryError(f'{key!r}: key must look like "<sorter>@<version>"')

    mode = raw.get("mode")
    if mode not in _FIELDS:
        raise SorterRegistryError(
            f"{key}: mode must be one of {sorted(_FIELDS)}, got {mode!r}"
        )

    unknown = set(raw) - _FIELDS[mode]
    if unknown:
        raise SorterRegistryError(
            f"{key}: unknown fields for {mode} mode: {sorted(unknown)}"
        )

    sorter = raw.get("sorter")
    if sorter != match.group(1):
        raise SorterRegistryError(
            f"{key}: key prefix must equal the entry sorter ({sorter!r})"
        )

    if mode == "native":
        if sorter not in NATIVE_SORTERS:
            raise SorterRegistryError(
                f"{key}: {sorter} cannot run native, only {sorted(NATIVE_SORTERS)}"
            )
        if not raw.get("version"):
            raise SorterRegistryError(
                f'{key}: native entries need the pinned package "version"'
            )
    else:
        if sorter not in CONTAINER_SORTERS:
            raise SorterRegistryError(
                f"{key}: {sorter} is not a supported container sorter"
            )
        if not is_tagged_docker_image(raw.get("image")):
            raise SorterRegistryError(
                f'{key}: image must be "docker://<name>:<tag>" with a tag other than latest '
                f"(the digest goes in digest), got {raw.get('image')!r}"
            )
        if not isinstance(raw.get("digest"), str) or not _DIGEST_FIELD_RE.match(
            raw["digest"]
        ):
            raise SorterRegistryError(
                f'{key}: digest must be the image\'s "sha256:<64 hex>", got {raw.get("digest")!r}'
            )

    return SorterEntry(key=key, **raw)


def load_registry(path=None):
    """Load and validate the whole registry: {key: SorterEntry}."""

    path = pathlib.Path(path) if path is not None else default_registry_file()
    with open(path) as f:
        raw_registry = json.load(f)

    if not isinstance(raw_registry, dict):
        raise SorterRegistryError(
            f"{path}: registry must be a JSON object of key -> entry"
        )

    registry = {key: parse_entry(key, raw) for key, raw in raw_registry.items()}

    # Two keys with one image name and tag would share their image files.
    prefixes = [e.sif_prefix for e in registry.values() if e.mode == "container"]
    duplicated = sorted({p for p in prefixes if prefixes.count(p) > 1})
    if duplicated:
        raise SorterRegistryError(
            f"{path}: image name and tag shared by several keys: {duplicated}"
        )

    return registry


def find_image(entry, sif_dir, spikeinterface_version):
    """(path, spikeinterface version) of the image a job with this SpikeInterface runs.

    The image built for exactly that version if it is there; otherwise the newest one built
    for another patch release of the same minor release, with a SorterImageVersionWarning.
    Anything else raises MissingSorterImageError naming the commands that build the image.
    """

    host = release(spikeinterface_version)
    if host is None:
        raise SorterRegistryError(
            f"{entry.key}: container sorters need spikeinterface installed in the job's "
            f"environment, found {spikeinterface_version!r}"
        )

    sif_dir = pathlib.Path(sif_dir).resolve()
    wanted = sif_dir / entry.sif_name(spikeinterface_version)
    if wanted.is_file() and wanted.stat().st_size > 0:
        return wanted.resolve(), spikeinterface_version

    cached = {}
    if sif_dir.is_dir():
        for path in sif_dir.iterdir():
            version = entry.sif_version(path.name)
            if version and path.is_file() and path.stat().st_size > 0:
                cached[version] = path

    same_minor = [v for v in cached if release(v)[:2] == host[:2]]
    if same_minor:
        version = max(same_minor, key=lambda v: (release(v), v))
        message = (
            f"{entry.key}: no image for spikeinterface {spikeinterface_version} in {sif_dir}; "
            f"running {cached[version].name}, built with spikeinterface {version} (patch "
            f"difference). To build the matching image: {build_commands(entry.key)}."
        )
        print("WARNING", message)
        warnings.warn(message, SorterImageVersionWarning, stacklevel=2)
        return cached[version].resolve(), version

    found = (
        f" Images for other minor releases are not used: {sorted(cached)}."
        if cached
        else ""
    )
    raise MissingSorterImageError(
        f"{entry.key}: no image for spikeinterface {spikeinterface_version} "
        f"({wanted.name}) in {sif_dir}.{found} Build it with {build_commands(entry.key)}."
    )


def resolve(
    key, registry=None, sif_dir=None, check_image=True, spikeinterface_version=None
):
    """Resolve an allow-listed key to what the job will run.

    For container entries the image is the absolute path of the cached .sif for
    spikeinterface_version (default: the installed SpikeInterface); see find_image. When
    check_image is set, a missing, empty or incompatible image raises
    MissingSorterImageError instead of letting SpikeInterface try to pull it; without it
    the path is the one the image for that version would have.
    """

    if registry is None:
        registry = load_registry()

    if not isinstance(key, str) or key not in registry:
        raise UnknownSorterVersionError(
            f"sorter_version {key!r} is not in the registry; allowed: {sorted(registry)}"
        )

    entry = registry[key]
    if entry.mode == "native":
        return ResolvedSorter(entry)

    sif_dir = pathlib.Path(sif_dir) if sif_dir is not None else default_sif_dir()
    if spikeinterface_version is None:
        spikeinterface_version = installed_spikeinterface()

    if not check_image:
        sif_path = (sif_dir / entry.sif_name(spikeinterface_version)).resolve()
        return ResolvedSorter(entry, sif_path, spikeinterface_version)

    sif_path, image_version = find_image(entry, sif_dir, spikeinterface_version)
    return ResolvedSorter(entry, sif_path, image_version)
