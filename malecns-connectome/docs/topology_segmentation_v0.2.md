# MaleCNS blind topology segmentation — checkpoint v0.2

## Graph-only backbone

- Selection: total degree >= 70
- Bodies: 167,352
- Internal directed edges with weight >= 5: 6,259,265
- Internal weight sum: 89,744,260

Simple connected components do not recover anatomy. At weight >= 5 the largest weak component contains 99.376% of the backbone; even at weight >= 20 it remains about 85.06%.

## Blind hierarchy

- 62 robust fine modules
- 91,191 bodies in stable cores
- 129,777 / 167,352 bodies conservatively assigned (77.55%)
- 8 meso regions
- 3 macro regions

Numeric region IDs remain deliberately unnamed until independent anatomy supports a label.

## Independent anchor validation

- ANXXX098 leg tactile: all 6 official bodies -> fine module 33
- DNg11 front-leg rubbing: all 5 tested bodies -> fine module 8
- MDN backward walking: all 4 tested bodies -> fine module 16
- AN17A026 backward walking: both tested bodies -> fine module 16
- AN04B001: four homologues remain in meso 2 while splitting over fine 36/44/48/53
- AN17A002: both bodies remain in meso 2
- DNg98: both bodies -> fine module 40

These anchors validate structure; they do not imply every member of a module has the anchor's exact function.

## Real-vs-random structural propagation

Initial mass was equally distributed over the six ANXXX098 tactile anchors. Directed transition probability was proportional to edge weight within each presynaptic row. Thirty-two controls permuted post endpoints while preserving edge count, presynaptic row totals, the postsynaptic endpoint multiset and global weights.

| hop | module16 real | module16 random mean | enrichment |
|---:|---:|---:|---:|
| 1 | 0.00240 | 0.01733 | 0.14x |
| 2 | 0.00548 | 0.01985 | 0.28x |
| 3 | 0.01332 | 0.01966 | 0.68x |
| 4 | 0.02550 | 0.01941 | 1.31x |
| 5 | 0.04071 | 0.01917 | 2.12x |
| 6 | 0.05415 | 0.01892 | 2.86x |

Interpretation: the real graph routes mass more selectively than randomized topology, and module 16 becomes enriched only after several hops. This is a structural result, not a biological dynamics simulation.

## Negative results retained

- Connected components alone are not useful for limb separation.
- Random-neighborhood embedding + KMeans was not robust enough.
- A tempting two-way macro split could not be defended as left/right anatomy.
- Choosing exactly six similar fine modules and naming them six legs was explicitly rejected.

## Updated limb-identity conclusion

Subsequent annotation work falsified the idea that one fine module equals one limb. The current model separates segment identity (T1/T2/T3) from side identity (L/R), then combines them into six limb scores. Evaluation must transfer to a held-out cell type.
