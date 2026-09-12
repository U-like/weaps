from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

SIDES = ("L", "R")
SEGMENTS = ("T1", "T2", "T3")
LIMBS = tuple(f"{segment}{side}" for segment in SEGMENTS for side in SIDES)


@dataclass(frozen=True)
class Prediction:
    label: str
    forced_label: str
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


def _softmax(x: np.ndarray, temperature: float) -> np.ndarray:
    z = np.asarray(x, dtype=np.float64) / max(float(temperature), 1e-9)
    z -= np.max(z)
    e = np.exp(z)
    return e / np.sum(e)


def _prepare_rows(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2:
        raise ValueError("features must be a 2D matrix")
    if not np.all(np.isfinite(a)):
        raise ValueError("features contain non-finite values")
    y = a.copy() if np.min(a) < 0 else np.log1p(a)
    norms = np.linalg.norm(y, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return y / norms


class FactorizedLimbDecoder:
    """Decode side and thoracic segment from within-family connectivity contrasts.

    The six-way forced prediction is always available for scientific evaluation.
    ABSTAIN is an operational layer and is deliberately kept separate from the
    forced-choice significance test.
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

        prepared = _prepare_rows(
            np.stack([np.asarray(features_by_body[i], dtype=np.float64) for i in ordered_ids])
        )
        vectors = {body: prepared[i] for i, body in enumerate(ordered_ids)}
        self.feature_dim_ = prepared.shape[1]

        side_diffs: list[np.ndarray] = []
        segment_contrasts: dict[str, list[np.ndarray]] = {s: [] for s in SEGMENTS}
        family_centers: list[np.ndarray] = []

        for members in families.values():
            six = {label: vectors[int(members[label])] for label in LIMBS}
            family_centers.append(np.mean(np.stack(list(six.values())), axis=0))
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
        self._fitted = True
        return self

    def predict_one(self, feature: np.ndarray) -> Prediction:
        if not self._fitted:
            raise RuntimeError("decoder is not fitted")
        x = _prepare_rows(np.asarray(feature, dtype=np.float64).reshape(1, -1))[0]
        if x.shape[0] != self.feature_dim_:
            raise ValueError("feature dimension differs from training data")
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

        limb_probs = {
            f"{seg}{sd}": float(segment_probs[si] * side_probs[di])
            for si, seg in enumerate(SEGMENTS)
            for di, sd in enumerate(SIDES)
        }
        ordered = sorted(limb_probs.items(), key=lambda kv: kv[1], reverse=True)
        forced_label = ordered[0][0]
        confidence = float(ordered[0][1])
        margin = float(ordered[0][1] - ordered[1][1])
        novelty = float(np.linalg.norm(centered) / max(self.training_radius_, 1e-12))

        label = forced_label
        if (
            confidence < self.confidence_threshold
            or margin < self.margin_threshold
            or novelty > 1.0 + self.novelty_threshold
        ):
            label = "ABSTAIN"

        return Prediction(
            label=label,
            forced_label=forced_label,
            side=side,
            segment=segment,
            confidence=confidence,
            margin=margin,
            side_probability=float(side_probs[side_i]),
            segment_probability=float(segment_probs[segment_i]),
            novelty=novelty,
            limb_probabilities=limb_probs,
        )


def leave_one_family_out(
    features_by_body: Mapping[int, np.ndarray],
    families: Mapping[str, Mapping[str, int]],
    **decoder_kwargs: float,
) -> dict[str, dict[str, object]]:
    if len(families) < 2:
        raise ValueError("leave-one-family-out requires at least two families")

    result: dict[str, dict[str, object]] = {}
    for held_name, held_members in families.items():
        train = {name: members for name, members in families.items() if name != held_name}
        decoder = FactorizedLimbDecoder(**decoder_kwargs).fit(features_by_body, train)
        rows = []
        forced_correct = side_correct = segment_correct = strict_correct = non_abstain_correct = 0
        non_abstain = 0

        for truth in LIMBS:
            body = int(held_members[truth])
            pred = decoder.predict_one(features_by_body[body])
            forced_correct += int(pred.forced_label == truth)
            side_correct += int(pred.side == truth[-1])
            segment_correct += int(pred.segment == truth[:2])
            strict_correct += int(pred.label == truth)
            if pred.label != "ABSTAIN":
                non_abstain += 1
                non_abstain_correct += int(pred.label == truth)
            rows.append(
                {
                    "body_id": body,
                    "truth": truth,
                    "prediction": pred.label,
                    "forced_prediction": pred.forced_label,
                    "side_prediction": pred.side,
                    "segment_prediction": pred.segment,
                    "confidence": pred.confidence,
                    "margin": pred.margin,
                    "novelty": pred.novelty,
                }
            )

        result[held_name] = {
            "forced_accuracy": forced_correct / 6.0,
            "side_accuracy": side_correct / 6.0,
            "segment_accuracy": segment_correct / 6.0,
            "strict_accuracy_with_abstain_wrong": strict_correct / 6.0,
            "accuracy_non_abstain": non_abstain_correct / max(non_abstain, 1),
            "coverage": non_abstain / 6.0,
            "rows": rows,
        }
    return result


def permutation_null(
    features_by_body: Mapping[int, np.ndarray],
    families: Mapping[str, Mapping[str, int]],
    *,
    repeats: int = 4096,
    seed: int = 1,
) -> np.ndarray:
    """Forced-choice null from independent within-family label permutations."""
    rng = np.random.default_rng(seed)
    labels = np.array(LIMBS, dtype=object)
    scores = np.empty(repeats, dtype=np.float64)

    for r in range(repeats):
        shuffled: dict[str, dict[str, int]] = {}
        for name, members in families.items():
            ids = np.array([members[label] for label in LIMBS], dtype=np.int64)
            rng.shuffle(ids)
            shuffled[name] = {label: int(body) for label, body in zip(labels, ids, strict=True)}
        fold = leave_one_family_out(features_by_body, shuffled)
        scores[r] = np.mean([float(v["forced_accuracy"]) for v in fold.values()])
    return scores
