from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

SIDES = ("L", "R")
SEGMENTS = ("T1", "T2", "T3")
LIMBS = tuple(f"{segment}{side}" for segment in SEGMENTS for side in SIDES)


@dataclass(frozen=True)
class Prediction:
    label: str
    side: str
    segment: str
    confidence: float
    margin: float
    side_probability: float
    segment_probability: float
    novelty: float
    limb_probabilities: dict[str, float]


def _unit(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    norm = float(np.linalg.norm(x))
    return np.zeros_like(x, dtype=np.float64) if norm <= eps else x / norm


def _softmax(x: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = np.asarray(x, dtype=np.float64) / max(float(temperature), 1e-9)
    z -= np.max(z)
    e = np.exp(z)
    return e / np.sum(e)


def _prepare_rows(x: np.ndarray) -> np.ndarray:
    """Compress heavy-tailed non-negative connectivity features and row-normalize."""
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2:
        raise ValueError("features must be a 2D matrix")
    if not np.all(np.isfinite(a)):
        raise ValueError("features contain non-finite values")
    if np.min(a) < 0:
        # Signed contrast features are allowed, but skip log transform in that case.
        y = a.copy()
    else:
        y = np.log1p(a)
    norms = np.linalg.norm(y, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return y / norms


class FactorizedLimbDecoder:
    """Decode T1/T2/T3 and L/R separately from connectivity features.

    Training input is one or more complete six-member serial-homologue families.
    The model intentionally uses within-family contrasts so common cell-type identity is
    cancelled before side/segment axes are estimated.
    """

    def __init__(
        self,
        *,
        temperature: float = 0.20,
        confidence_threshold: float = 0.45,
        margin_threshold: float = 0.08,
        novelty_threshold: float = 0.15,
    ) -> None:
        self.temperature = float(temperature)
        self.confidence_threshold = float(confidence_threshold)
        self.margin_threshold = float(margin_threshold)
        self.novelty_threshold = float(novelty_threshold)
        self._fitted = False

    def fit(
        self,
        features_by_body: Mapping[int, np.ndarray],
        families: Mapping[str, Mapping[str, int]],
    ) -> "FactorizedLimbDecoder":
        if not families:
            raise ValueError("at least one training family is required")

        ordered_ids: list[int] = []
        for name, members in families.items():
            missing = [label for label in LIMBS if label not in members]
            if missing:
                raise ValueError(f"family {name!r} is incomplete: missing {missing}")
            ordered_ids.extend(int(members[label]) for label in LIMBS)

        raw = np.stack([np.asarray(features_by_body[i], dtype=np.float64) for i in ordered_ids])
        prepared = _prepare_rows(raw)
        dim = prepared.shape[1]
        vectors = {body: prepared[i] for i, body in enumerate(ordered_ids)}

        side_diffs: list[np.ndarray] = []
        segment_contrasts: dict[str, list[np.ndarray]] = {s: [] for s in SEGMENTS}
        family_centers: list[np.ndarray] = []

        for members in families.values():
            six = {label: vectors[int(members[label])] for label in LIMBS}
            family_center = np.mean(np.stack(list(six.values())), axis=0)
            family_centers.append(family_center)

            pair_means: dict[str, np.ndarray] = {}
            for segment in SEGMENTS:
                left = six[f"{segment}L"]
                right = six[f"{segment}R"]
                side_diffs.append(left - right)
                pair_means[segment] = 0.5 * (left + right)

            for segment in SEGMENTS:
                others = [pair_means[s] for s in SEGMENTS if s != segment]
                segment_contrasts[segment].append(pair_means[segment] - np.mean(others, axis=0))

        self.side_axis_ = _unit(np.mean(side_diffs, axis=0))
        self.segment_axes_ = {
            segment: _unit(np.mean(segment_contrasts[segment], axis=0)) for segment in SEGMENTS
        }
        self.center_ = np.mean(family_centers, axis=0)
        self.training_radius_ = max(
            float(np.linalg.norm(v - self.center_)) for v in vectors.values()
        )
        self.feature_dim_ = dim
        self._fitted = True
        return self

    def _prepare_one(self, feature: np.ndarray) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("decoder is not fitted")
        x = _prepare_rows(np.asarray(feature, dtype=np.float64).reshape(1, -1))[0]
        if x.shape[0] != self.feature_dim_:
            raise ValueError("feature dimension differs from training data")
        return x

    def predict_one(self, feature: np.ndarray) -> Prediction:
        x = self._prepare_one(feature)
        centered = x - self.center_

        side_raw = float(np.dot(centered, self.side_axis_))
        side_probs = _softmax(np.array([side_raw, -side_raw]), self.temperature)
        side_i = int(np.argmax(side_probs))
        side = SIDES[side_i]

        segment_scores = np.array(
            [float(np.dot(centered, self.segment_axes_[s])) for s in SEGMENTS], dtype=np.float64
        )
        segment_probs = _softmax(segment_scores, self.temperature)
        segment_i = int(np.argmax(segment_probs))
        segment = SEGMENTS[segment_i]

        limb_probs: dict[str, float] = {}
        for si, seg in enumerate(SEGMENTS):
            for di, sd in enumerate(SIDES):
                limb_probs[f"{seg}{sd}"] = float(segment_probs[si] * side_probs[di])

        ordered = sorted(limb_probs.items(), key=lambda kv: kv[1], reverse=True)
        confidence = float(ordered[0][1])
        margin = float(ordered[0][1] - ordered[1][1])
        radius = max(self.training_radius_, 1e-12)
        novelty = float(np.linalg.norm(centered) / radius)

        label = ordered[0][0]
        if (
            confidence < self.confidence_threshold
            or margin < self.margin_threshold
            or novelty > 1.0 + self.novelty_threshold
        ):
            label = "ABSTAIN"

        return Prediction(
            label=label,
            side=side,
            segment=segment,
            confidence=confidence,
            margin=margin,
            side_probability=float(side_probs[side_i]),
            segment_probability=float(segment_probs[segment_i]),
            novelty=novelty,
            limb_probabilities=limb_probs,
        )

    def predict_many(self, features: np.ndarray) -> list[Prediction]:
        return [self.predict_one(row) for row in np.asarray(features)]


def leave_one_family_out(
    features_by_body: Mapping[int, np.ndarray],
    families: Mapping[str, Mapping[str, int]],
    **decoder_kwargs: float,
) -> dict[str, dict[str, object]]:
    """Evaluate transfer of limb identity to a cell type excluded from training."""
    if len(families) < 2:
        raise ValueError("leave-one-family-out requires at least two families")

    out: dict[str, dict[str, object]] = {}
    for held_name, held_members in families.items():
        train = {name: members for name, members in families.items() if name != held_name}
        decoder = FactorizedLimbDecoder(**decoder_kwargs).fit(features_by_body, train)
        rows = []
        correct = 0
        non_abstain = 0
        for truth in LIMBS:
            body = int(held_members[truth])
            pred = decoder.predict_one(features_by_body[body])
            if pred.label != "ABSTAIN":
                non_abstain += 1
                correct += int(pred.label == truth)
            rows.append(
                {
                    "body_id": body,
                    "truth": truth,
                    "prediction": pred.label,
                    "confidence": pred.confidence,
                    "margin": pred.margin,
                    "novelty": pred.novelty,
                }
            )
        out[held_name] = {
            "accuracy_non_abstain": correct / max(non_abstain, 1),
            "coverage": non_abstain / 6.0,
            "rows": rows,
        }
    return out


def permutation_null(
    features_by_body: Mapping[int, np.ndarray],
    families: Mapping[str, Mapping[str, int]],
    *,
    repeats: int = 256,
    seed: int = 1,
) -> np.ndarray:
    """Null distribution produced by permuting labels within each six-cell family."""
    rng = np.random.default_rng(seed)
    family_items = {name: dict(members) for name, members in families.items()}
    scores = np.empty(repeats, dtype=np.float64)
    labels = np.array(LIMBS, dtype=object)

    for r in range(repeats):
        shuffled: dict[str, dict[str, int]] = {}
        for name, members in family_items.items():
            ids = np.array([members[label] for label in LIMBS], dtype=np.int64)
            rng.shuffle(ids)
            shuffled[name] = {label: int(body) for label, body in zip(labels, ids, strict=True)}
        result = leave_one_family_out(
            features_by_body,
            shuffled,
            confidence_threshold=0.0,
            margin_threshold=0.0,
            novelty_threshold=1e9,
        )
        scores[r] = np.mean([float(v["accuracy_non_abstain"]) for v in result.values()])
    return scores
