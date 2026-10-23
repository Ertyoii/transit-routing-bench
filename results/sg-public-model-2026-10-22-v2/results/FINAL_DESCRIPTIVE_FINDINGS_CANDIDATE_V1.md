# Fixed R18 final: descriptive aggregates

Report89a3 is independently accepted by receipt d0797b43e259dc4e25cd34d8cb6126a7545733459f7be1c4409ed5c821a2c6d0. This publication candidate remains unpublished pending owner review. All18 retained; finite budget exhausted; no plateau.

144 processes;25920 offered/attempted;25912 independently complete;8 label-limit failures retained(all p17).720 original request records repeated twice/product,not720 distinct physical OD pairs.

Every product:385140 eligible393 comparisons=490 positive-pool original records x2 blocks x393.230 other original records x2=460 empty/unavailable-pool offers do not count as393 successes. Scalar1296 once:881 finite-found,351 finite-model-empty,64 UNKNOWN.

## All18 products

Full-panel display hits share denominator385140. Regret columns are maximum signed additive score-seconds and normalized ratio,not absolute values or physical delay. Publication p95 is pooled over all1440 ordinary offers/product.

|Product|k|Display hits|Missing|Max signed score-s|Max normalized|Pooled p95 ms|Router prep p50 s|Peak RSS GB|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|p01 raptor-local-walk-ties|3|325712|0|2779|3.03947368|62.961331|1.877620|1.604723|
|p02 raptor-early-local-walk-ties|3|325712|0|2779|3.03947368|49.970782|1.835400|1.216889|
|p03 old-native-mc-control|3|381204|0|305.666667|0.119066491|85.074255|1.984146|1.252082|
|p04 mc-early-qualified-top3|3|381204|0|305.666667|0.119066491|68.368568|1.978961|1.251574|
|p05 ultra-capped-local-walk-ties|3|325712|0|2779|3.03947368|24.929083|1.940682|1.270129|
|p06 ultra-subset-local-walk-ties|3|325712|0|2779|3.03947368|25.324841|2.157539|1.422971|
|p07 tb-compact-native-capped|3|280036|0|4124|3.03947368|101.933356|6.873730|3.130581|
|p08 tb-compact-answer-walk-ties|3|300604|0|3712|3.03947368|96.367555|5.956638|3.110576|
|p09 finite20-lean-k3|3|381204|0|305.666667|0.119066491|71.672083|2.580295|0.946864|
|p10 finite20-safe-absolute-k3|3|381410|0|305.666667|0.119066491|68.866973|2.367785|0.976904|
|p11 bounded-normalized-greedy-k3|3|380752|0|387.090909|0.106233862|71.660309|2.114828|0.972993|
|p12 finite20-lean-k5|5|384264|0|169.601273|0.0713477948|72.108140|2.531702|0.971760|
|p13 bounded-absolute-greedy-k5|5|384620|0|69|0.0265066412|71.388993|2.587415|1.023881|
|p14 bounded-absolute-hybrid-k5|5|384620|0|69|0.0265066412|73.578648|2.493685|0.973615|
|p15 absolute-hybrid-fill-k5|5|384620|0|69|0.0265066412|71.633772|2.585735|1.036780|
|p16 old-native-mc-labels1m|3|381204|0|305.666667|0.119066491|90.637642|1.873966|1.263112|
|p17 sourceB-mc-early-labels250k|3|379634|1572|305.666667|0.119066491|69.902018|1.934817|1.237221|
|p18 sourceB-mc-early-labels1m|3|381204|0|305.666667|0.119066491|68.168845|1.992000|1.253261|

## Exact window/block publication p95 pairs(ms)

Each entry is b0/b1. Do not average these into an across-window block quantile.

|Product|Morning b0/b1|Midday b0/b1|Evening b0/b1|Overnight b0/b1|
|---|---:|---:|---:|---:|
|p01|65.089010/73.055733|60.553375/63.176136|72.567534/67.667412|41.710173/41.403288|
|p02|48.163750/52.182744|54.796449/51.736099|57.475834/50.012663|28.523891/25.145478|
|p03|82.552275/87.286486|87.703534/92.454791|84.180931/92.366047|59.199489/65.916746|
|p04|67.641805/76.916324|71.242621/69.395871|74.128632/73.864391|35.862540/36.785294|
|p05|23.996423/26.665644|27.223892/25.177502|29.173549/25.820273|10.193874/9.296144|
|p06|26.214541/28.556648|28.900372/26.807301|25.068164/27.793397|14.553998/8.973675|
|p07|108.545728/101.184000|118.010177/97.890038|97.809101/124.076031|24.749719/20.885366|
|p08|102.303446/104.240709|95.735282/105.677975|96.367555/116.705191|17.467285/26.764436|
|p09|72.855895/76.175680|73.424543/76.735875|75.719217/76.991732|35.200544/42.195612|
|p10|67.730200/68.784949|70.202262/75.171359|82.085177/75.284363|38.016200/36.523815|
|p11|79.380886/68.859746|75.408076/84.961153|73.260430/72.459657|39.495362/37.186239|
|p12|67.711373/71.666906|85.520561/71.160338|77.085475/79.896350|32.336421/45.940870|
|p13|67.215570/73.375003|81.975320/74.481061|70.076856/75.757745|33.304973/36.715852|
|p14|80.942693/76.288508|76.868882/75.457743|72.777679/83.153634|37.667129/36.931992|
|p15|73.771388/70.643752|78.501439/79.632412|75.350038/73.374390|32.826742/41.599257|
|p16|93.571010/92.614493|91.003097/93.151479|96.726649/95.788209|60.455109/58.040570|
|p17|66.298598/71.817131|78.628178/73.051136|76.764413/74.737197|36.174037/35.349991|
|p18|70.090534/80.225771|74.343001/66.619940|68.916998/70.285048|31.225909/37.084480|

## All stages and reference panels

JSON retains exact9 raw/final/display x full/family-out/lineage-out summaries/product. CSV retains234 contexts x9=2106 aggregate rows,including72 product-window and144 window/block cells. No private request identifiers,ODs,witnesses,raw paths or credentials are included.

Full raw/final hits: p01/p02/p05/p06=325758/385140;p07=280082;p08=300650;all other products385140 except p17=383568 with1572 missing. Full,family-out,lineage-out display numerators are exact and separate in JSON/CSV.

## Descriptive tradeoffs

- p03 old ORDINARY Mc500k vs p04 Source-B EARLY Mc500k: matching quality summaries,p9585.074255 vs68.368568ms. This final service-product contrast is not isolated old-Early to Source-B-Early source optimization.
- p07 native compact TripBased vs p08 walking ties: display280036 vs300604/385140;maximum signed score4124 vs3712s;p95101.933356 vs96.367555ms. Native/search-order products remain distinct.
- Same Source-B early500k/GC50/4GiB cohort: p09 lean k3=381204 hits;p10 safe-absolute k3=381410;p11 normalized-greedy k3=380752. p11 lowers maximum normalized regret(0.106233862 vs0.119066491) while increasing maximum additive regret(387.090909 vs305.666667s). Both objectives matter.
- Same cohort k5: p12 lean384264 hits,max169.601273s/0.071347795;p13/p14/p15 absolute policies384620 hits,max69s/0.026506641. Matching aggregate statistics do not prove identical outputs. Cardinality and policy change together.
- Native2D ULTRA p05/p06:325712 hits,p9524.929083/25.324841ms;Mc3D p04:381204 hits,p9568.368568ms. These are different native-contract service products,not a universal winner.
- p17 early250k:1432/1440 complete,all8 label limits,1572 eligible missing. p04 early500k and p18 early1m:1440/1440 complete with matching quality summaries. All cap products stay retained.

## First-native cohorts(hash-warmed,not cold disk)

- VALID-EMPTY: n=108;p50=6.217100485s;p95=12.933787530s;p99=13.717862756s. Raw and independently accepted first-marker clocks agree for all144 processes.
- TRANSIT: n=36;p50=6.949466934s;p95=12.473923893s;p99=13.329338540s. Raw and independently accepted first-marker clocks agree for all144 processes.

Prelaunch hashing is outside process clocks. Router/checker/quality prep,startup,RSS and first-native cohorts remain separate. Input-aware outcome-sealed literal-protocol deviation remains a public method limitation. No clean untouched-holdout,global-truth,demand-success,source-isolated-speedup,adoption-gate,unique-minimal-R or plateau claim.
