# Tech Connector Pricing Model — Launch Draft

Status: commercial strategy draft; not an offer or controlling legal terms

Last reviewed: 2026-09-28

This model keeps Community accessible, gives independent creators a predictable
way to eliminate residuals, and charges professional organizations per actual
user. All prices, eligibility rules, discounts, and residual terms belong in a
private versioned offer catalog. They must not be hardcoded into the client.

## Recommended launch model

### Community Success

- Price: USD $0 upfront.
- Identity: every user has their own verified account; no paid seat purchase.
- Commercial projects must be registered.
- No residual is owed on the first USD $500,000 of lifetime Adjusted Project
  Profit per registered project.
- Residuals use marginal brackets on Adjusted Project Profit above the threshold:

  | Lifetime Adjusted Project Profit | Solo | Micro, 2–5 people | Small, 6–25 people |
  | --- | ---: | ---: | ---: |
  | First $500,000 | 0% | 0% | 0% |
  | $500,000–$1,000,000 | 0.50% | 0.75% | 1.00% |
  | $1,000,000–$5,000,000 | 0.75% | 1.00% | 1.25% |
  | Above $5,000,000 | 1.00% | 1.25% | 1.50% |
- Organizations above 25 people, major corporate IP work, hosted services, and
  redistribution require an Enterprise or Custom agreement.

Studio size should include employees and regularly engaged contractors across
affiliated entities. Artificial entity splitting, short-term staffing changes,
or moving the same project between entities must not lower the applicable band.
The accepted band, classification version, marginal schedule, threshold, and
terms ID are frozen into the signed project entitlement. Each rate applies only
to profit inside that bracket; crossing a boundary never reprices lower profit.

### Indie Named User

- Annual: USD $200 per named user per year. An active annual license receives
  all releases during its paid term.
- Perpetual: USD $500 per named user for the purchased major version.
- Perpetual minor and patch updates are free through the final release of that
  major version.
- Upgrade to a new major version: USD $200 per named user. Upgrading is optional;
  the licensed prior major version remains perpetual.
- Two registered devices per named user, for that user only.
- Recommended offline validity window: 60 days, capped by the signed entitlement.
- No project residual for work created under the paid covered version.
- Standard self-service support and updates during the paid term; perpetual
  support and future major versions are separate purchases.
- Eligibility target: organizations of 25 or fewer people that are not doing
  major-corporate-IP work requiring an Enterprise agreement.

Annual and perpetual are the two launch offers; no monthly SKU is needed at
launch. Perpetual protects the promised no-residual path without committing
future major versions or indefinite support.

### Product packaging

Launch has two composable products, not individual DCC tool packs:

- `tech_connector.core`: the licensed application, including user-owned project
  and tool-directory support.
- `official_tools_bundle`: the complete optional first-party Maya, Blender,
  Houdini, 3ds Max, MotionBuilder, Substance Painter, Unreal, utility, plugin,
  and Qt collection.

The bundle may be included in an offer or sold as one add-on. Do not create
separate host, rigging, animation, or game-engine tool SKUs. The bundle's final
price and offer inclusion are intentionally unset pending launch research; they
belong in the private offer catalog rather than the client. A combined installer
does not merge the two entitlement capabilities.

### Enterprise Named User

- Annual: USD $1,500 per named user, with a five-seat minimum.
- Volume price: USD $1,250 per named user at 25 or more seats; larger deals are
  custom rather than an automatic public discount.
- Perpetual: USD $3,500 per named user for the contracted major version,
  with a five-seat minimum.
- Perpetual minor and patch updates are included for that major version.
- Optional annual support and major-version update plan for perpetual licenses:
  20% of license price.
- Two registered devices per named user. Seat reassignment is administered by
  the organization and governed by a configurable anti-sharing policy.
- Recommended offline validity window: 30 days so revoked staff seats do not
  remain usable for an excessive period; air-gapped deployments are custom.
- Enterprise integrations, deployment assistance, enhanced support, source
  adaptation, hosted use, redistribution, and service/build-agent rights are
  separately scoped contract items.

These are the standard Enterprise draft prices. Larger volume agreements and
nonstandard rights remain custom. Until SSO, centralized administration, SLA
support, and deployment tooling are operational, contracts must price and
promise only capabilities that can actually be delivered.

## Why this range

Current official reference points include:

- [Houdini Indie](https://www.sidefx.com/products/houdini-indie/) at USD $299
  for one year, with a named artist able to use a supplementary second machine.
- [Adobe Substance 3D](https://helpx.adobe.com/substance-3d/pricing-change.html)
  at USD $599.88/year for individuals and USD $1,439.88/year for Teams.
- [Unity Pro](https://unity.com/products) from USD $2,310/year per seat, with
  Enterprise sold through custom pricing.
- [Autodesk Maya](https://www.autodesk.com/products/maya/overview) at USD
  $2,010/year, licensed to a named user and installable on multiple devices.
- [Unreal Engine](https://www.unrealengine.com/license) at USD $1,850/year per
  seat for applicable non-game commercial users, or a 5% game royalty above its
  stated lifetime gross-revenue threshold.

Tech Connector's Indie annual price is intentionally below Houdini Indie and
the Adobe individual collection. The Enterprise price is near
Adobe Teams and below Unity Pro, Maya, and Unreal's applicable professional
seat pricing. The proposed Community residual is materially smaller than a 5%
gross-revenue engine royalty because it applies only to Adjusted Project Profit
above the Tech Connector threshold.

## Backend offer representation

Suggested immutable offer identifiers:

- `community-success-solo-2026a`;
- `community-success-micro-2026a`;
- `community-success-small-2026a`;
- `indie-annual-2026a`;
- `indie-perpetual-v7-2026a`;
- `indie-upgrade-v8-2026a`;
- `enterprise-annual-2026a`; and
- negotiated custom offer IDs generated per agreement.

Each offer record should specify currency, billing period, unit amount,
eligibility/classification version, grant model, market segment, included major
versions, support, seat/device limits, product capabilities (including
`official_tools_bundle` when applicable), and referenced project terms. A
project or perpetual grant retains the immutable accepted offer and terms IDs
even after the public catalog changes.

## Decisions required before publishing prices

- Validate willingness-to-pay with at least 10 indie creators and 5 studios.
- Confirm sales tax/VAT handling, refunds, renewals, regional pricing, and
  currency policy with payment and tax providers.
- Have counsel approve studio-size aggregation, contractor treatment,
  anti-avoidance language, perpetual rights, and residual reporting.
- Model support cost and payment fees at the proposed Enterprise floor.
- Decide whether launch customers receive a time-limited founder discount;
  preserve the list price and represent any discount in the backend offer.
- Decide which launch offers include the complete Official Tools Bundle and the
  single add-on price, without introducing individual tool-pack SKUs.
