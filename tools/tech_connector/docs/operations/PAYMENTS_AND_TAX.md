# Payments, Tax, Refunds, and Reconciliation

Stripe is an adapter, not the licensing authority. A verified, idempotent Stripe
webhook updates canonical backend records; only backend policy may create or
change a license. Never accept a price, license type, seat count, studio band, or
entitlement capability directly from browser-supplied metadata.

Create versioned provider products/prices for the approved private offer catalog.
Current business direction is USD $200 per Indie named user/year, USD $500 per
Indie perpetual major version, and USD $200 per named-user major upgrade. The
Enterprise launch draft is USD $1,500 per named user/year with a five-seat
minimum, USD $1,250 at 25+ seats, or USD $3,500 perpetual per named user with a
five-seat minimum. These remain configuration, not client code or a legal offer,
until commercial and legal approval.

Before sales, the company must establish its merchant identity and bank payout,
choose supported sale countries/currencies, obtain required tax registrations,
configure Stripe Tax registrations and product tax codes, decide invoice and
receipt content, configure refunds/cancellations/renewal notices, and document
chargeback and failed-payment effects. Stripe Tax calculation does not create a
tax registration or replace professional tax advice.

Verify webhook signature rejection, duplicate delivery, out-of-order delivery,
refund, dispute, renewal, cancellation, seat quantity change, tax calculation,
invoice finalization, and daily provider-to-database-to-bank reconciliation.
Evidence is a protected merchant readiness review, tax-adviser reference,
provider configuration export/reference, and successful test transaction IDs.

