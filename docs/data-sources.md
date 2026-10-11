# Data sources, licences and attribution

FlowCredit uses licensed **public aggregate revenue observations** for forecasting,
development calibration and separate revenue benchmarks. No private bank records
or actual customer identities are included. Sources provide no borrower expense,
repayment or default labels. Inference reads committed assets locally and never
downloads data.

| Provider / dataset                                                                                                                                                                                                                                                          | Native unit                                                                                                           | Licence                                                                                      | Role                                                                                                                          |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| [Uzbekistan SIAT 1.07.02.0002](https://siat.stat.uz/data/2699/?lang=en), regional retail trade                                                                                                                                                                              | Million UZS; year-to-date totals differenced within each year                                                         | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)                                    | Original revenue training/evaluation and disclosed generator seasonality                                                      |
| [Uzbekistan SIAT expanded turnover corpus](../ml-service/data/revenue-series.json): [wholesale](https://siat.stat.uz/data/964/?lang=en), [market services](https://siat.stat.uz/data/3409/?lang=en), [accommodation/food services](https://siat.stat.uz/data/3227/?lang=en) | Million UZS wholesale / billion UZS services; within-year differences, services ×1000 for million-UZS benchmark units | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)                                    | Original regional/district revenue training and temporal evaluation; post-September 2024 service-definition boundary enforced |
| [ABS Retail Trade, June 2025 Table11](https://www.abs.gov.au/statistics/industry/retail-and-wholesale-trade/retail-trade-australia/jun-2025), state × industry leaf turnover                                                                                                | Million AUD, original monthly values                                                                                  | [CC BY 4.0](https://www.abs.gov.au/website-privacy-copyright-and-disclaimer)                 | Original international revenue training, development and reserved evaluation                                                  |
| [Statistics Canada 20-10-0056-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010005601), retail province × leaf NAICS                                                                                                                                           | Thousand CAD, unadjusted                                                                                              | [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence) | Original international revenue training, development and reserved evaluation                                                  |
| [Eurostat sts_trtu_m](https://ec.europa.eu/eurostat/databrowser/product/view/sts_trtu_m), disjoint trade sectors/countries                                                                                                                                                  | Nominal turnover index, 2021=100; unadjusted                                                                          | [Attributed reuse policy](https://ec.europa.eu/eurostat/help/copyright-notice)               | Original real-revenue training/development and reserved country audit                                                         |
| [ONS Retail Sales Index DRSI](https://www.ons.gov.uk/businessindustryandtrade/retailindustry/datasets/retailsales/current), leaf VALUE series                                                                                                                               | Nominal index, 2024=100; unadjusted                                                                                   | [OGL v3.0](https://www.ons.gov.uk/help/terms-conditions)                                     | Original external audit only; never fitted or selected                                                                        |
| [Statistics Canada 20-10-0074-01](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=2010007401), wholesale geography × leaf NAICS                                                                                                                                       | Thousand CAD, nominal/unadjusted                                                                                      | [Statistics Canada Open Licence](https://www.statcan.gc.ca/en/terms-conditions/open-licence) | New research training/development in eight geographies; five entirely reserved audit geographies                              |
| [Stats NZ electronic card transactions, August 2026](https://www.stats.govt.nz/information-releases/electronic-card-transactions-august-2026/), eight disjoint industry groups                                                                                              | Million NZD, GST-inclusive monthly merchant card spending                                                             | [CC BY 4.0](https://www.stats.govt.nz/about-us/copyright/)                                   | New independent-provider holdout only; no fitting or interval calibration                                                     |

Attribution: National Statistics Committee of the Republic of Uzbekistan;
Australian Bureau of Statistics; Statistics Canada; Eurostat; Office for National
Statistics, licensed under OGL v3.0. This work is based on/includes Stats NZ's data
which are licensed by Stats NZ for reuse under the Creative Commons Attribution
4.0 International licence. Adaptations imply no provider endorsement.

## Snapshots, transformations and separation

The [original dataset declaration](../ml-service/data/README.md) describes
source releases, exclusions, quality flags, temporal splits and transformations.
Committed JSON snapshots retain the source URL, download SHA-256, retrieval
timestamp, native units, licence and attribution. Suppressed, missing, confidential
or unreliable values stay null; training rejects invalid windows. Parent totals,
overlapping sectors, seasonally adjusted duplicates and zero-filled gaps are
excluded. Monetary scales are normalized for losses, not converted into UZS.

The [fresh reservation](../ml-service/data/fresh-holdout-reservation.json) was
hashed before model errors. New wholesale data has 416 disjoint series with
3,812 training origins / 45,744 targets for the research candidate. The primary
fresh audit uses 382 Canadian windows and 72 NZ windows, totaling 454 windows /
5,448 target months. NZ card spending excludes cash, cheques, bank transfers and
other non-card sales, so it is a partial revenue proxy.

The [fresh report](../ml-service/reports/revenue-upgrade-fresh.md) and
[machine evidence](../ml-service/reports/revenue-upgrade-fresh.json) retain source
hashes, selected models, every actual/predicted coordinate and exclusion reasons.
These retrospective aggregate series share economic shocks and use revised
release vintages. They are not independent individual borrower cases.
All scored holdouts are now consumed.

The served incumbent remains trained on its original 86,976 rolling targets /
43,705 unique observations. New research training is not claimed for the incumbent.
Real interval calibration uses 3,208 dependent development history views and
excludes the 68 old external cases. It is empirical revenue calibration, not
validated net-flow or repayment coverage.

## Business inputs and synthetic material

Authenticated bank workspaces start empty. Actual UZS imports declare
`data_source: "user_provided"` and `amount_unit: "UZS"`; the importer supplies
provenance, which the application does not independently authenticate. Private
runtime imports and audit records are ignored and must never be committed.

The optional Showcase lab creates a separate tenant and marks every generated
business as synthetic. Its generator, parameters, source/seed and exports disclose
that origin. Fixtures in tests and financial behavior reports are synthetic;
they support contract, accounting and behavior checks only. Public revenue
seasonality does not turn synthetic borrower costs into real evidence.

The teammate's historical boosters/calibration were trained on synthetic
businesses. The final assembly does not use those revenue/outflow predictors or
the synthetic net forecast. It does reuse verified financial primitives and
discloses inherited synthetic-calibrated buffer policy as unvalidated on real
borrowers. See the [teammate source declaration](../teammate-ml-service/README.md).

## Code attribution

The [upstream foundation](upstream.md) is an explicitly imported MIT-licensed
Nest/React boilerplate. Original upstream code and the teammate's supplied module
are not presented as newly invented during the final. The teammate archive hash,
selected source paths and vendor SHA manifest are retained. Node/Python dependency
licences remain governed by their publishers. Paid external inference APIs are
not used by the runtime.
