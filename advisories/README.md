# Advisory feed

The posture run (`POST /posture`, `python -m theseus posture`) checks every workflow on `main` against each
advisory here. When a workflow uses an advisory's Action at an affected version, Theseus runs finding mode
on it: what that workflow can reach if it is compromised, the cheapest cut, and the secrets to rotate. The
finding appears on the organisation dashboard with its own page.

Each file is one JSON object:

| Field | Meaning |
| --- | --- |
| `id` | The advisory's ID, such as a GHSA ID |
| `action` | The Action it affects, `owner/name` |
| `affected_versions` | The version tags that are affected, such as `["v1", "v2", "v3"]` |
| `text` | The advisory's text. Untrusted: Jev reads it inside untrusted tags to rate urgency, and it is never evidence |

`GHSA-demo-0001.json` is synthetic, like the rest of the demo world: it is the same advisory as
`fixtures/compromised-action/advisory.json`, for `demo-thirdparty/file-diff`, which `preview.yml` and
`lint.yml` use. A real deployment fills this folder from the GitHub Advisory Database (`ecosystem=actions`);
`THESEUS_ADVISORIES` points the server at another folder.
