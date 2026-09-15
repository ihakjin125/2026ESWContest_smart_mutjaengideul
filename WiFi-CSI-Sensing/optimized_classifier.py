"""Small waveform CNN; grouped validation selects weights, test stays unseen."""

import numpy as np
from cnn_runtime import probabilities, forward


def make_network(classes, channels):
    from torch import nn

    class Network(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv1d(channels, 16, 7, padding=3)
            self.bn1 = nn.BatchNorm1d(16)
            self.conv2 = nn.Conv1d(16, 32, 5, padding=2)
            self.bn2 = nn.BatchNorm1d(32)
            self.conv3 = nn.Conv1d(32, 32, 3, padding=1)
            self.fc1 = nn.Linear(32 * 16, 64)
            self.fc2 = nn.Linear(64, classes)
            self.drop = nn.Dropout(0.35)

        def forward(self, x):
            x = nn.functional.max_pool1d(
                nn.functional.relu(self.bn1(self.conv1(x))), 2
            )
            x = nn.functional.max_pool1d(
                nn.functional.relu(self.bn2(self.conv2(x))), 2
            )
            x = nn.functional.relu(self.conv3(x))
            x = nn.functional.adaptive_avg_pool1d(x, 16).flatten(1)
            return self.fc2(self.drop(nn.functional.relu(self.fc1(x))))

    return Network()


class WaveformClassifier:
    def fit(self, x, y, validation, epochs=100):
        import torch
        from sklearn.metrics import balanced_accuracy_score

        torch.set_num_threads(2)
        torch.manual_seed(42)
        self.classes_, encoded = np.unique(y, return_inverse=True)
        self.channels, self.input_length = x.shape[1:]
        self.scale = np.maximum(
            np.sqrt(
                np.mean(
                    np.asarray(x, dtype=float) ** 2, axis=(0, 2), keepdims=True
                )
            ),
            1e-5,
        ).astype(np.float32)
        vx, vy = validation
        vencoded = np.array([list(self.classes_).index(v) for v in vy])
        tx = torch.from_numpy(np.asarray(x, dtype=np.float32) / self.scale)
        ty = torch.from_numpy(encoded).long()
        tvx = torch.from_numpy(np.asarray(vx, dtype=np.float32) / self.scale)
        network = make_network(len(self.classes_), self.channels)
        optimizer = torch.optim.AdamW(
            network.parameters(), lr=1e-3, weight_decay=1e-3
        )
        weights = len(y) / (len(self.classes_) * np.bincount(encoded))
        criterion = torch.nn.CrossEntropyLoss(
            weight=torch.tensor(weights, dtype=torch.float32),
            label_smoothing=0.05,
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=epochs
        )
        generator = torch.Generator().manual_seed(42)
        best = (-1.0, -np.inf)
        best_weights = None
        stale = 0
        self.losses = []
        self.validation_history = []
        self.best_epoch = 0
        for epoch in range(epochs):
            network.train()
            total = 0.0
            for indexes in torch.randperm(len(tx), generator=generator).split(
                32
            ):
                optimizer.zero_grad(set_to_none=True)
                loss = criterion(network(tx[indexes]), ty[indexes])
                if not torch.isfinite(loss):
                    raise ValueError("학습 손실이 유효하지 않습니다.")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(network.parameters(), 1.0)
                optimizer.step()
                total += loss.item() * len(indexes)
            scheduler.step()
            self.losses.append(total / len(tx))
            network.eval()
            with torch.inference_mode():
                logits = network(tvx)
                vloss = torch.nn.functional.cross_entropy(
                    logits, torch.from_numpy(vencoded).long()
                ).item()
                score = float(
                    balanced_accuracy_score(
                        vy, self.classes_[logits.argmax(1).numpy()]
                    )
                )
            self.validation_history.append(
                dict(epoch=epoch + 1, balanced_accuracy=score, loss=vloss)
            )
            if (score, -vloss) > best:
                best = (score, -vloss)
                self.best_epoch = epoch + 1
                stale = 0
                best_weights = {
                    k: v.detach().cpu().numpy().copy()
                    for k, v in network.state_dict().items()
                }
            else:
                stale += 1
            if epoch >= 24 and stale >= 15:
                break
        self.epochs = len(self.losses)
        self.weights = best_weights
        self.temperature = 1.0
        # Calibration uses only validation, never held-out test.
        logits = forward(
            self.weights, np.asarray(vx, dtype=np.float32) / self.scale
        )
        losses = []
        for temperature in (1.0, 1.5, 2.0, 3.0, 5.0):
            z = logits / temperature
            z -= z.max(axis=1, keepdims=True)
            p = np.exp(z)
            p /= p.sum(axis=1, keepdims=True)
            losses.append(
                -np.log(
                    np.maximum(p[np.arange(len(p)), vencoded], 1e-9)
                ).mean()
            )
        self.temperature = float(
            (1.0, 1.5, 2.0, 3.0, 5.0)[int(np.argmin(losses))]
        )
        self.threshold = 0.65
        self.margin = 0.15
        self.validation_accuracy = best[0]
        # Numerical parity is required before saving portable weights.
        network.load_state_dict(
            {k: torch.from_numpy(v.copy()) for k, v in self.weights.items()}
        )
        network.eval()
        with torch.inference_mode():
            expected = network(tvx).numpy()
        self.portable_error = float(np.max(np.abs(expected - logits)))
        if not np.allclose(expected, logits, atol=2e-4, rtol=2e-4):
            raise ValueError("PC와 온디바이스 추론 계산 검증에 실패했습니다.")
        return self

    def predict_proba(self, x):
        x = np.asarray(x, dtype=np.float32)
        if x.ndim != 3 or tuple(x.shape[1:]) != (
            self.channels,
            self.input_length,
        ):
            raise ValueError("모델의 전처리 채널·구간 길이가 맞지 않습니다.")
        return probabilities(self.weights, x, self.scale, self.temperature)

    def predict(self, x):
        return self.classes_[np.argmax(self.predict_proba(x), axis=1)]
