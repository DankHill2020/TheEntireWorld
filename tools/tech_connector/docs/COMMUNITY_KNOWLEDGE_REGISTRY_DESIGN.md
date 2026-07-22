# Community Knowledge Registry Design

## Purpose

Share verified Unreal, animation, traversal, combat, puzzle, DCC, and import
techniques without turning community submissions into trusted executable code.
The local project remains authoritative. Community knowledge proposes evidence;
local capability, compatibility, compile, and runtime gates decide whether it
can be used.

Only open information may be promoted into reusable or community knowledge.
That means public HTTPS access plus open reuse terms, or official public
documentation used with attribution. Authenticated, paid, private,
project-confidential, or personally identifying information is ineligible for
reusable or community knowledge. A user-owned restricted source may support
the current task only after authentication, entitlement verification, and
explicit task approval. Learning from it is a separate opt-in, must remain in
a project-local model/index, and can never enter community credits, exports,
or shared knowledge packets.

## Knowledge Packet

Each immutable packet should contain:

- Packet id, schema version, author identity, signature, creation time, and revision lineage.
- Domain tags and semantic roles such as `ledge_shimmy` or `paired_disarm_victim`.
- Unreal/DCC/tool versions and relevant plugin versions.
- Input contracts, target asset classes, skeleton hierarchy fingerprints, and proportion measurements.
- Source URLs, provider, license text/hash, entitlement requirements, and retrieval time.
- Exact registered operations used, parameters with secrets removed, and dependency order.
- Created/modified asset paths and content hashes.
- Static validation, compile output, reference readback, runtime scenario, and observed assertions.
- Failure records, rollback result, known limitations, confidence, and evidence expiry policy.

Packets must not contain credentials, machine-specific absolute paths, opaque
binary executables, or an unreviewed claim of success.

## Source Scopes

- `community`: public HTTPS plus open reuse terms or official public documentation; eligible for credits and verified sharing.
- `task`: authenticated and entitled user-owned material with explicit approval; usable only for the current authorized task.
- `local_learning`: a second explicit opt-in for entitled restricted material; stored project-locally and excluded from all sharing.
- `denied`: missing entitlement, missing authentication, missing consent, or uncertain ownership; cannot be used.

Authenticated marketplace motions and other user-owned restricted downloads
remain asset records. Their files, license/entitlement metadata, hashes, and
project-local search metadata belong in the asset provenance ledger, never in
the technique registry or community Credits. Local asset indexing must not be
silently upgraded into model training.

## Trust Model

1. Download packets into a quarantine index. Do not execute them.
2. Verify schema, signature, source availability, license, and hash integrity.
3. Compare engine/plugin versions and target fingerprints with the live project.
4. Resolve every operation through the local registered capability registry.
5. Re-run the packet's preflight and validation on disposable or duplicated assets.
6. Promote only locally reproduced results to project knowledge.
7. Decay confidence when sources disappear, versions diverge, or later runs fail.

Community votes and download counts are discovery signals, not validation.

## Offline Behavior

The registry is optional. When offline, use locally promoted packets and the
project index. `run_with_current_knowledge` may create isolated prototypes but
cannot substitute missing contextual assets or report completion without the
same compile and runtime evidence required online.

## Integration Point

`unreal_animation_knowledge_continuation_v1` already separates:

- semantic role contracts;
- local knowledge records;
- provider research targets;
- candidate acceptance requirements;
- missing capabilities and completion gates.

A future community connector should add signed candidate packets to this
structure. It must not bypass `external_animation_target_policy`, ActionGraph
approval, asset provenance, retarget validation, Blueprint compilation, or PIE
runtime assertions.
