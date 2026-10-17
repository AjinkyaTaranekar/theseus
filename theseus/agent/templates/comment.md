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

<sub>Red arrow: added by this PR · Shaded: sensitive data</sub>

{% endif %}
{% if graph_url %}
**[See it on a graph →]({{ graph_url }})**

{% endif %}
{% if impact %}
<details>
<summary><b>Where this change lands</b> (who reaches it, what runs through it, what it costs)</summary>

{% if impact.diagram %}
{{ impact.diagram }}

<sub>Green: added by this PR · Red, dashed: removed · Yellow: where it lands most</sub>

{% endif %}
{% for m in impact.moved %}
- {{ m }}
{% endfor %}
{% if impact.moved_more %}
- and {{ impact.moved_more }} more links
{% endif %}

| Touched | Change | Reached by | Dependencies through it | Services that call it |
| --- | --- | --- | --- | --- |
{% for t in impact.touched %}
| {{ t.node }} | {{ t.change }} | {{ t.reached_by }} | {{ t.relied_on }} | {{ t.dependents }} |
{% endfor %}
{% if impact.touched_more %}

and {{ impact.touched_more }} more.
{% endif %}
{% if impact.access %}

**Access that moves**, whatever the data's class:

| Who | | What | Class |
| --- | --- | --- | --- |
{% for a in impact.access %}
| {{ a.who }} | {{ a.change }} | {{ a.what }} | {{ a.class }} |
{% endfor %}
{% if impact.access_more %}

and {{ impact.access_more }} more.
{% endif %}
{% endif %}
{% if impact.relies %}

**Dependencies the change touches** (code calls and `theseus.yaml` requirements):

| Who | Needs | From | State |
| --- | --- | --- | --- |
{% for r in impact.relies %}
| {{ r.who }} | {{ r.needs }} | {{ r.source }} | {{ r.state }} |
{% endfor %}
{% if impact.relies_more %}

and {{ impact.relies_more }} more.
{% endif %}
{% endif %}

**Cost:** {{ impact.cost }}

</details>

{% endif %}
{% if opened %}
<details>
<summary><b>Step by step</b> ({{ opened|length + opened_more }} {{ "way" if opened|length + opened_more == 1 else "ways" }} in, each linked to its line)</summary>

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
{% if nothing_passes %}<summary><b>All {{ fixes|length }} fixes Theseus tested</b>, each on a copy of the graph</summary>{% elif fixes|length == 1 %}<summary><b>The fix that passes</b>, tested on a copy of the graph</summary>{% else %}<summary><b>{{ fixes|length }} fixes that pass</b>, each tested on a copy of the graph</summary>{% endif %}


{% if cut %}
**Smallest change:** {{ cut }}

{% endif %}
| Fix | Dangerous paths | Required access | Code calls | Verdict |
| --- | --- | --- | --- | --- |
{% for row in fixes %}
| {{ row[0] }} | {{ row[1] }} | {{ row[2] }} | {{ row[3] }} | {{ row[4] }} |
{% endfor %}

{% if nothing_passes %}
No fix passes every check. The table shows what each one breaks.

{% endif %}{% if other_fixes %}
{{ other_fixes }}

{% endif %}
{% if apply_hint %}
{{ apply_hint }}

{% endif %}
</details>

{% endif %}
{% if unknowns %}
<details>
<summary><b>What Theseus couldn't check</b> ({{ unknowns_count }})</summary>

{% for u in unknowns %}
- {{ u }}
{% endfor %}
{% if unknowns_more %}
- and {{ unknowns_more }} more not shown.
{% endif %}

</details>

{% endif %}
<details>
<summary><b>Details</b></summary>

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

and {{ unchanged_more }} more: every path is on the graph page.
{% endif %}

{% endif %}
{{ coverage }}

{{ timings }}
{% if versions %}

{{ versions }}
{% endif %}

</details>

<details>
<summary><b>About Theseus</b></summary>

Theseus maps who can reach what in your infrastructure, as a graph in FalkorDB. It blocks a PR that opens a new way to sensitive data, and links every step to the line behind it.

</details>
