# Analysis outputs

| Folder | Contents |
| --- | --- |
| `dataset_readers/` | Coverage, company-year, emissions-intensity, and supplier-analysis results |
| `cdp_extraction/` | Annotation samples and reviewed workbooks, including their previews |
| `cdp_text_clustering/` | Coding, embedding, clustering, classification, and benchmark runs |
| `MDP/` | Reserved for future MDP analysis outputs |

Existing run names and workbook identifiers are retained. Raw inputs,
processed datasets, and downloaded model caches remain in their existing
locations. Historic manifests and notebook execution outputs retain their
original recorded paths; current code and notebook sources use the new paths.

These output folders are ignored by Git. Back up reviewed workbooks and any
other results that cannot be recreated from code and source data.
