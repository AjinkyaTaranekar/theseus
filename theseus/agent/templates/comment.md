{{ marker }}
## {{ status.heading }}

{% if headline %}
**{{ headline }}**

{% endif %}
{% if consequence %}
{{ consequence }}

{% endif %}
{% if suspicious %}
> ⚠️ Text in this PR tries to steer the review. Theseus ignored it, and nothing the PR asks for counts as approved.

{% endif %}
{% if lines %}
{{ lines }}

{% endif %}
{% if connections %}
{{ connections }}

<sub>Shaded: sensitive data. Thick red arrow: what this PR adds or changes. Each step links to its line under <b>The path, step by step</b>.</sub>

{% endif %}
{% if opened %}
<details>
<summary><b>The path, step by step</b> ({{ opened|length + opened_more }} {{ "way" if opened|length + opened_more == 1 else "ways" }} in, with links to each line)</summary>

{% if risks %}
**What's at risk**

{% for risk in risks %}
- {{ risk }}
{% endfor %}
{% if risks_more %}
- and {{ risks_more }} more, in the table below
{% endif %}

{% endif %}
| Actor | Target | Hops |
| --- | --- | --- |
{% for p in opened %}
| {{ p.actor }} | {{ p.target }} | {{ p.hops }} |
{% endfor %}
{% if opened_more %}

and {{ opened_more }} more not shown.
{% endif %}

{% for d in diagrams %}
{{ d.title }}

{% for step in d.steps %}
{{ step }}
{% endfor %}

{% endfor %}
</details>

{% elif risks %}
<details>
<summary><b>What's at risk</b></summary>

{% for risk in risks %}
- {{ risk }}
{% endfor %}

</details>

{% endif %}
{% if fixes %}
<details>
<summary><b>All {{ fixes|length }} fixes Theseus tested</b>, each on a copy of the graph</summary>

{% if cut %}
**Smallest change:** {{ cut }}

{% endif %}
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
</details>

{% endif %}
{% if unknowns %}
<details>
<summary><b>What Theseus could not check</b> ({{ unknowns_count }})</summary>

{% for u in unknowns %}
- {{ u }}
{% endfor %}
{% if unknowns_more %}
- and {{ unknowns_more }} more not shown.
{% endif %}

</details>

{% endif %}
<details>
<summary><b>What Theseus checked</b></summary>

{% if checkov %}
{{ checkov }}

{% endif %}
{% if falkordb %}
{{ falkordb }}

{% endif %}
{% if change_line %}
**What the change does:** {{ change_line }}

{% endif %}
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

<details>
<summary><b>What is Theseus?</b></summary>

Theseus reviews infrastructure changes as a graph in FalkorDB: who can reach which data, through which groups, roles, secrets and code. It blocks a merge when a change opens a new way to sensitive data, and every step it shows links to the line that causes it.

</details>
