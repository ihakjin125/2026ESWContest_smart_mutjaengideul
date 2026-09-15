"""Portable NumPy CNN inference shared by Windows and Raspberry Pi."""

import numpy as np


def conv(x, w, b, padding):
    padded = np.pad(x, ((0, 0), (0, 0), (padding, padding)))
    windows = np.lib.stride_tricks.sliding_window_view(
        padded, w.shape[2], axis=2
    )
    return (
        np.einsum("nctk,ock->not", windows, w, optimize=True)
        + b[None, :, None]
    )


def forward(weights, x):
    def bn(a, key):
        scale = weights[key + ".weight"] / np.sqrt(
            weights[key + ".running_var"] + 1e-5
        )
        return (a - weights[key + ".running_mean"][None, :, None]) * scale[
            None, :, None
        ] + weights[key + ".bias"][None, :, None]

    a = conv(x, weights["conv1.weight"], weights["conv1.bias"], 3)
    a = np.maximum(bn(a, "bn1"), 0)
    a = (
        a[:, :, : a.shape[2] // 2 * 2]
        .reshape(len(a), a.shape[1], -1, 2)
        .max(axis=3)
    )
    a = conv(a, weights["conv2.weight"], weights["conv2.bias"], 2)
    a = np.maximum(bn(a, "bn2"), 0)
    a = (
        a[:, :, : a.shape[2] // 2 * 2]
        .reshape(len(a), a.shape[1], -1, 2)
        .max(axis=3)
    )
    a = np.maximum(
        conv(a, weights["conv3.weight"], weights["conv3.bias"], 1), 0
    )
    length = a.shape[2]
    a = np.stack(
        [
            a[
                :,
                :,
                int(np.floor(i * length / 16)) : int(
                    np.ceil((i + 1) * length / 16)
                ),
            ].mean(axis=2)
            for i in range(16)
        ],
        axis=2,
    )
    a = np.maximum(
        a.reshape(len(a), -1) @ weights["fc1.weight"].T + weights["fc1.bias"],
        0,
    )
    return a @ weights["fc2.weight"].T + weights["fc2.bias"]


def probabilities(weights, x, scale, temperature=1.0):
    logits = (
        forward(weights, np.asarray(x, dtype=np.float32) / scale) / temperature
    )
    logits -= logits.max(axis=1, keepdims=True)
    e = np.exp(logits)
    return e / e.sum(axis=1, keepdims=True)
