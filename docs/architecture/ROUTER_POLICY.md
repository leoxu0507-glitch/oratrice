# Declarative router policy (M3)

M3 keeps route selection as a side-effect-free policy boundary.  The
composition root reads `defaults.router.strategy` and constructs an immutable
`router.policy.RoutingPolicy`.  `GemmaRouterProvider` receives that object as
`decision_policy`; it does not own YAML parsing, provider construction, or
runtime lifecycle.

## Candidate catalogue

Each strategy candidate declares an opaque gateway model alias, a canonical
provider ID, optional task/complexity labels, capability labels, an integer
priority, and `requires_cloud_opt_in`.  The live profile uses the existing
aliases `gpt_oss`, `qwen_vl`, and `deepseek_reasoner`; no model or provider ID
is hard-coded in Python.

The adapter's global `allowed_models`/`allowed_providers` are the union of the
configured allow-list and every strategy candidate.  This is a strict parser
allow-list only.  It prevents a valid strategy response from being rejected
before policy evaluation, but it does not enable cloud inference.

For each request, `RoutingPolicy.prompt_candidates(request)` creates a fresh
`candidate_catalog`.  Candidates marked `requires_cloud_opt_in: true` are
omitted unless request metadata contains the configured key (the live profile
uses the exact boolean `metadata.allow_cloud: true`).  `validate(request,
decision)` then enforces the highest-priority matching candidate, capabilities,
task/complexity labels, and the same cloud gate.

Ordinary local-first prompts therefore never advertise the DeepSeek candidate;
an explicit caller opt-in is required.  The policy does not perform health
checks, network calls, process startup, provider invocation, or answer the
user.  Router output remains a `RouteDecision` consumed by the core facade.

## Deferred path

The Qwen vision/OCR candidate is declarative and local-first.  Its complete
LiteLLM multimodal execution chain remains deferred; adding the candidate does
not start its runtime or claim that the end-to-end vision path is available.
