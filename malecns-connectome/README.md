# MaleCNS connectome topology research

Research code and reproducible checkpoints for blind structural analysis of the adult male *Drosophila* CNS connectome.

## Current state

The graph-only backbone contains 167,352 bodies and 6,259,265 directed edges after selecting bodies with total degree >= 70 and retaining edges with weight >= 5. Blind consensus segmentation produced 62 fine modules, which collapse reproducibly into 8 meso regions and 3 macro regions.

Independent annotations were used only after clustering for validation. Strong anchors include ANXXX098 (fine module 33), DNg11 (fine module 8), MDN + AN17A026 (fine module 16), AN04B001 (meso region 2 split over fine 36/44/48/53), AN17A002 (meso 2), and DNg98 (fine 40).

A structural propagation experiment from six ANXXX098 tactile anchors showed module-16 enrichment emerging after several hops and reaching about 2.86x the topology-destroying random control at hop 6. This is evidence for non-random routing, not a claim of simulated behaviour.

## Current hypothesis

Fine modules are not six limb labels. Existing anchors already falsify that simple model: homologous left/right cells can share a fine module, while cells belonging to different thoracic segments can also share one.

The next model therefore factorizes limb identity:

```text
P(limb | v) = P(side | v) * P(segment | v)
side    = {L, R}
segment = {T1, T2, T3}
```

Training uses contrasts between serial homologues inside a cell type instead of absolute similarity to one seed neuron. Evaluation is leave-one-cell-type-out so the held-out family is never used to build the decoder.

## Confirmed six-channel families

```text
AN17A003
T1L 15751   T1R 16384
T2L 42467   T2R 37876
T3L 29304   T3R 28508

AN17A024
T1L 43839   T1R 45843
T2L 56218   T2R 51068
T3L 121691  T3R 55185
```

AN17A062 is retained as a third candidate family while remaining segment assignments are verified.

## Layout

- `data/anchors.json` — curated experimental anchors and provenance notes.
- `docs/topology_segmentation_v0.2.md` — current blind-topology checkpoint.
- `src/malecns/limb_decoder.py` — factorized six-limb decoder.
- `tests/test_limb_decoder.py` — synthetic invariance and leave-family-out tests.
- `scripts/run_limb_decoder.py` — CLI for real connectivity feature matrices.

## Data

The large raw graph is deliberately not committed. Download the official MaleCNS connectivity data from:

- https://male-cns.janelia.org/download/
- https://github.com/flyconnectome/2025malecns

Expected raw edge schema:

```text
body_pre: int64
body_post: int64
weight:   int64
```

The source graph previously audited here contained 151,856,684 rows and 88,384,522 unique segment IDs in the union of pre/post columns. Those raw segment IDs must not be interpreted as 88 million biological neurons.

## Immediate next experiment

1. Build incoming/outgoing structural feature vectors for AN17A003 and AN17A024.
2. Fit paired side and segment contrasts using one family.
3. Predict all six cells of the held-out family.
4. Swap train/test families.
5. Add side-label and segment-label permutation nulls.
6. Add AN17A062 once all six T1/T2/T3 × L/R assignments are independently verified.
7. Use abdominal/non-limb cells as abstention controls.

The decoder must report confidence, margin, and `ABSTAIN`; forcing every neuron into one of six legs would merely turn uncertainty into a confident-looking error.
