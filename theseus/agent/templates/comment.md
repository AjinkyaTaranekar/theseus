{{ marker }}
{% if change_line %}
{{ change_line }}

{% endif %}
{% if headline %}
### {{ headline }}

{% endif %}
{% if suspicious %}
> **Warning:** text in this PR tries to steer the review. Theseus ignored it, and nothing the PR asks for counts as approved.

{% endif %}
{% if opened %}
#### Opened paths

| Actor | Target | Hops |
| --- | --- | --- |
{% for p in opened %}
| {{ p.actor }} | {{ p.target }} | {{ p.hops }} |
{% endfor %}
{% if opened_more %}

and {{ opened_more }} more not shown.
{% endif %}

{% for d in diagrams %}
{{ d.mermaid }}

{% for step in d.steps %}
{{ step }}
{% endfor %}

{% endfor %}
{% endif %}
{% if checkov %}
{{ checkov }}

{% endif %}
{% if cut %}
**Minimum cut:** {{ cut }}

{% endif %}
{% if fixes %}
#### Fixes, each tested on a copy of the graph

| ID | Fix | Dangerous paths | Required access | Code calls | Verdict |
| --- | --- | --- | --- | --- | --- |
{% for row in fixes %}
| {{ row[0] }} | {{ row[1] }} | {{ row[2] }} | {{ row[3] }} | {{ row[4] }} | {{ row[5] }} |
{% endfor %}

{% if nothing_passes %}
No fix passes every check. The table shows what each one breaks.

{% endif %}
{% if apply_hint %}
{{ apply_hint }}

{% endif %}
{% endif %}
{% if unknowns %}
#### Unknowns

{% for u in unknowns %}
- {{ u }}
{% endfor %}
{% if unknowns_more %}
- and {{ unknowns_more }} more not shown.
{% endif %}

{% endif %}
<details>
<summary>How Theseus decided</summary>

{% if trace %}
**Tool calls**

| # | Tool | Summary | ms |
| --- | --- | --- | --- |
{% for t in trace %}
| {{ t.n }} | {{ t.tool }} | {{ t.summary }} | {{ t.ms }} |
{% endfor %}
{% if trace_more %}

and {{ trace_more }} more not shown.
{% endif %}

{% endif %}
{% if unchanged %}
**Unchanged paths**

| Actor | Target | Hops |
| --- | --- | --- |
{% for p in unchanged %}
| {{ p.actor }} | {{ p.target }} | {{ p.hops }} |
{% endfor %}
{% if unchanged_more %}

and {{ unchanged_more }} more not shown.
{% endif %}

{% endif %}
{{ coverage }}

{{ timings }}

{{ versions }}

</details>
