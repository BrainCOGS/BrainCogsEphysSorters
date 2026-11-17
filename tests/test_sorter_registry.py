import json
import pathlib
import tomllib

import pytest

import u19_sorting.sorter_registry as sr

NATIVE = {"mode": "native", "sorter": "kilosort4", "version": "4.1.7"}
CONTAINER = {
    "mode": "container",
    "sorter": "kilosort3",
    "image": "docker://spikeinterface/kilosort3-compiled-base:0.2.0",
    "digest": "sha256:" + "a" * 64,
}
# The job's SpikeInterface in these tests, and the image file built for it.
HOST_SI = "0.104.8"
SIF = "kilosort3-compiled-base_0.2.0_si-0.104.8.sif"


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
    assert entry.image is None and entry.digest is None


def test_parse_container_entry():
    entry = sr.parse_entry("kilosort3@0.2.0", CONTAINER)
    assert entry.mode == "container"
    assert entry.image == CONTAINER["image"]
    assert entry.digest == CONTAINER["digest"]


def test_container_entry_pulls_by_digest():
    entry = sr.parse_entry("kilosort3@0.2.0", CONTAINER)
    assert entry.pull_ref == (
        "docker://spikeinterface/kilosort3-compiled-base@sha256:" + "a" * 64
    )


def test_container_image_name_follows_the_spikeinterface_version():
    entry = sr.parse_entry("kilosort3@0.2.0", CONTAINER)
    assert entry.sif_name("0.104.8") == SIF
    assert entry.sif_name("0.106.1") == "kilosort3-compiled-base_0.2.0_si-0.106.1.sif"
    assert entry.sif_version(SIF) == "0.104.8"
    assert entry.sif_version("kilosort2-compiled-base_0.2.0_si-0.104.8.sif") is None


@pytest.mark.parametrize("version", [None, "", "../0.1.0", "0.1/0"])
def test_container_image_name_needs_a_version(version):
    entry = sr.parse_entry("kilosort3@0.2.0", CONTAINER)
    with pytest.raises(sr.SorterRegistryError):
        entry.sif_name(version)


def test_image_name_keeps_the_tag_of_a_name_with_underscores():
    raw = {
        **CONTAINER,
        "sorter": "kilosort2_5",
        "image": "docker://spikeinterface/kilosort2_5-compiled-base:2.5.2_cuda-11.2.2",
    }
    entry = sr.parse_entry("kilosort2_5@2.5.2", raw)
    assert (
        entry.sif_name("0.105.0")
        == "kilosort2_5-compiled-base_2.5.2_cuda-11.2.2_si-0.105.0.sif"
    )


def test_description_is_allowed():
    entry = sr.parse_entry("kilosort4@4.1.7", {**NATIVE, "description": "default"})
    assert entry.description == "default"


@pytest.mark.parametrize(
    "key", ["kilosort4", "kilosort4@", "@4.1.7", "", "kilosort4@4.1.7@x"]
)
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
        sr.parse_entry(
            "kilosort3@x", {"mode": "native", "sorter": "kilosort3", "version": "x"}
        )


def test_native_must_not_have_image():
    with pytest.raises(sr.SorterRegistryError, match="image"):
        sr.parse_entry("kilosort4@4.1.7", {**NATIVE, "image": CONTAINER["image"]})


@pytest.mark.parametrize("missing", ["image", "digest"])
def test_container_requires_fields(missing):
    raw = {k: v for k, v in CONTAINER.items() if k != missing}
    with pytest.raises(sr.SorterRegistryError, match=missing):
        sr.parse_entry("kilosort3@0.2.0", raw)


@pytest.mark.parametrize(
    "image",
    [
        "spikeinterface/kilosort3-compiled-base:0.2.0",  # no docker:// scheme
        "docker://spikeinterface/kilosort3-compiled-base",  # untagged == latest
        "docker://spikeinterface/kilosort3-compiled-base:latest",
        "docker://localhost:5000/kilosort3-compiled-base",  # port, but no tag
        # the digest has a field of its own; the tag names the image file
        "docker://spikeinterface/kilosort3-compiled-base@sha256:" + "a" * 64,
        "docker://spikeinterface/kilosort3-compiled-base:0.2.0@sha256:" + "a" * 64,
        "https://example.com/ks3.sif",
        "",
    ],
)
def test_container_image_must_be_tagged_docker_ref(image):
    with pytest.raises(sr.SorterRegistryError, match="image"):
        sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "image": image})


def test_container_image_registry_port_and_tag():
    image = "docker://localhost:5000/kilosort3-compiled-base:0.2.0"
    entry = sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "image": image})
    assert entry.image == image
    assert entry.pull_ref == "docker://localhost:5000/kilosort3-compiled-base@" + (
        "sha256:" + "a" * 64
    )


@pytest.mark.parametrize(
    "digest",
    ["a" * 64, "sha256:" + "a" * 63, "sha256:" + "A" * 64, "sha512:" + "a" * 64, ""],
)
def test_container_digest_must_be_sha256(digest):
    with pytest.raises(sr.SorterRegistryError, match="digest"):
        sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, "digest": digest})


@pytest.mark.parametrize("field", ["sif", "spikeinterface"])
def test_container_entry_no_longer_pins_spikeinterface(field):
    # The image file and its SpikeInterface follow the job's environment.
    with pytest.raises(sr.SorterRegistryError, match=field):
        sr.parse_entry("kilosort3@0.2.0", {**CONTAINER, field: "x"})


# ----------------------------------------------------------------------------- load_registry


def test_load_registry(tmp_path):
    path = write_registry(
        tmp_path, {"kilosort4@4.1.7": NATIVE, "kilosort3@0.2.0": CONTAINER}
    )
    registry = sr.load_registry(path)
    assert set(registry) == {"kilosort4@4.1.7", "kilosort3@0.2.0"}


def test_load_registry_empty(tmp_path):
    assert sr.load_registry(write_registry(tmp_path, {})) == {}


def test_load_registry_rejects_non_object(tmp_path):
    with pytest.raises(sr.SorterRegistryError):
        sr.load_registry(write_registry(tmp_path, [NATIVE]))


def test_load_registry_rejects_shared_image_name(tmp_path):
    # Two keys with one image name and tag would share their .sif files.
    other = {**CONTAINER, "digest": "sha256:" + "b" * 64}
    path = write_registry(
        tmp_path, {"kilosort3@0.2.0": CONTAINER, "kilosort3@0.2.1": other}
    )
    with pytest.raises(sr.SorterRegistryError, match="image name"):
        sr.load_registry(path)


def test_load_registry_env_override(tmp_path, monkeypatch):
    path = write_registry(tmp_path, {"kilosort4@4.1.7": NATIVE})
    monkeypatch.setenv("U19_SORTER_REGISTRY", str(path))
    assert list(sr.load_registry()) == ["kilosort4@4.1.7"]


def locked_version(package):
    lock = tomllib.loads(
        (pathlib.Path(__file__).parents[1] / "uv.lock").read_text(encoding="utf-8")
    )
    (version,) = [p["version"] for p in lock["package"] if p["name"] == package]
    return version


def test_container_images_follow_the_locked_spikeinterface(tmp_path):
    """Whatever SpikeInterface uv.lock installs, each container entry resolves to the image
    built for it, under its own name, without editing the registry."""
    locked = locked_version("spikeinterface")
    containers = {k: e for k, e in sr.load_registry().items() if e.mode == "container"}

    assert containers
    names = {key: entry.sif_name(locked) for key, entry in containers.items()}
    assert len(set(names.values())) == len(names)
    for key, name in names.items():
        assert name.endswith(f"_si-{locked}.sif"), key
        (tmp_path / name).write_bytes(b"SIF")
        resolved = sr.resolve(key, sif_dir=tmp_path, spikeinterface_version=locked)
        assert resolved.sif_path == (tmp_path / name).resolve()
        assert resolved.spikeinterface == locked


def test_native_entries_match_the_locked_sorter():
    from u19_sorting.sorter_wrappers import NATIVE_PACKAGES

    for key, entry in sr.load_registry().items():
        if entry.mode == "native":
            assert entry.version == locked_version(NATIVE_PACKAGES[entry.sorter]), key


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


@pytest.mark.parametrize(
    "key", ["kilosort4@9.9.9", "", None, "KILOSORT4@4.1.7", " kilosort4@4.1.7"]
)
def test_resolve_unknown_key_refused(registry, tmp_path, key):
    with pytest.raises(sr.UnknownSorterVersionError):
        sr.resolve(key, registry=registry, sif_dir=tmp_path)


def test_resolve_native_has_no_sif(registry, tmp_path):
    resolved = sr.resolve("kilosort4@4.1.7", registry=registry, sif_dir=tmp_path)
    assert resolved.entry.mode == "native"
    assert resolved.sif_path is None


def test_resolve_container_returns_absolute_local_sif(registry, tmp_path):
    (tmp_path / SIF).write_bytes(b"sif")
    resolved = sr.resolve(
        "kilosort3@0.2.0",
        registry=registry,
        sif_dir=tmp_path,
        spikeinterface_version=HOST_SI,
    )
    assert resolved.sif_path == (tmp_path / SIF).resolve()
    assert resolved.sif_path.is_absolute()


def test_resolve_container_missing_sif_fails_fast(registry, tmp_path):
    # Compute nodes are offline: a missing image must error, never fall back to a pull,
    # and say how to build the image.
    with pytest.raises(sr.MissingSorterImageError) as error:
        sr.resolve(
            "kilosort3@0.2.0",
            registry=registry,
            sif_dir=tmp_path,
            spikeinterface_version=HOST_SI,
        )
    message = str(error.value)
    assert SIF in message
    assert "`scripts/sorter_image.sh fetch kilosort3@0.2.0`" in message
    assert "`sbatch scripts/sorter_image.sh build kilosort3@0.2.0`" in message


def image_for(tmp_path, version):
    path = tmp_path / f"kilosort3-compiled-base_0.2.0_si-{version}.sif"
    path.write_bytes(b"SIF")
    return path.resolve()


def resolve_with_host(registry, tmp_path, host):
    return sr.resolve(
        "kilosort3@0.2.0",
        registry=registry,
        sif_dir=tmp_path,
        spikeinterface_version=host,
    )


def test_resolve_prefers_the_image_of_the_host_version(registry, tmp_path):
    image_for(tmp_path, "0.105.0")
    exact = image_for(tmp_path, "0.105.1")
    resolved = resolve_with_host(registry, tmp_path, "0.105.1")  # no warning
    assert (resolved.sif_path, resolved.spikeinterface) == (exact, "0.105.1")


@pytest.mark.parametrize("host", ["0.105.3", "0.105.0"])
def test_resolve_patch_difference_warns_and_runs(registry, tmp_path, host):
    image_for(tmp_path, "0.104.9")
    image_for(tmp_path, "0.105.1")
    newest = image_for(tmp_path, "0.105.2")
    with pytest.warns(sr.SorterImageVersionWarning, match="patch") as record:
        resolved = resolve_with_host(registry, tmp_path, host)
    assert (resolved.sif_path, resolved.spikeinterface) == (newest, "0.105.2")
    assert "sorter_image.sh build kilosort3@0.2.0" in str(record[0].message)
    assert resolved.provenance()["spikeinterface"] == "0.105.2"


@pytest.mark.parametrize("host", ["0.106.0", "0.104.8", "1.105.0"])
def test_resolve_minor_difference_refuses(registry, tmp_path, host):
    image_for(tmp_path, "0.105.0")
    with pytest.raises(sr.MissingSorterImageError) as error:
        resolve_with_host(registry, tmp_path, host)
    message = str(error.value)
    assert "0.105.0" in message  # says which image it did not use
    assert f"kilosort3-compiled-base_0.2.0_si-{host}.sif" in message
    assert "sorter_image.sh fetch kilosort3@0.2.0" in message


def test_resolve_ignores_other_entries_and_empty_images(registry, tmp_path):
    (tmp_path / "kilosort2-compiled-base_0.2.0_si-0.105.0.sif").write_bytes(b"SIF")
    (tmp_path / "kilosort3-compiled-base_0.2.0_si-0.105.1.sif").write_bytes(b"")
    with pytest.raises(sr.MissingSorterImageError):
        resolve_with_host(registry, tmp_path, "0.105.0")


@pytest.mark.parametrize("host", [None, "", "unknown"])
def test_resolve_container_needs_host_spikeinterface(
    registry, tmp_path, monkeypatch, host
):
    # None means "the installed one", here: not installed
    monkeypatch.setattr(sr, "installed_spikeinterface", lambda: None)
    image_for(tmp_path, "0.105.0")
    with pytest.raises(sr.SorterRegistryError, match="spikeinterface"):
        resolve_with_host(registry, tmp_path, host)


def test_resolve_defaults_to_the_installed_spikeinterface(
    registry, tmp_path, monkeypatch
):
    monkeypatch.setattr(sr, "installed_spikeinterface", lambda: "0.105.0")
    exact = image_for(tmp_path, "0.105.0")
    resolved = sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path)
    assert resolved.sif_path == exact


def test_resolve_container_empty_sif_fails_fast(registry, tmp_path):
    # A 0-byte file is a leftover from an interrupted copy, not a usable image.
    (tmp_path / SIF).write_bytes(b"")
    with pytest.raises(sr.MissingSorterImageError):
        sr.resolve(
            "kilosort3@0.2.0",
            registry=registry,
            sif_dir=tmp_path,
            spikeinterface_version=HOST_SI,
        )


def test_resolve_container_skip_image_check(registry, tmp_path):
    resolved = sr.resolve(
        "kilosort3@0.2.0",
        registry=registry,
        sif_dir=tmp_path,
        check_image=False,
        spikeinterface_version=HOST_SI,
    )
    assert resolved.sif_path == (tmp_path / SIF).resolve()


def test_resolve_relative_sif_dir_is_made_absolute(registry, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / SIF).write_bytes(b"sif")
    resolved = sr.resolve(
        "kilosort3@0.2.0",
        registry=registry,
        sif_dir=pathlib.Path("."),
        spikeinterface_version=HOST_SI,
    )
    assert resolved.sif_path.is_absolute()


def test_provenance_container(registry, tmp_path):
    (tmp_path / SIF).write_bytes(b"sif")
    prov = sr.resolve(
        "kilosort3@0.2.0",
        registry=registry,
        sif_dir=tmp_path,
        spikeinterface_version=HOST_SI,
    ).provenance()
    assert prov["sorter_version"] == "kilosort3@0.2.0"
    assert prov["mode"] == "container"
    assert prov["image"] == (
        "docker://spikeinterface/kilosort3-compiled-base@sha256:" + "a" * 64
    )
    assert prov["sif_path"] == str((tmp_path / SIF).resolve())
    assert prov["sif_size_bytes"] == 3
    assert prov["spikeinterface"] == "0.104.8"
    json.dumps(prov)


def test_provenance_native(registry, tmp_path):
    prov = sr.resolve(
        "kilosort4@4.1.7", registry=registry, sif_dir=tmp_path
    ).provenance()
    assert prov == {
        "sorter_version": "kilosort4@4.1.7",
        "sorter": "kilosort4",
        "mode": "native",
        "version": "4.1.7",
    }
