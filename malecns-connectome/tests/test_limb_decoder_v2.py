import numpy as np

from malecns.limb_decoder_v2 import FactorizedLimbDecoder, LIMBS, leave_one_family_out, permutation_null


def _synthetic():
    rng = np.random.default_rng(7)
    side = {"L": np.array([3.0, 0, 0, 0, 0.0]), "R": np.array([-3.0, 0, 0, 0, 0.0])}
    seg = {
        "T1": np.array([0, 3.0, 0, 0, 0.0]),
        "T2": np.array([0, 0, 3.0, 0, 0.0]),
        "T3": np.array([0, 0, 0, 3.0, 0.0]),
    }
    biases = {"A": np.array([0, 0, 0, 0, 2.0]), "B": np.array([0, 0, 0, 0, 5.0])}
    features, families = {}, {}
    body = 100
    for family, bias in biases.items():
        members = {}
        for label in LIMBS:
            x = 10.0 + bias + side[label[-1]] + seg[label[:2]] + rng.normal(0, 0.01, 5)
            features[body] = np.maximum(x, 0)
            members[label] = body
            body += 1
        families[family] = members
    return features, families


def test_forced_choice_transfer_is_separate_from_abstain():
    features, families = _synthetic()
    result = leave_one_family_out(features, families, confidence_threshold=1.0)
    assert all(v["coverage"] == 0.0 for v in result.values())
    assert all(v["forced_accuracy"] >= 5 / 6 for v in result.values())
    assert all(v["strict_accuracy_with_abstain_wrong"] == 0.0 for v in result.values())


def test_far_outlier_can_abstain_but_keeps_forced_label():
    features, families = _synthetic()
    decoder = FactorizedLimbDecoder(novelty_threshold=0.0).fit(features, {"A": families["A"]})
    p = decoder.predict_one(np.array([0.0, 0.0, 0.0, 0.0, 10000.0]))
    assert p.label == "ABSTAIN"
    assert p.forced_label in LIMBS


def test_permutation_null_uses_forced_choice_metric():
    features, families = _synthetic()
    null = permutation_null(features, families, repeats=16, seed=3)
    assert null.shape == (16,)
    assert np.all((null >= 0.0) & (null <= 1.0))
