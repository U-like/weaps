import numpy as np

from malecns.limb_decoder import FactorizedLimbDecoder, LIMBS, leave_one_family_out


def _synthetic():
    rng = np.random.default_rng(4)
    side = {"L": np.array([2.0, 0.0, 0.0, 0.0, 0.0]), "R": np.array([-2.0, 0.0, 0.0, 0.0, 0.0])}
    seg = {
        "T1": np.array([0.0, 2.0, 0.0, 0.0, 0.0]),
        "T2": np.array([0.0, 0.0, 2.0, 0.0, 0.0]),
        "T3": np.array([0.0, 0.0, 0.0, 2.0, 0.0]),
    }
    family_bias = {
        "A": np.array([0.0, 0.0, 0.0, 0.0, 2.5]),
        "B": np.array([0.0, 0.0, 0.0, 0.0, 5.0]),
    }
    features = {}
    families = {}
    body = 100
    for family, bias in family_bias.items():
        members = {}
        for label in LIMBS:
            segment, sd = label[:2], label[2]
            x = 8.0 + bias + side[sd] + seg[segment] + rng.normal(0, 0.03, 5)
            features[body] = np.maximum(x, 0)
            members[label] = body
            body += 1
        families[family] = members
    return features, families


def test_leave_family_out_transfers_identity():
    features, families = _synthetic()
    result = leave_one_family_out(
        features,
        families,
        confidence_threshold=0.0,
        margin_threshold=0.0,
        novelty_threshold=1e9,
    )
    assert all(v["accuracy_non_abstain"] >= 5 / 6 for v in result.values())


def test_decoder_can_abstain_on_far_outlier():
    features, families = _synthetic()
    decoder = FactorizedLimbDecoder(novelty_threshold=0.0).fit(features, {"A": families["A"]})
    outlier = np.array([0.0, 0.0, 0.0, 0.0, 10000.0])
    assert decoder.predict_one(outlier).label == "ABSTAIN"
