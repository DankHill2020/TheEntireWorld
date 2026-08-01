# Unreal Gameplay Proof And Knowledge Policy

This policy applies to every prompt-built Unreal gameplay, traversal, combat,
ability, animation, puzzle, AI, UI, VFX, audio, networking, and persistence
feature.

## Meaning Of Done

Compilation is structural evidence only. A feature is complete only when the
system has gathered trusted evidence for all six levels:

1. Static structure: assets resolve, graphs and references are reachable, and
   touched code and Blueprints compile without relevant warnings.
2. Construction: the played instance owns the expected components, bindings,
   defaults, and initialized references.
3. Runtime path: the public trigger reaches the intended branches and state
   transitions in PIE, Standalone, Automation, or a Functional Test.
4. Gameplay outcome: authoritative state and the player-visible result match
   the prompt contract, including contextual animation playback when required.
5. Negative and boundary behavior: invalid targets, early release,
   interruption, repeated activation, contact loss, missing assets, and other
   relevant failures restore a valid state.
6. Regression: adjacent input, movement, animation, combat, spawning,
   persistence, networking, timers, delegates, logs, and performance remain
   valid.

Every runtime claim must name its observation method, comparator, expected
value, observed value, evidence origin, and scenario. Planned assertions and
compiler success never count as observed gameplay evidence.

## Planning Contract

Before mutation, preserve explicit trigger, input alternatives, timing
thresholds, scope words such as `any` or `every`, requested artifacts, and
player-visible outcomes. Resolve the played pawn, authoritative gameplay owner,
current AnimBlueprint, target mesh/skeleton, input path, dependencies, and
existing reusable systems from the live project.

Gameplay state belongs to a character, component, ability, subsystem, or other
appropriate gameplay owner. An AnimBlueprint consumes that state and produces
pose. Do not replace an existing AnimBlueprint merely to add one mechanic.

Feature-scale requests always stop at a visible implementation plan before
mutation, even when the user did not explicitly ask for a plan. The Unreal
bridge remains fully capable of mutation, but its planning phase may issue only
inspection, reflection, indexing, and other read-only calls. Small explicit
atomic commands may use their normal confirmation policy.

Seal each plan with a deterministic fingerprint and revision. Approval applies
only to that exact fingerprint. A reply that adds, removes, corrects, expands,
or otherwise changes scope creates a new read-only revision with a visible
delta and requires new approval. Discovery of a material implementation change
after approval also returns to planning. Unsealed, altered, stale, or merely
implied approval must never authorize execution.

Users may elaborate, correct, add, or remove plan behavior. Apply the latest
instruction against the prior request, regenerate affected states, transitions,
animation roles, operations, assets, proof scenarios, and rollback scope, and
show what was added, removed, changed, and preserved.

## Novel Behavior Understanding

Known primitives are vocabulary and verified tools, not a whitelist of systems.
For each feature, synthesize a prompt-specific behavior contract containing
clause coverage, triggers, observations, guards, states, transitions, outcomes,
cancellation, failures, presentation roles, atomic operations, and proof
scenarios. A deterministic critic must reject missing clauses, undeclared
states, irrelevant operations, invented presentation requirements, and empty
proof paths.

For unfamiliar mechanics, propose new atomic capability keys and route them to
capability acquisition instead of forcing the request into the nearest known
system. Model-authored contracts are provisional and cannot mutate assets or be
learned as recipes until grounded operations and all required proof gates pass.
If model synthesis fails but verified primitives fully cover the prompt, retain
the grounded composition and report the rejected augmentation. If neither path
covers the request, offer knowledge acquisition or an isolated current-
knowledge prototype; do not guess.

## Animation Acceptance

An animation found by name is only a candidate. It becomes accepted only after
semantic role, source and license, skeleton or measured retarget result,
duration, loopability, root motion, contacts, displacement, target-character
preview, graph consumption, and PIE playback all pass. A technically successful
import or bake is not a usable gameplay animation by itself.

## Technique Knowledge Versus System Recipes

A technique record may describe how a capability probably should be composed,
such as traces, custom movement modes, linked animation layers, graph editing,
retargeting, or montage slots. It is a prior for planning, not proof of a whole
feature.

A system recipe such as `Climbing System` is reusable only after all required
capability, asset, contextual animation, compile, graph, construction, runtime,
gameplay outcome, negative-path, regression, and clean-log gates pass. Its proof
contract must cover Levels 1 through 6 with trusted Unreal or explicit human
observation. Failed and partial episodes remain diagnostic history and cannot be
retrieved as known wins.

Atomic techniques may use narrower gates appropriate to their scope. They may
not be promoted or described as end-to-end gameplay systems.

## Known Wins And Current Research

A verified known win is the baseline and rollback path, not a timeless answer.
For each new feature, assess engine-version fit and source freshness. Offer a
current-source comparison by default, and require it when the user asks for a
newer/current/latest approach, sources are missing, or engine versions differ.

Compare approaches on live project architecture, engine API/plugin support,
runtime and multiplayer requirements, asset compatibility, failure handling,
regression risk, and measured proof. A newer candidate replaces the baseline
only after it passes the same isolated proof contract.

Use current official documentation and primary repositories first. Public
tutorials may contribute attributable patterns. Paid, authenticated, private,
or confidential material cannot become shared reusable knowledge. Retain URL,
author/provider, retrieval date, engine version, prerequisites, claim, access
class, reuse terms, and credits for adopted open knowledge.

When required technique evidence is absent locally, automatically refresh known
public source pointers first, then search for uncovered claims. Remove project
paths, asset identifiers, local file paths, account data, and other project
identity from outbound queries. Source discovery creates candidates only. A
claim becomes usable for the current plan only when a fetched HTTPS source
contains an exact bounded supporting quote. Model output without that support is
rejected. Public material with unknown reuse terms may guide the current task
but cannot be learned, credited as reusable knowledge, or community-shared.

When a prompt requires an asset role that the live project index cannot satisfy,
automatically search registered public open asset providers during preflight. Do
not silently query authenticated, paid, private, or entitlement-gated providers.
Search results are provenance-bearing candidates, not accepted assets. Download,
retarget, import, destination selection, and Unreal mutation remain contingent
operations in the exact user-approved plan. For animation, no candidate may pass
until target-skeleton compatibility, contextual target-character preview, graph
consumption, and PIE playback all succeed.

Automatic research is read-only and never authorizes Unreal mutation. After the
plan is approved, the writable Unreal bridge may execute only the operations in
the approved fingerprint, then compile, read back graph topology and references,
save approved assets, and gather runtime proof. Any material deviation returns
to a new plan revision.

When online research is unavailable, offer the user `add knowledge first` or
`run with current knowledge`. The latter permits only an isolated prototype and
does not relax completion gates.

## Self-Repair

After a failed proof attempt, locate the earliest divergence in trigger,
ownership, initialization, reference, timing, state, asset, integration, or
implementation. Repair that cause, rerun the failed level, and rerun affected
earlier and later levels. Stop only at verified completion or a concrete
external blocker.

## Reporting

Final reports must separate implemented behavior from planned behavior and list
changed files/assets, complete trigger-to-outcome execution path, evidence per
acceptance criterion, failures repaired, regressions checked, and exact
remaining limitations. Never use `working`, `complete`, or `shippable` for a
feature supported only by asset creation, graph wiring, compilation, or
theoretical correctness.
