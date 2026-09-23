""" Build the Apptainer images for containerized sorters into shared storage.

    Run on a login node (compute nodes have no internet), after adding a registry entry:

        python -m u19_sorting.apptainer_cache              # build every missing image
        python -m u19_sorting.apptainer_cache kilosort3@3.0.2
        python -m u19_sorting.apptainer_cache --check      # exit 1 if any image is missing

    Each image is the registry's pinned docker image plus the pinned SpikeInterface, so a
    job can run it with installation_mode="no-install" and never touch the network.
    Images are built to a temporary file and renamed into place read-only; an existing
    image is never rebuilt or overwritten.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import u19_sorting.config as config
import u19_sorting.sorter_registry as sr


def default_cache_dir():
    return pathlib.Path(os.environ.get('U19_APPTAINER_CACHEDIR', config.apptainer_cache_dir))


def definition_file_text(entry):
    """ Apptainer definition: the pinned base image with SpikeInterface installed on top. """

    if entry.mode != 'container':
        raise ValueError(f'{entry.key} is a {entry.mode} entry, it has no image to build')

    return (
        'Bootstrap: docker\n'
        f'From: {entry.image[len("docker://"):]}\n'
        '\n'
        '%post\n'
        f'    python -m pip install --no-cache-dir "spikeinterface[full]=={entry.spikeinterface}"\n'
        '\n'
        '%labels\n'
        f'    u19.sorter_version {entry.key}\n'
        f'    u19.base_image {entry.image}\n'
        f'    u19.spikeinterface {entry.spikeinterface}\n'
    )


def build_command(out_sif, definition_file, fakeroot=False):
    cmd = ['apptainer', 'build']
    if fakeroot:
        cmd.append('--fakeroot')
    return cmd + [str(out_sif), str(definition_file)]


def cache_entry(entry, sif_dir, cache_dir, runner=subprocess.run, dry_run=False, fakeroot=False):
    """ Build one registry entry's image into sif_dir unless it is already there.

        Returns 'native' (nothing to build), 'cached', 'would-build' (dry run) or 'built'.
    """

    if entry.mode != 'container':
        return 'native'

    sif_dir, cache_dir = pathlib.Path(sif_dir), pathlib.Path(cache_dir)
    final_sif = sif_dir / entry.sif
    # A 0-byte file is a broken copy that resolve() refuses, so it is rebuilt.
    if final_sif.is_file() and final_sif.stat().st_size > 0:
        return 'cached'
    if dry_run:
        return 'would-build'

    sif_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Build next to the final image (same filesystem) so the rename into place is atomic and
    # a job never sees a half-written image.
    build_dir = pathlib.Path(tempfile.mkdtemp(prefix='.build-' + entry.sif + '-', dir=sif_dir))
    try:
        definition_file = build_dir / 'image.def'
        definition_file.write_text(definition_file_text(entry))
        partial_sif = build_dir / entry.sif

        env = dict(os.environ)
        env['APPTAINER_CACHEDIR'] = str(cache_dir)
        env['SINGULARITY_CACHEDIR'] = str(cache_dir)
        # Build scratch on shared storage too: login-node /tmp is small.
        env.setdefault('APPTAINER_TMPDIR', str(build_dir))

        cmd = build_command(partial_sif, definition_file, fakeroot=fakeroot)
        print(entry.key, ':', ' '.join(cmd))
        result = runner(cmd, env=env)
        if result.returncode != 0:
            raise RuntimeError(f'{entry.key}: apptainer build failed (exit {result.returncode})')
        if not partial_sif.is_file() or partial_sif.stat().st_size == 0:
            raise RuntimeError(f'{entry.key}: apptainer build reported success but wrote no image')

        os.chmod(partial_sif, 0o444)
        os.replace(partial_sif, final_sif)
    finally:
        shutil.rmtree(build_dir, ignore_errors=True)

    return 'built'


def main(argv=None, runner=subprocess.run):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('keys', nargs='*', help='registry keys to build (default: every container entry)')
    parser.add_argument('--check', action='store_true', help='only report missing images; exit 1 if any')
    parser.add_argument('--dry-run', action='store_true', help='show what would be built')
    parser.add_argument('--fakeroot', action='store_true', help='pass --fakeroot to apptainer build')
    parser.add_argument('--registry', default=None, help='registry json (default: U19_SORTER_REGISTRY or the repo file)')
    parser.add_argument('--sif-dir', default=None, help='image dir (default: U19_APPTAINER_SIF_DIR or config)')
    parser.add_argument('--cache-dir', default=None, help='apptainer layer cache (default: U19_APPTAINER_CACHEDIR or config)')
    args = parser.parse_args(argv)

    registry = sr.load_registry(args.registry)
    sif_dir = pathlib.Path(args.sif_dir) if args.sif_dir else sr.default_sif_dir()
    cache_dir = pathlib.Path(args.cache_dir) if args.cache_dir else default_cache_dir()

    for key in args.keys:
        if key not in registry:
            raise sr.UnknownSorterVersionError(f'{key!r} is not in the registry; allowed: {sorted(registry)}')
    keys = args.keys or [key for key, entry in registry.items() if entry.mode == 'container']

    if args.check:
        missing = []
        for key in keys:
            try:
                sr.resolve(key, registry=registry, sif_dir=sif_dir)
            except sr.MissingSorterImageError:
                missing.append(key)
                print('MISSING', key, '->', sif_dir / registry[key].sif)
        if not missing:
            print('all', len(keys), 'images cached in', sif_dir)
        return 1 if missing else 0

    failures = 0
    for key in keys:
        try:
            status = cache_entry(registry[key], sif_dir, cache_dir, runner=runner,
                                 dry_run=args.dry_run, fakeroot=args.fakeroot)
        except RuntimeError as e:
            failures += 1
            print('FAILED', e)
            continue
        print(status, key)

    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
