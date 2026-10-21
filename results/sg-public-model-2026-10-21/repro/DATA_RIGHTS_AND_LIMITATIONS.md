# Input provenance, rights and scientific limitations

## Software is not data permission

The routing/benchmark repositories are MIT licensed with retained third-party notices. That does not relicense source transit data, OpenStreetMap databases, provider maps, literature or images. Original helper code included within the existing project follows its MIT default, as confirmed by the project owner. This does not extend MIT to third-party data or alter retained third-party notices.

The Vorld software MIT file and original NOTICE are retained in `licenses/inputs/`. NOTICE separately identifies LTA/DataMall, SimplyGo/TransitLink, SBS Transit and community-measured transfer sources. This package does not establish that all those data are redistributable. Public source availability, a hash, or a software MIT notice is not blanket data redistribution permission.

Historical GTFS provenance (`helpers/data/SOURCE_PROVENANCE.json`) states private research processing and no public data redistribution. Historical walking provenance (`helpers/walking-build/SOURCE_PROVENANCE.json`) explicitly records `public_redistribution: false`. Those restrictions on the data are preserved. The user's requested publication of results/methodology is not relabeled as a grant to redistribute third-party datasets.

## Retrieval, not redistribution

- GTFS: https://github.com/Vorld/singapore-gtfs/releases/download/v2026-07-12/singapore-gtfs.zip
  - 348,712 bytes; SHA256 `d92173127e9a5cbf8ecb5b4d50ab03f68deb7f8ddff73648b8ffb33c70ab4801`.
  - Review the release and source notices: https://github.com/Vorld/singapore-gtfs/releases/tag/v2026-07-12
- OSM/Geofabrik: https://download.geofabrik.de/asia/malaysia-singapore-brunei-261019.osm.pbf
  - 252,137,556 bytes; SHA256 `143cd2983864f6595e817e4e72b5f1acb498629a04613eb2e6da0bc5b064b0f3`.
  - © OpenStreetMap contributors, ODbL 1.0. Attribution: https://www.openstreetmap.org/copyright
  - License: https://opendatacommons.org/licenses/odbl/1-0/
  - Extract provider: https://download.geofabrik.de/asia/malaysia-singapore-brunei.html

Any authorized reuse or distribution must independently satisfy provider terms, attribution and ODbL/database obligations as applicable. No distribution-rights certification is made. The optional retrieval script downloads from providers to the researcher's chosen local root only after explicit opt-in; this source bundle supplies no data bytes.

## Interpretation limits

The GTFS is a community typical-weekday deterministic frequency model dated 2026-07-12, not a latest-official bus-and-rail feed, exact observed timetable, live service, or empirical passenger demand. Four fixed weekday windows do not constitute an all-day service model. Source calendar absence on the weekend is retained as unavailable coverage, not physical unreachability or successful no-route behavior.

The conservative walking graph uses a fixed OSM crop and explicit mapped path/permission rules. Bus-anchor connectors include disclosed assumptions. Unknown access stays unknown; no physical survey, wheelchair certification, dynamic restrictions, station fare-control or measured journey-time claim is made. Rail entry/exit sensitivity uses fixed hypothetical 120/90-second costs and remains separate from the conservative layer.

The workloads are finite-model stop-pair requests, not genuine within-request multiple access/egress candidates. The evaluator reconstructs witnesses independently but uses an incomplete observed feasible pool, not an independently complete full-network oracle. Failure counts and all offered requests remain in denominators. Agreement, valid witnesses and source-conditional cap comparisons do not certify global optimality or production SLA performance.

The source packager performed offline patch replay and bounded source/helper checks only. It did not retrieve data, regenerate full graphs/datasets, run Go builds/tests/routers, execute timing campaigns, publish or push. Regenerated path/time/hash-bound metadata needs new seals and cannot inherit historic provenance automatically.
