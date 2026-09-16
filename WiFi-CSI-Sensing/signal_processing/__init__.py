"""One waveform pipeline for observation, training and live prediction.

Uses physical channels, mild DWT and three PCA components.
The same final waveform is used for display, fitting and prediction.
"""

import numpy as np
import pywt
from scipy.signal import butter, sosfiltfilt
from sklearn.decomposition import PCA

PROFILE = "csi_physical50_pca3_v2"
RATE = 60
COMPONENTS = 3
CONFIG = dict(
    profile=PROFILE,
    resampling_hz=RATE,
    normalization="channel_power_fraction",
    channel_mapping="physical_50_v1",
    dwt="db4",
    dwt_level=2,
    dwt_threshold="0.5_MAD_sigma_soft",
    pca_components=COMPONENTS,
    pca_fit="each_complete_window",
    lowpass="Butterworth_4_zero_phase",
    lowpass_hz=8.0,
    max_interpolation_gap_s=0.15,
    minimum_rate_hz=30.0,
)


def preprocess(amplitude):
    return preprocess_stages(amplitude, return_matrix=True)


def preprocess_stages(
    amplitude,
    denoise=True,
    pca=True,
    lowpass=True,
    subcarrier=0,
    return_matrix=False,
    component=0,
):
    amplitude = np.asarray(amplitude, dtype=float)
    if (
        amplitude.ndim != 2
        or amplitude.shape[1] != 50
        or len(amplitude) < 30
        or not np.isfinite(amplitude).all()
    ):
        raise ValueError(
            "전처리에는 배열이 확인된 50개 유효 채널이 필요합니다."
        )
    data = amplitude.copy()
    if denoise:
        power = data**2
        totals = power.sum(axis=1, keepdims=True)
        if np.any(totals <= 0):
            raise ValueError("모든 채널이 0인 프레임은 전처리할 수 없습니다.")
        data = power / totals
        coeff = pywt.wavedec(data, "db4", axis=0, level=2, mode="symmetric")
        sigma = (
            np.median(abs(coeff[-1] - np.median(coeff[-1], axis=0)), axis=0)
            / 0.6745
        )
        coeff[1:] = [
            np.sign(d) * np.maximum(abs(d) - 0.5 * sigma, 0) for d in coeff[1:]
        ]
        data = pywt.waverec(coeff, "db4", axis=0, mode="symmetric")[
            : len(data)
        ]
    if pca:
        data -= np.median(data, axis=0, keepdims=True)
        if np.max(np.ptp(data, axis=0)) < 1e-15:
            result = np.zeros((len(data), COMPONENTS))
        else:
            transform = PCA(n_components=COMPONENTS, svd_solver="full").fit(
                data
            )
            result = transform.transform(data)
            signs = np.sign(
                transform.components_[
                    np.arange(COMPONENTS),
                    np.argmax(abs(transform.components_), axis=1),
                ]
            )
            result *= signs
    else:
        result = data[:, [int(subcarrier)]]
    if lowpass:
        result = sosfiltfilt(
            butter(4, 8.0, fs=RATE, output="sos"), result, axis=0
        )
    if not np.isfinite(result).all():
        raise ValueError("전처리 결과에 유효하지 않은 값이 있습니다.")
    result = np.asarray(result, dtype=np.float32)
    return (
        result
        if return_matrix
        else result[:, max(0, min(result.shape[1] - 1, int(component)))]
    )
