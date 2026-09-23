""" sorter_main dispatch on the optional `sorter_version` registry key in the process params. """
import json

import pytest

import u19_sorting.config as config
import u19_sorting.sorter_registry as sr
import u19_sorting.sorter_wrappers as sw


NATIVE = {"mode": "native", "sorter": "kilosort4", "version": "4.1.7"}
CONTAINER = {
    "mode": "container",
    "sorter": "kilosort3",
    "image": "docker://spikeinterface/kilosort3-compiled-base:0.2.0",
    "sif": "ks3_0.2.0.sif",
    "spikeinterface": "0.104.8",
}


@pytest.fixture
def job(tmp_path, monkeypatch):
    """ A fake job: param files, registry, and sif dir under tmp_path; sorter runners recorded. """

    params_dir = tmp_path / "ParameterFiles"
    params_dir.mkdir()
    monkeypatch.setattr(config, "process_parameter_file", str(params_dir / "process_paramset_{}.json"))
    monkeypatch.setattr(config, "preprocess_parameter_file", str(params_dir / "preprocess_paramset_{}.json"))
    monkeypatch.setattr(config, "chanmap_file", str(tmp_path / "chanmap_{}.mat"))

    registry = tmp_path / "sorter_registry.json"
    registry.write_text(json.dumps({"kilosort4@4.1.7": NATIVE, "kilosort3@0.2.0": CONTAINER}))
    monkeypatch.setenv("U19_SORTER_REGISTRY", str(registry))
    sif_dir = tmp_path / "sif"
    sif_dir.mkdir()
    monkeypatch.setenv("U19_APPTAINER_SIF_DIR", str(sif_dir))

    calls = []
    monkeypatch.setattr(sw.Kilosort4, "run_Kilosort4", staticmethod(lambda *a: calls.append(("ks4", a))))
    monkeypatch.setattr(sw.Kilosort3, "run_Kilosort3", staticmethod(lambda *a: calls.append(("ks3", a))))

    def fake_container_run(resolved, raw_directory, output_directory, sorter_params):
        calls.append(("container", resolved, raw_directory, output_directory, dict(sorter_params)))
        out = output_directory / "sorter_output"
        out.mkdir(parents=True)
        return out

    monkeypatch.setattr(sw.SpikeInterfaceContainer, "run", staticmethod(fake_container_run))
    installed = {"kilosort": "4.1.7", "spikeinterface": "0.104.8"}
    monkeypatch.setattr(sw, "installed_version", lambda package: installed.get(package))

    class Job:
        pass

    j = Job()
    j.tmp_path, j.sif_dir, j.calls, j.installed = tmp_path, sif_dir, calls, installed
    j.raw = tmp_path / "raw"
    j.processed = tmp_path / "processed"

    def write_params(params, rp_id=1):
        with open(config.process_parameter_file.format(rp_id), "w") as f:
            json.dump(params, f)

    def read_params(rp_id=1):
        with open(config.process_parameter_file.format(rp_id)) as f:
            return json.load(f)

    def run(rp_id=1):
        return sw.sorter_main(rp_id, j.raw, j.processed)

    j.write_params, j.read_params, j.run = write_params, read_params, run
    return j


def provenance(directory):
    return json.loads((directory / sw.PROVENANCE_FILENAME).read_text())


def test_no_sorter_version_is_legacy_behavior(job):
    job.write_params({"clustering_method": "kilosort4", "Th_universal": 9})
    out = job.run()
    assert [c[0] for c in job.calls] == ["ks4"]
    assert out == job.processed / "kilosort4_output"
    assert job.read_params() == {"Th_universal": 9}
    assert not (out / sw.PROVENANCE_FILENAME).exists()


def test_null_sorter_version_is_legacy_behavior(job):
    job.write_params({"clustering_method": "kilosort4", "sorter_version": None})
    job.run()
    assert [c[0] for c in job.calls] == ["ks4"]
    # KS4 rejects unknown settings keys, so the key must not survive into the settings file
    assert "sorter_version" not in job.read_params()


def test_native_version_runs_in_host_env_and_stamps_provenance(job):
    job.write_params({"clustering_method": "kilosort4", "sorter_version": "kilosort4@4.1.7", "nblocks": 1})
    out = job.run()
    assert [c[0] for c in job.calls] == ["ks4"]
    assert job.read_params() == {"nblocks": 1}
    prov = provenance(out)
    assert prov["sorter_version"] == "kilosort4@4.1.7"
    assert prov["mode"] == "native"
    assert prov["installed_version"] == "4.1.7"


def test_native_version_mismatch_refuses_to_run(job):
    # The shared env was upgraded under us: results would silently differ from the pin.
    job.installed["kilosort"] = "4.2.0"
    job.write_params({"clustering_method": "kilosort4", "sorter_version": "kilosort4@4.1.7"})
    with pytest.raises(sr.SorterRegistryError, match="4.2.0"):
        job.run()
    assert job.calls == []


def test_native_version_not_installed_refuses_to_run(job):
    del job.installed["kilosort"]
    job.write_params({"clustering_method": "kilosort4", "sorter_version": "kilosort4@4.1.7"})
    with pytest.raises(sr.SorterRegistryError, match="not installed"):
        job.run()
    assert job.calls == []


def test_container_version_runs_cached_sif(job):
    sif = job.sif_dir / CONTAINER["sif"]
    sif.write_bytes(b"SIF")
    job.write_params({"clustering_method": "kilosort3", "sorter_version": "kilosort3@0.2.0", "detect_threshold": 6})
    out = job.run()

    assert [c[0] for c in job.calls] == ["container"]
    _, resolved, raw, output_dir, params = job.calls[0]
    assert resolved.sif_path == sif.resolve()
    assert raw == job.raw
    assert output_dir == job.processed / "kilosort3_output"
    assert params == {"detect_threshold": 6}
    # downstream (IBL, phy params shim) gets the raw Kilosort output folder
    assert out == job.processed / "kilosort3_output" / "sorter_output"
    prov = provenance(out)
    assert prov["mode"] == "container"
    assert prov["sif_path"] == str(sif.resolve())


@pytest.mark.parametrize("host_si", ["0.105.0", None])
def test_container_spikeinterface_mismatch_refuses_to_run(job, host_si):
    # The host serializes the recording and the in-image SpikeInterface loads it back:
    # the two versions must match.
    (job.sif_dir / CONTAINER["sif"]).write_bytes(b"SIF")
    if host_si is None:
        del job.installed["spikeinterface"]
    else:
        job.installed["spikeinterface"] = host_si
    job.write_params({"clustering_method": "kilosort3", "sorter_version": "kilosort3@0.2.0"})
    with pytest.raises(sr.SorterRegistryError, match="spikeinterface"):
        job.run()
    assert job.calls == []


def test_container_missing_sif_fails_before_running(job):
    job.write_params({"clustering_method": "kilosort3", "sorter_version": "kilosort3@0.2.0"})
    with pytest.raises(sr.MissingSorterImageError):
        job.run()
    assert job.calls == []


@pytest.mark.parametrize("key", ["kilosort4@9.9.9", "", "../../etc/passwd"])
def test_unknown_sorter_version_refused(job, key):
    job.write_params({"clustering_method": "kilosort4", "sorter_version": key})
    with pytest.raises(sr.UnknownSorterVersionError):
        job.run()
    assert job.calls == []


def test_sorter_version_must_match_clustering_method(job):
    (job.sif_dir / CONTAINER["sif"]).write_bytes(b"SIF")
    job.write_params({"clustering_method": "kilosort4", "sorter_version": "kilosort3@0.2.0"})
    with pytest.raises(sr.SorterRegistryError, match="clustering_method"):
        job.run()
    assert job.calls == []


# ----------------------------------------------------------------------------- run_sorter kwargs

def test_container_run_sorter_kwargs_are_offline(tmp_path):
    (tmp_path / CONTAINER["sif"]).write_bytes(b"SIF")
    registry = {"kilosort3@0.2.0": sr.parse_entry("kilosort3@0.2.0", CONTAINER)}
    resolved = sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path)

    kwargs = sw.SpikeInterfaceContainer.run_sorter_kwargs(resolved, tmp_path / "out", {"detect_threshold": 6})

    assert kwargs["sorter_name"] == "kilosort3"
    # absolute local path, never a docker:// reference => SpikeInterface never pulls
    assert kwargs["singularity_image"] == str((tmp_path / CONTAINER["sif"]).resolve())
    # SpikeInterface is baked into the cached image; "auto" would pip install from GitHub
    assert kwargs["installation_mode"] == "no-install"
    assert kwargs["folder"] == str(tmp_path / "out")
    assert kwargs["remove_existing_folder"] is True
    assert kwargs["detect_threshold"] == 6


def test_container_run_sorter_kwargs_reject_reserved_params(tmp_path):
    (tmp_path / CONTAINER["sif"]).write_bytes(b"SIF")
    registry = {"kilosort3@0.2.0": sr.parse_entry("kilosort3@0.2.0", CONTAINER)}
    resolved = sr.resolve("kilosort3@0.2.0", registry=registry, sif_dir=tmp_path)
    # a params file must not be able to swap the image or re-enable runtime installs
    for reserved in ("singularity_image", "docker_image", "installation_mode"):
        with pytest.raises(ValueError, match=reserved):
            sw.SpikeInterfaceContainer.run_sorter_kwargs(resolved, tmp_path / "out", {reserved: "x"})


# ----------------------------------------------------------------------------- DREDge + container

KS2 = {**CONTAINER, "sorter": "kilosort2", "sif": "ks2.sif"}
KS2_5 = {**CONTAINER, "sorter": "kilosort2_5", "sif": "ks2_5.sif"}


def enable_dredge(disable_sorter_drift=True, rp_id=1):
    with open(config.preprocess_parameter_file.format(rp_id), "w") as f:
        json.dump([{"catgt": {}}, {"dredge": {"disable_sorter_drift": disable_sorter_drift}}], f)


@pytest.fixture
def container_job(job, monkeypatch, tmp_path):
    registry = {"kilosort3@0.2.0": CONTAINER, "kilosort2@0.2.0": KS2, "kilosort2_5@0.2.0": KS2_5}
    path = tmp_path / "container_registry.json"
    path.write_text(json.dumps(registry))
    monkeypatch.setenv("U19_SORTER_REGISTRY", str(path))
    for raw in registry.values():
        (job.sif_dir / raw["sif"]).write_bytes(b"SIF")
    return job


@pytest.mark.parametrize("method", ["kilosort3", "kilosort2_5"])
def test_dredge_disables_drift_with_spikeinterface_param(container_job, method):
    # Inside SpikeInterface the switch is do_correction; raw KS ops (nblocks) alone would leave
    # KS2.5's datashift on and correct motion twice.
    enable_dredge()
    container_job.write_params({"clustering_method": method, "sorter_version": method + "@0.2.0"})
    container_job.run()
    params = container_job.calls[0][4]
    assert params["do_correction"] is False
    assert "reorder" not in params


def test_dredge_kilosort2_container_adds_no_unknown_params(container_job):
    # SpikeInterface's kilosort2 has no drift parameter; `reorder` would be rejected as unknown.
    enable_dredge()
    container_job.write_params({"clustering_method": "kilosort2", "sorter_version": "kilosort2@0.2.0"})
    container_job.run()
    assert container_job.calls[0][4] == {}


def test_dredge_keep_sorter_drift_leaves_container_params(container_job):
    enable_dredge(disable_sorter_drift=False)
    container_job.write_params({"clustering_method": "kilosort3", "sorter_version": "kilosort3@0.2.0"})
    container_job.run()
    assert container_job.calls[0][4] == {}


def test_dredge_native_kilosort4_still_uses_nblocks(job):
    enable_dredge()
    job.write_params({"clustering_method": "kilosort4", "sorter_version": "kilosort4@4.1.7"})
    job.run()
    # KS4 native rejects do_correction (not a KS4 setting)
    assert job.read_params() == {"nblocks": 0}
