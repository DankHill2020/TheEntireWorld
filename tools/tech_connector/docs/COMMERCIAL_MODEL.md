# Tech Connector Commercial Model

This document is a practical summary of the
[Tech Connector Community Source License](../LICENSE.md). If this summary and
the license conflict, the license controls.

Tech Connector is designed around one principle:

**We succeed when our users succeed.**

The tools should lower the barrier to high-end creative and technical work.
Individuals should be able to learn, build, experiment, and ship without a
subscription wall. Larger commercial beneficiaries should help fund continued
development once the tools create meaningful value for them.

## Free Use

Tech Connector is free for:

- individuals;
- students and educators;
- hobbyists and researchers;
- nonprofits;
- open-source projects;
- independent creators;
- small studios and startups below the commercial threshold.

You own the work you create with Tech Connector.

If a registered project never exceeds the profit threshold, it never owes a residual.

## Community Project Registration and Success Threshold

Community commercial use requires a verified account, acceptance of the current
license, and registration of each commercial project under a Community license.

No residual is owed on the first USD $500,000 of Adjusted Project Profit for a
registered project. Only profit above that threshold may be subject to a
success-based residual.

The threshold is measured cumulatively over the registered project's lifetime.
Adjusted Project Profit is project receipts minus true Eligible Project Costs.
Eligible costs must be actually paid or incurred, documented, ordinary,
necessary, reasonable, and directly attributable to the project. Examples can
include genuine project labor, contractors, project-specific software and
services, production assets, render/cloud usage, distribution fees, and direct
project marketing.

Reasonably allocated shared costs can count when the allocation is documented,
consistent, and proportionate. Owner or affiliate charges count only for real
goods or services and only up to an arm's-length fair-market amount.

Actual reasonable compensation for genuine owner or founder work can count.
Unpaid founder time counts only if the accepted project terms establish a
pre-agreed capped labor allowance and the time is recorded as the work occurs.
It cannot be invented or repriced retroactively after a project succeeds.

The following do not reduce Adjusted Project Profit:

- owner draws, dividends, and profit distributions;
- personal, unrelated, or excessive general expenses;
- artificial management fees or unsupported corporate allocations;
- inflated owner, affiliate, or related-party charges;
- entity-level income taxes, unrelated financing costs, fines, and penalties;
- reimbursed or double-counted costs;
- costs already attributed to another registered project; or
- transactions or project splits primarily designed to avoid the threshold.

This is intended to recognize real production economics, not punish legitimate
costs. Financial reporting should request reasonable accounting records only;
it must not require project assets, scenes, source files, animation, or other
creative content.

The applicable marginal schedule is selected from versioned terms based on
studio size and any custom conditions agreed for the project. Smaller creators
and studios can therefore receive lower rates than larger firms. Each rate
applies only to profit inside its bracket, so reaching a new bracket never
reprices earlier profit. The signed entitlement records the exact calculation
basis, lifetime measurement period, threshold, brackets, reporting schedule,
and terms version accepted for the project.

Economic terms are not hardcoded into the application. An accepted terms
version remains identifiable and auditable; later terms should not silently or
retroactively replace the terms attached to an existing project entitlement.

## Indie Licenses

Indie is a customer classification, not a single hardcoded price. A qualifying
individual or small studio can receive a Community success-based grant, a paid
perpetual grant, or negotiated custom terms. The signed entitlement records the
studio-size band, classification-rules version, offer ID, exact project terms,
seat/device limits, version rights, and support level.

This allows a lower success-based rate or a different paid offer for smaller
teams without embedding employee thresholds, prices, or percentages in the
public application. Reclassification affects a future offer or negotiated
renewal; it must not silently rewrite immutable terms already accepted for a
registered project.

Paid Indie licenses are assigned per named human user, not shared per studio.
Each user signs in with a verified account and receives their own seat
assignment and reasonable device allowance. Enterprise licenses follow the same
named-user rule, with organization administrators managing the purchased pool.
See [PRICING_MODEL_DRAFT.md](PRICING_MODEL_DRAFT.md) for the nonbinding launch
price recommendation and market references.

## Core and the Official Tools Bundle

Tech Connector Core and the complete Official Tools Bundle are composable
products. Core can use user-owned project directories and independently
obtained tools. The optional Official Tools Bundle contains the complete
approved first-party DCC and pipeline collection; individual hosts and tools are
not sold as separate packs.

An offer can provide Core alone, Core plus the full bundle, or negotiated
enterprise capabilities. The bundle can be downloaded independently and added
through the same local project/tool directory configuration that Core already
uses. The signed `official_tools_bundle` capability controls access to the
first-party bundle. Prices and offer composition remain versioned backend
configuration rather than client constants.

## Enterprise and IP Use

The public version may not be used to create, process, automate, test,
demonstrate, or otherwise work with major corporate IP. A separate written
enterprise license is required before Tech Connector is used for:

- commercial internal pipelines at companies above 25 employees;
- major corporate IP, including film, television, game, animation, software,
  media, character, brand, or franchise IP owned or controlled by a major
  corporation;
- contractor, vendor, freelancer, employee, consultant, or service-provider work
  on behalf of a major corporation or major corporate IP project;
- paid automation or production services above the commercial threshold;
- hosted access, SaaS, cloud services, marketplace tools, or plugin platforms;
- redistribution of Tech Connector or modified Tech Connector.

## No Resale

You may not resell Tech Connector.

This includes selling, sublicensing, repackaging, hosting, redistributing, or
commercializing:

- Tech Connector itself;
- modified versions of Tech Connector;
- generated builds of Tech Connector;
- substantially similar products based on Tech Connector source code;
- hosted access to Tech Connector.

Commercial success licensing allows use of the tools in commercial work. It does
not allow selling the tools themselves, reusing their code in another product,
or using the public version with major corporate IP.

## No AI Training or Direct Code Reuse

Tech Connector source code, documentation, prompts, function signatures, call
plans, API traces, generated wrappers, and internal automation logic may not be
used to train, fine-tune, distill, benchmark, evaluate, embed, or otherwise
improve AI systems or competing automation tools.

The intended programmable access path is through Tech Connector itself:

- the licensed desktop app;
- a licensed local service;
- a licensed hosted API;
- an SDK or plugin interface expressly authorized by The Entire World, LLC.

Users are welcome to call Tech Connector functions from prompts or through
official APIs when their license tier allows it. They may not copy those
functions out of the project, wrap them as their own product, train a model on
them, or build a parallel system that bypasses Tech Connector.

Source availability does not grant permission to copy, extract, reuse,
repackage, sublicense, sell, host, provide, or incorporate Tech Connector source
code, architecture, prompts, workflows, UI, services, documentation, examples,
generated plans, or related materials into any separate product, service, tool,
plugin, platform, internal system, or commercial offering.

## Source-Available, Not Open Source

Tech Connector is source-available. The source can be viewed, studied, run
locally, modified for allowed use, and contributed to.

It is not an OSI open-source project because commercial use and redistribution
may require separate permission.

This distinction matters. We can still support community involvement while
protecting the business model that funds development.

## Data and Outputs

Users own their outputs.

Tech Connector does not claim ownership of user-created games, films, assets,
animations, code, workflows, rigs, scenes, plugins, documents, or other work
product.

Private user data and private outputs should not be used for training without
explicit permission.

## License Verification and Provenance

Tech Connector can use the same installed application for personal, commercial,
and enterprise users. The user's login/license token determines which
entitlements are unlocked.

Generated code, exported assets, and project-level automation records may
include transparent Tech Connector provenance markers. These markers are meant
to support license compliance and troubleshooting. They can include:

- license tier;
- hashed license/account identifiers;
- hashed project identifier;
- operation name;
- output path;
- no-resale/no-hosting/no-redistribution flags.
- no-AI-training and official-API-required flags.

Markers should not include raw private emails, private tokens, secrets, or
unpublished user data.

The intent is auditability, not hidden tracking. Network telemetry or training
on private data should remain opt-in and explicit.
