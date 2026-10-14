# Theseus

Theseus reviews Terraform pull requests as a graph in FalkorDB. It shows which sensitive data a change makes
reachable, compares that with what the PR says and what the code calls, proves the smallest safe fix on graph
copies, and commits it once a person approves. Built for FalkorDB Graph Hacks, Track 01.