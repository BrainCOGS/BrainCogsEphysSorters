import json
import pathlib

import pytest

import u19_sorting.sorter_registry as sr


NATIVE = {"mode": "native", "sorter": "kilosort4", "version": "4.1.7"}
CONTAINER = {
    "mode": "container",
    "sorter": "kilosort3",
    "image": "docker://spikeinterface/kilosort3-compiled-base:0.2.0",
    "sif": "kilosort3-compiled-base_0.2.0_si-0.104.8.sif",
    "spikeinterface": "0.104.8",
}


def write_registry(tmp_path, entries):
    path = tmp_path / "sorter_registry.json"
    path.write_text(json.dumps(entries))
    return path


# ----------------------------------------------------------------------------- parse_entry

def test_parse_native_entry():
    entry = sr.parse_entry("kilosort4@4.1.7", NATIVE)
    assert entry.mode == "native"
    assert entry.sorter == "kilosort4"
    assert entry.version == "4.1.7"
    assert entry.image is None and entry.sif is None


def test_parse_container_entry():
    entry = sr.parse_entry("kilosort3@0.2.0", CONTAINER)
    assert entry.mode == "container"
    assert entry.image == CONTAINER["image"]
    assert entry.spikeinterface == "0.104.8"


def test_description_is_allowed():
    entry = sr.parse_entry("kilosort4@4.1.7", {**NATIVE, "description": "default"})
    assert entry.description == "default"


@pytest.mark.parametrize("key", ["kilosort4", "kilosort4@", "@4.1.7", "", "kilosort4@4.1.7@x"])
def test_key_must_be_sorter_at_version(key):
    with pytest.raises(sr.SorterRegistryError):
        sr.parse_entry(key, NATIVE)


def test_key_sorter_must_match_entry_sorter():
    with pytest.raises(sr.SorterRegistryError, match="sorter"):
        sr.parse_entry("kilosort3@4.1.7", NATIVE)


def test_unknown_mode_rejected():
    with pytest.raises(sr.SorterRegistryError, match="mode"):
        sr.parse_entry("kilosort4@4.1.7", {**NATIVE, "mode": "conda"})


def test_unknown_field_rejected():
    # Typos (e.g. "imgae") must not be silently ignored.
    with pytest.raises(sr.SorterRegistryError, match="imgae"):
        sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "imgae": "x"})


def test_entry_must_be_a_dict():
    with pytest.raises(sr.SorterRegistryError):
        sr.parse_entry("kilosort4@4.1.7", None)


def test_native_requires_version():
    raw = {k: v for k, v in NATIVE.items() if k != "version"}
    with pytest.raises(sr.SorterRegistryError, match="version"):
        sr.parse_entry("kilosort4@4.1.7", raw)


def test_native_only_for_python_sorters():
    # MATLAB sorters can't be version pinned natively (license + module load): container only.
    with pytest.raises(sr.SorterRegistryError, match="native"):
        sr.parse_entry("kilosort3@x", {"mode": "native", "sorter": "kilosort3", "version": "x"})


def test_native_must_not_have_image():
    with pytest.raises(sr.SorterRegistryError, match="image"):
        sr.parse_entry("kilosort4@4.1.7", {**NATIVE, "image": CONTAINER["image"]})


@pytest.mark.parametrize("missing", ["image", "sif", "spikeinterface"])
def test_container_requires_fields(missing):
    raw = {k: v for k, v in CONTAINER.items() if k != missing}
    with pytest.raises(sr.SorterRegistryError, match=missing):
        sr.parse_entry("kilosort3@0.2.0", raw)


@pytest.mark.parametrize("image", [
    "spikeinterface/kilosort3-compiled-base:0.2.0",          # no docker:// scheme
    "docker://spikeinterface/kilosort3-compiled-base",       # untagged == latest
    "docker://spikeinterface/kilosort3-compiled-base:latest",
    "docker://localhost:5000/kilosort3-compiled-base",       # port, but no tag
    "https://example.com/ks3.sif",
    "",
])
def test_container_image_must_be_pinned_docker_ref(image):
    with pytest.raises(sr.SorterRegistryError, match="image"):
        sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "image": image})


def test_container_image_digest_is_pinned():
    image = "docker://spikeinterface/kilosort3-compiled-base@sha256:" + "a" * 64
    entry = sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "image": image})
    assert entry.image == image


def test_container_image_registry_port_and_tag():
    image = "docker://localhost:5000/kilosort3-compiled-base:0.2.0"
    assert sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "image": image}).image == image


@pytest.mark.parametrize("sif", [
    "/scratch/gpfs/other/ks3.sif",   # absolute path: sif dir is fixed by config
    "../ks3.sif",                    # traversal
    "sub/ks3.sif",
    "docker://spikeinterface/ks3",
    "ks3.img",
    ".sif",
    "",
])
def test_container_sif_must_be_bare_sif_filename(sif):
    with pytest.raises(sr.SorterRegistryError, match="sif"):
        sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "sif": sif})


# ----------------------------------------------------------------------------- load_registry

def test_load_registry(tmp_path):
    path = write_registry(tmp_path, {"kilosort4@4.1.7": NATIVE, "kilosort3@0.2.0": CONTAINER})
    registry = sr.load_registry(path)
    assert set(registry) == {"kilosort4@4.1.7", "kilosort3@0.2.0"}


def test_load_registry_empty(tmp_path):
    assert sr.load_registry(write_registry(tmp_path, {})) == {}


def test_load_registry_rejects_non_object(tmp_path):
    with pytest.raises(sr.SorterRegistryError):
        sr.load_registry(write_registry(tmp_path, [NATIVE]))


def test_load_registry_rejects_duplicate_sif(tmp_path):
    # Two keys sharing one .sif would let one entry silently change another's image.
    other = {**CONTAINER, "image": "docker://spikeinterface/kilosort3-compiled-base:0.3.0"}
    path = write_registry(tmp_path, {"kilosort3@0.2.0": CONTAINER, "kilosort3@0.3.0": other})
    with pytest.raises(sr.SorterRegistryError, match="sif"):
        sr.load_registry(path)


def test_load_registry_env_override(tmp_path, monkeypatch):
    path = write_registry(tmp_path, {"kilosort4@4.1.7": NATIVE})
    monkeypatch.setenv("U19_SORTER_REGISTRY", str(path))
    assert list(sr.load_registry()) == ["kilosort4@4.1.7"]


def test_repository_registry_is_valid():
    # The committed allow-list must always parse.
    sr.load_registry(sr.default_registry_file())


# ----------------------------------------------------------------------------- resolve

@pytest.fixture
def registry():
    return {
        "kilosort4@4.1.7": sr.parse_entry("kilosort4@4.1.7", NATIVE),
        "kilosort3@0.2.0": sr.parse_entry("kilosort3@0.2.0", CONTAINER),
    }


@pytest.mark.parametrize("key", ["kilosort4@9.9.9", "", None, "KILOSORT4@4.1.7", " kilosort4@4.1.7"])
def test_resolve_unknown_key_refused(registry, tmp_path, key):
    with pytest.raises(sr.UnknownSorterVersionError):
        sr.resolve(key, registry=registry, sif_dir=tmp_path)


def test_resolve_native_has_no_sif(registry, tmp_path):
    resolved = sr.resolve("kilosort4@4.1.7", registry=registry, sif_dir=tmp_path)
    assert resolved.entry.mode == "native"
    assert resolved.sif_path is None


def test_resolve_container_returns_absolute_local_sif(registry, tmp_path):
    (tmp_path / CONTAINER["sif"]).write_bytes(b"sif")
    resolved = sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path)
    assert resolved.sif_path == (tmp_path / CONTAINER["sif"]).resolve()
    assert resolved.sif_path.is_absolute()


def test_resolve_container_missing_sif_fails_fast(registry, tmp_path):
    # Compute nodes are offline: a missing image must error, never fall back to a pull.
    with pytest.raises(sr.MissingSorterImageError, match="apptainer_cache"):
        sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path)


def test_resolve_container_empty_sif_fails_fast(registry, tmp_path):
    # A 0-byte file is a leftover from an interrupted copy, not a usable image.
    (tmp_path / CONTAINER["sif"]).write_bytes(b"")
    with pytest.raises(sr.MissingSorterImageError):
        sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path)


def test_resolve_container_skip_image_check(registry, tmp_path):
    resolved = sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path, check_image=False)
    assert resolved.sif_path == (tmp_path / CONTAINER["sif"]).resolve()


def test_resolve_relative_sif_dir_is_made_absolute(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / CONTAINER["sif"]).write_bytes(b"sif")
    resolved = sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=pathlib.Path("."))
    assert resolved.sif_path.is_absolute()


def test_provenance_container(registry, tmp_path):
    (tmp_path / CONTAINER["sif"]).write_bytes(b"sif")
    prov = sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path).provenance()
    assert prov["sorter_version"] == "kilosort3@0.2.0"
    assert prov["mode"] == "container"
    assert prov["image"] == CONTAINER["image"]
    assert prov["sif_path"] == str((tmp_path / CONTAINER["sif"]).resolve())
    assert prov["sif_size_bytes"] == 3
    assert prov["spikeinterface"] == "0.104.8"
    json.dumps(prov)


def test_provenance_native(registry, tmp_path):
    prov = sr.resolve("kilosort4@4.1.7", registry=registry, sif_dir=tmp_path).provenance()
    assert prov == {"sorter_version": "kilosort4@4.1.7", "sorter": "kilosort4", "mode": "native", "version": "4.1.7"}
