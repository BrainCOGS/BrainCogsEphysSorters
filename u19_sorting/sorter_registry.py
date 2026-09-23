""" Allow-list of pinned sorter versions a job may request.

    A job selects a sorter version with a registry key ("<sorter>@<version>") in the
    "sorter_version" field of its process params. Keys are resolved here, once, before the
    sorter runs; anything not in the registry is refused (no free-text env or image paths).

    Registry entries (sorter_registry.json, override with U19_SORTER_REGISTRY):

      native:    runs in the job's own python env; the installed package version must match.
                 {"mode": "native", "sorter": "kilosort4", "version": "4.1.7"}

      container: runs through SpikeInterface inside a pre-built Apptainer image.
                 {"mode": "container", "sorter": "kilosort3",
                  "image": "docker://spikeinterface/kilosort3-compiled-base:<tag>",
                  "sif": "<filename>.sif", "spikeinterface": "0.104.8"}

    Container images are never pulled on compute nodes (no internet there). They are built on
    a login node into the shared sif dir by `python -m u19_sorting.apptainer_cache`, and a
    missing image is an error here rather than a pull.

    Entries are append-only: never change an existing key, add a new one instead.
"""
import dataclasses
import json
import os
import pathlib
import re

import u19_sorting.config as config


NATIVE_SORTERS = {'kilosort4'}
CONTAINER_SORTERS = {'kilosort2', 'kilosort2_5', 'kilosort3', 'kilosort4'}

_KEY_RE = re.compile(r'^([a-z0-9_]+)@([A-Za-z0-9._+-]+)$')
_SIF_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*\.sif$')
_DIGEST_RE = re.compile(r'@sha256:[0-9a-f]{64}$')

_FIELDS = {
    'native':    {'mode', 'sorter', 'version', 'description'},
    'container': {'mode', 'sorter', 'image', 'sif', 'spikeinterface', 'description'},
}


class SorterRegistryError(ValueError):
    """ Invalid registry entry, or a job that doesn't match its registry entry. """


class UnknownSorterVersionError(SorterRegistryError):
    """ The requested key is not in the allow-list. """


class MissingSorterImageError(SorterRegistryError):
    """ The container image for a key has not been cached on shared storage. """


@dataclasses.dataclass(frozen=True)
class SorterEntry:
    key: str
    mode: str
    sorter: str
    version: str | None = None
    image: str | None = None
    sif: str | None = None
    spikeinterface: str | None = None
    description: str | None = None


@dataclasses.dataclass(frozen=True)
class ResolvedSorter:
    entry: SorterEntry
    sif_path: pathlib.Path | None = None

    def provenance(self):
        """ JSON-able record of exactly what ran, stored next to the sorter output. """

        prov = {'sorter_version': self.entry.key, 'sorter': self.entry.sorter, 'mode': self.entry.mode}
        if self.entry.mode == 'native':
            prov['version'] = self.entry.version
        else:
            prov['image'] = self.entry.image
            prov['spikeinterface'] = self.entry.spikeinterface
            prov['sif_path'] = str(self.sif_path)
            if self.sif_path.is_file():
                prov['sif_size_bytes'] = self.sif_path.stat().st_size
        return prov


def default_registry_file():
    return pathlib.Path(os.environ.get('U19_SORTER_REGISTRY', config.sorter_registry_file))


def default_sif_dir():
    return pathlib.Path(os.environ.get('U19_APPTAINER_SIF_DIR', config.apptainer_sif_dir))


def is_pinned_docker_image(image):
    """ docker://<ref> with an explicit tag other than `latest`, or a sha256 digest. """

    if not isinstance(image, str) or not image.startswith('docker://'):
        return False
    ref = image[len('docker://'):]
    if _DIGEST_RE.search(ref):
        return True
    # The tag lives in the last path component; a ':' earlier is a registry port.
    name, _, tag = ref.rpartition('/')[2].partition(':')
    return bool(name) and bool(tag) and tag != 'latest'


def parse_entry(key, raw):
    """ Validate one registry entry and return it as a SorterEntry. """

    if not isinstance(raw, dict):
        raise SorterRegistryError(f'{key!r}: entry must be an object, got {type(raw).__name__}')

    match = _KEY_RE.match(key) if isinstance(key, str) else None
    if not match:
        raise SorterRegistryError(f'{key!r}: key must look like "<sorter>@<version>"')

    mode = raw.get('mode')
    if mode not in _FIELDS:
        raise SorterRegistryError(f'{key}: mode must be one of {sorted(_FIELDS)}, got {mode!r}')

    unknown = set(raw) - _FIELDS[mode]
    if unknown:
        raise SorterRegistryError(f'{key}: unknown fields for {mode} mode: {sorted(unknown)}')

    sorter = raw.get('sorter')
    if sorter != match.group(1):
        raise SorterRegistryError(f'{key}: key prefix must equal the entry sorter ({sorter!r})')

    if mode == 'native':
        if sorter not in NATIVE_SORTERS:
            raise SorterRegistryError(f'{key}: {sorter} cannot run native, only {sorted(NATIVE_SORTERS)}')
        if not raw.get('version'):
            raise SorterRegistryError(f'{key}: native entries need the pinned package "version"')
    else:
        if sorter not in CONTAINER_SORTERS:
            raise SorterRegistryError(f'{key}: {sorter} is not a supported container sorter')
        if not is_pinned_docker_image(raw.get('image')):
            raise SorterRegistryError(
                f'{key}: image must be a docker:// reference pinned to a tag (not latest) or digest, '
                f'got {raw.get("image")!r}')
        if not isinstance(raw.get('sif'), str) or not _SIF_RE.match(raw['sif']):
            raise SorterRegistryError(f'{key}: sif must be a bare "<name>.sif" filename, got {raw.get("sif")!r}')
        if not raw.get('spikeinterface'):
            raise SorterRegistryError(f'{key}: container entries need the "spikeinterface" version baked into the image')

    return SorterEntry(key=key, **raw)


def load_registry(path=None):
    """ Load and validate the whole registry: {key: SorterEntry}. """

    path = pathlib.Path(path) if path is not None else default_registry_file()
    with open(path, 'r') as f:
        raw_registry = json.load(f)

    if not isinstance(raw_registry, dict):
        raise SorterRegistryError(f'{path}: registry must be a JSON object of key -> entry')

    registry = {key: parse_entry(key, raw) for key, raw in raw_registry.items()}

    sifs = [e.sif for e in registry.values() if e.sif]
    duplicated = sorted({s for s in sifs if sifs.count(s) > 1})
    if duplicated:
        raise SorterRegistryError(f'{path}: sif filenames shared by several keys: {duplicated}')

    return registry


def resolve(key, registry=None, sif_dir=None, check_image=True):
    """ Resolve an allow-listed key to what the job will run.

        For container entries the image is the absolute path of the cached .sif. When
        check_image is set, a missing or empty image raises MissingSorterImageError instead
        of letting SpikeInterface try to pull it.
    """

    if registry is None:
        registry = load_registry()

    if not isinstance(key, str) or key not in registry:
        raise UnknownSorterVersionError(f'sorter_version {key!r} is not in the registry; allowed: {sorted(registry)}')

    entry = registry[key]
    if entry.mode == 'native':
        return ResolvedSorter(entry)

    sif_dir = pathlib.Path(sif_dir) if sif_dir is not None else default_sif_dir()
    sif_path = (sif_dir / entry.sif).resolve()

    if check_image and (not sif_path.is_file() or sif_path.stat().st_size == 0):
        raise MissingSorterImageError(
            f'{key}: container image {sif_path} is not cached. Build it on a login node with '
            f'`python -m u19_sorting.apptainer_cache {key}`')

    return ResolvedSorter(entry, sif_path)
