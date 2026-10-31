# Production Account and Entitlement Backend

The reference private service uses Auth0, Cloud Run, Cloud SQL for PostgreSQL,
Stripe, and Google Cloud KMS behind replaceable adapters. Production must use a
dedicated cloud project/account, separate staging and production resources,
least-privilege service identities, protected secrets, HTTPS only, database
migrations, and no public database address unless independently justified.

Before verification:

1. Configure Auth0 Universal Login, verified email, recovery, MFA for admins,
   allowed callback/logout URLs, Organizations, bot protection, and separate
   production API audience.
2. Deploy an immutable backend image and run migrations using a dedicated
   migration identity. The runtime identity may connect to the database, read
   required secrets, and call only the specific KMS signing key version.
3. Populate versioned agreements and offers through reviewed configuration.
   Prices, residual rates, studio-size rules, device limits, support, versions,
   and capabilities must never be inferred by the public client.
4. Publish the KMS public key in `licensing.json` under its `kid`, fill all exact
   HTTPS endpoints, and verify that redirects are disabled.
5. Exercise new account, email verification, acceptance, Community project
   registration, Indie/Enterprise named seats, activation limit, replacement,
   60-day/30-day offline policy, revocation, payment webhook idempotency, and
   historical acceptance viewing.
6. Confirm logs contain no passwords, bearer/refresh tokens, payment secrets,
   private keys, project paths, assets, scenes, prompts, or creative content.

The evidence reference should point to the deployment revision, migration,
smoke-test result, and approval—not to a secret or raw customer record.

