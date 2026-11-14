#!/bin/bash
# Build the Apptainer image of a container entry of sorter_registry.json, without root.
#
#   scripts/sorter_image.sh fetch <key>           # login node (internet), ~10 min
#   sbatch scripts/sorter_image.sh build <key>    # compute node (offline), ~6 min
#
# Why not `python -m u19_sorting.apptainer_cache` (a definition file with %post):
# - the SpikeInterface Kilosort images ship Python 3.9 and spikeinterface >= 0.104 needs
#   Python >= 3.10, so `pip install spikeinterface==<lock version>` cannot work in them;
# - on spock users have no /etc/subuid entry, so %post runs under apptainer's bundled fakeroot,
#   which needs a newer glibc than these images have ("GLIBC_2.34 not found ... faked");
# - unpacking and packing ~8 GB of small files on the login VM or on NFS takes hours.
# Instead: `fetch` puts the image layers in the apptainer layer cache and the wheels in the uv
# cache; `build` unpacks the image on the node's local disk, adds a uv Python 3.13 venv with the
# spikeinterface, neo and probeinterface versions of uv.lock (first on PATH, so SpikeInterface
# runs from it while the sorter keeps the image's own runtime), packs it with mksquashfs and
# wraps it in a SIF. The image is written to the sif dir under a temporary name and renamed
# into place read-only; an existing image is never replaced.
#
# Run from the checkout, with its uv environment (.venv) synced. Directories as in config.py
# (U19_APPTAINER_SIF_DIR / U19_APPTAINER_CACHEDIR override them); UV_CACHE_DIR as for the job.
#SBATCH --job-name=sorter_image
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=6
#SBATCH --mem=24G
#SBATCH --time=01:30:00
#SBATCH --mail-type=NONE
set -euo pipefail
umask 002

step=${1:?fetch or build}
key=${2:?registry key, e.g. kilosort2@2.0.2}
repo=${SLURM_SUBMIT_DIR:-$PWD}
cd "$repo"
py=.venv/bin/python

read -r image sif sif_dir cache_dir < <("$py" - "$key" <<'PY'
import sys
import u19_sorting.apptainer_cache as ac
import u19_sorting.sorter_registry as sr
entry = sr.load_registry()[sys.argv[1]]
if entry.mode != "container":
    sys.exit(f"{entry.key} is a {entry.mode} entry, it has no image")
print(entry.image, entry.sif, sr.default_sif_dir(), ac.default_cache_dir())
PY
)
spikeinterface=$("$py" -c "import importlib.metadata as m; print(m.version('spikeinterface'))")
pins=("spikeinterface[full]==$spikeinterface")
for package in neo probeinterface numpy; do
  pins+=("$package==$("$py" -c "import importlib.metadata as m; print(m.version('$package'))")")
done
python_dir=$(dirname "$(dirname "$(readlink -f "$py")")")   # the uv Python of .venv
export APPTAINER_CACHEDIR=$cache_dir
mkdir -p "$sif_dir" "$cache_dir"
requirements=$cache_dir/$key.requirements.txt

case $step in
fetch)
  # Layers into the apptainer cache: unpack once on local /tmp, then drop the unpacked copy.
  work=$(mktemp -d /tmp/sorter_image.XXXXXX); trap 'chmod -R u+w "$work"; rm -rf "$work"' EXIT
  APPTAINER_TMPDIR=$work apptainer build --sandbox "$work/sandbox" "$image"
  # Exact versions for the image's venv, and their wheels into the uv cache.
  printf '%s\n' "${pins[@]}" > "$work/requirements.in"
  uv pip compile -q --python-version 3.13 --python-platform x86_64-manylinux_2_28 \
    "$work/requirements.in" -o "$requirements"
  uv venv -q "$work/prefetch" --python "$python_dir/bin/python3"
  uv pip install -q --python "$work/prefetch/bin/python" -r "$requirements"
  echo "fetched $key: $image; next: sbatch scripts/sorter_image.sh build $key"
  ;;
build)
  final=$sif_dir/$sif
  if [ -s "$final" ]; then echo "$final exists, not rebuilt"; exit 0; fi
  work=$(mktemp -d "${TMPDIR:-/tmp}/sorter_image.XXXXXX"); trap 'chmod -R u+w "$work"; rm -rf "$work"' EXIT
  export APPTAINER_TMPDIR=$work
  apptainer build --sandbox "$work/sandbox" "oci:$cache_dir/cache/blob@${image##*@}"
  sb=$work/sandbox
  mkdir -p "$sb/opt/uv-python" "$sb/uvcache" "$sb/build"
  cp "$(command -v uv)" "$sb/usr/local/bin/uv"
  cp -a "$python_dir" "$sb/opt/uv-python/"
  cp "$requirements" "$sb/build/requirements.txt"
  apptainer exec --writable --no-home --cleanenv -B "${UV_CACHE_DIR:-$HOME/.cache/uv}:/uvcache" \
    --env UV_CACHE_DIR=/uvcache,UV_LINK_MODE=copy "$sb" sh -c "
      set -e
      uv venv -q /opt/si-venv --python /opt/uv-python/$(basename "$python_dir")/bin/python3
      uv pip install -q --offline --python /opt/si-venv/bin/python -r /build/requirements.txt"
  rm -rf "$sb/build" "$sb/uvcache"
  printf '%s\n' "# SpikeInterface runs from its own Python (uv), ahead of the image's Python" \
    'export PATH="/opt/si-venv/bin:$PATH"' > "$sb/.singularity.d/env/99-zz-u19-si-python.sh"
  apptainer exec --no-home --cleanenv "$sb" python -c \
    "import spikeinterface, sys; assert spikeinterface.__version__ == '$spikeinterface', spikeinterface.__version__; print(sys.version.split()[0], spikeinterface.__version__)"
  mksquashfs "$sb" "$work/rootfs.squashfs" -all-root -comp gzip \
    -processors "${SLURM_CPUS_PER_TASK:-4}" -noappend -quiet -no-progress
  apptainer sif new "$work/image.sif"
  apptainer sif add "$work/image.sif" "$work/rootfs.squashfs" \
    --datatype 4 --parttype 2 --partfs 1 --partarch 2 --groupid 1
  cp "$work/image.sif" "$final.partial.$$"
  chmod 444 "$final.partial.$$"
  mv -n "$final.partial.$$" "$final"
  rm -f "$final.partial.$$"
  ls -l "$final"
  ;;
*) echo "unknown step $step (fetch or build)" >&2; exit 2 ;;
esac
