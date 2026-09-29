# Tech Connector Core

> **Source available — not open source. Account activation is required.**
>
> Cloning this repository or downloading a release does not create an activated
> entitlement or grant unrestricted redistribution, resale, sublicensing, or
> commercial exploitation. See the [Tech Connector Community Source License](LICENSE).

Tech Connector Core is the local-first desktop and headless production
environment for DCC applications and game engines. Official use requires a
registered account, verified email, acceptance of the applicable versioned
license, and a signed entitlement. The client caches that signed entitlement
for its allowed offline period; private signing keys never ship in this repo.

The optional **Official Tools Bundle** is distributed separately through an
account-gated download or private repository. It can be installed beside Core
or added through Core's existing project/tool directory settings. User-owned
project directories and independently obtained tools remain usable without the
bundle entitlement.

## Privacy boundary

Licensing sends only the minimum identity, entitlement, project-registration,
and pseudonymous activation metadata required to enforce the agreement. It does
not upload project assets, scenes, source files, animation data, prompts, or
other creative work. See [the privacy notice](tech_connector/PRIVACY.md).

## Source layout

- `tech_connector/` — application, headless API, bridges, engine runtime,
  client-side entitlement verification, documentation, and packaging tools.
- `reasoning_runtime/` — local planning and execution runtime used by Core.

## Development setup

The desktop release target is Python 3.14:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r tech_connector\packaging\requirements-runtime.txt
.\.venv\Scripts\python.exe -m tech_connector.app.main_window
```

The source launcher follows the same activation flow as an installed build; it
does not provide an automatic development or Community-license bypass. More
detail is in [the Tech Connector guide](tech_connector/README.md) and
[source-access model](tech_connector/docs/SOURCE_ACCESS_MODEL.md).
