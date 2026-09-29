# Repository-root release files

These files must be copied to the actual Git repository root before public
launch:

- `LICENSE` → `<repository>/LICENSE`
- `.github/workflows/tech-connector-release.yml` → the same repository-root path

The existing root `README.md` must also retain its prominent **Source available
— not open source. Account activation is required.** notice. It explains that a
GitHub release, clone, or ZIP download is not activation and that the
application stays locked until license acceptance and a signed entitlement are
verified.

They are stored as templates here because the Tech Connector workspace may be
mounted at `<repository>/tools` without write access to its parent.
