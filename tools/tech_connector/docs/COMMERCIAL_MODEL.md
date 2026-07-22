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

If you never make money from use of the tools, you never owe royalties.

## Commercial Success Threshold

Commercial use of the public version is free until Attributable Revenue reaches
USD $500,000 in a rolling 12-month period.

After that threshold, continued public-version commercial use carries a rolling
commercial-success residual unless a separate written agreement says otherwise.

The default residual model is a marginal bracket calculation on Attributable
Profit above the USD $500,000 threshold. Of this success share residual, The Entire World
takes half (50%) and the other half (50%) is put directly towards supporting other independent
creators, community projects, and industry initiatives.

The marginal brackets are:

- 0% below the USD $500,000 threshold;
- 1.0% on the portion above USD $500,000 up to USD $1,000,000;
- 2.0% on the portion above USD $1,000,000 up to USD $2,000,000;
- 3.0% on the portion above USD $2,000,000 up to USD $5,000,000;
- 5.0% on the portion above USD $5,000,000.

Example: if Attributable Profit is USD $3,000,000 in the rolling 12-month
period, the residual is USD $55,000 (of which $27,500 goes to The Entire World and $27,500 is allocated to industry initiatives):

- 0% on USD $500,000 = USD $0;
- 1.0% on USD $500,000 = USD $5,000;
- 2.0% on USD $1,000,000 = USD $20,000;
- 3.0% on USD $1,000,000 = USD $30,000.

These numbers are intended to be predictable and founder-friendly. A separate
written agreement may define different thresholds, caps, reporting terms, or
enterprise terms.

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
