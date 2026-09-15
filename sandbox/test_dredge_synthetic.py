"""Ground-truth accuracy check for the DREDge preprocessing stage.

Generates a synthetic drifting Neuropixels-style recording with a known displacement,
stores it as int16 (like SpikeGLX/CatGT output), runs u19_sorting's run_dredge on it and
reports:

  1. motion accuracy : estimated vs injected displacement (RMS / max error, um)
  2. residual drift  : motion re-estimated on the corrected output (should be ~flat)
  3. rounding error  : int16 file vs the float corrected traces (must be <= 0.5 count)

Run from the repo root (needs the uv env):
    uv run python sandbox/test_dredge_synthetic.py [--duration 40] [--device cpu|cuda]
"""

import argparse
import pathlib
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, pathlib.Path(__file__).resolve().parents[1].as_posix())

import spikeinterface.full as si
from spikeinterface.generation.drifting_generator import generate_drifting_recording

import u19_sorting.preprocess_wrappers as pw

UV_PER_COUNT = 0.195   # NP1 AP gain 500 -> ~0.195 uV/bit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--duration', type=float, default=40.0)
    ap.add_argument('--device', default='cpu')
    ap.add_argument('--preset', default='dredge_fast', help="'dredge' is the production preset but slower")
    ap.add_argument('--keep', action='store_true', help='keep the temp output dir')
    args = ap.parse_args()

    work = pathlib.Path(tempfile.mkdtemp(prefix='dredge_synth_'))
    raw, out = work / 'raw', work / 'dredge_output'
    raw.mkdir()

    # Zigzag rigid drift of +-20 um starting at 2 s, period 20 s.
    _static_rec, drifting_rec, _sorting, info = generate_drifting_recording(
        num_units=30, duration=args.duration, sampling_frequency=30000.0, seed=0, extra_outputs=True,
        generate_displacement_vector_kwargs=dict(
            displacement_sampling_frequency=5.0, drift_start_um=[0, 20], drift_stop_um=[0, -20],
            drift_step_um=1,
            motion_list=[dict(drift_mode='zigzag', non_rigid_gradient=None, t_start_drift=2.0,
                              t_end_drift=None, period_s=20)]))

    # Store the drifting recording as int16 counts, exactly like a SpikeGLX/CatGT ap.bin.
    to_counts = lambda r: si.astype(si.scale(r, gain=1 / UV_PER_COUNT), 'int16', round=True)
    drifting_i16 = to_counts(drifting_rec)

    # run_dredge locates the input via *ap.meta and opens it with read_spikeglx; stub that.
    (raw / 'synth_g0_t0.imec0.ap.meta').write_text('synthetic\n')
    si.read_spikeglx = lambda **kw: drifting_i16

    pw.dredge.run_dredge(raw, out, {'preset': args.preset, 'device': args.device,
                                    'job_kwargs': {'n_jobs': 4, 'chunk_duration': '1s', 'progress_bar': False}})

    # ---- 1. motion accuracy -------------------------------------------------------------
    motion = si.load_motion_info(out / 'motion')['motion']
    # ground truth: displacement_vectors is (time, xy, n_motions); rigid drift -> y of motion 0
    dv = info['displacement_vectors']
    t_true = np.arange(dv.shape[0]) / info['displacement_sampling_frequency']
    true_y = dv[:, 1, 0]
    depth = np.full_like(t_true, float(np.mean(drifting_rec.get_channel_locations()[:, 1])))
    est_y = motion.get_displacement_at_time_and_depth(t_true, depth)
    # DREDge is defined up to a constant offset; compare after removing the mean.
    err = (est_y - est_y.mean()) - (true_y - true_y.mean())
    print(f'[motion] injected range {true_y.min():+.1f}..{true_y.max():+.1f} um | '
          f'estimated range {est_y.min():+.1f}..{est_y.max():+.1f} um | '
          f'RMS err {np.sqrt(np.mean(err**2)):.2f} um | max err {np.abs(err).max():.2f} um')

    # ---- 2. residual drift --------------------------------------------------------------
    # Re-estimate motion on the corrected file: if the correction worked, what is left should
    # be flat compared to the injected +-20 um.
    corrected_bin = next(out.glob('*ap.bin'))
    corrected = si.read_binary(corrected_bin, sampling_frequency=30000.0,
                               num_channels=drifting_i16.get_num_channels(), dtype='int16')
    corrected.set_probe(drifting_i16.get_probe(), in_place=True)
    _, residual = si.correct_motion(si.astype(corrected, 'float32'), preset=args.preset,
                                    output_motion=True, estimate_motion_kwargs={'device': args.device},
                                    n_jobs=4, chunk_duration='1s', progress_bar=False)
    res_y = residual.get_displacement_at_time_and_depth(t_true, depth)
    print(f'[residual] drift left after correction: peak-to-peak {np.ptp(res_y):.2f} um, '
          f'RMS {np.sqrt(np.mean((res_y - res_y.mean())**2)):.2f} um  (injected peak-to-peak {np.ptp(true_y):.1f} um)')

    # ---- 3. rounding error --------------------------------------------------------------
    from spikeinterface.preprocessing.motion import motion_options_preset
    from spikeinterface.sortingcomponents.motion import interpolate_motion
    corrected_f = interpolate_motion(si.astype(drifting_i16, 'float32'), motion,
                                     **motion_options_preset[args.preset]['interpolate_motion_kwargs'])
    s0 = int(5 * 30000)
    Cf = corrected_f.get_traces(start_frame=s0, end_frame=s0 + 30000)
    Ci = corrected.get_traces(start_frame=s0, end_frame=s0 + 30000).astype(np.float32)
    print(f'[rounding] max |int16 - float| = {np.abs(Ci - Cf).max():.3f} counts (must be <= 0.5)')

    if args.keep:
        print('kept', work)
    else:
        shutil.rmtree(work)


if __name__ == '__main__':
    main()
