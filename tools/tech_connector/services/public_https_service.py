"""Verified HTTPS context for bundled Python and DCC runtimes."""

from __future__ import annotations

import os
from pathlib import Path
import ssl


def create_public_https_context() -> ssl.SSLContext:
    """Create a verifying TLS context with portable and Windows trust roots."""

    context = ssl.create_default_context()
    explicit_bundle = str(os.environ.get("SSL_CERT_FILE") or "").strip()
    if explicit_bundle and Path(explicit_bundle).is_file():
        context.load_verify_locations(cafile=explicit_bundle)
        return context

    try:
        import certifi  # type: ignore[import-not-found]

        context.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass

    if os.name == "nt" and hasattr(ssl, "enum_certificates"):
        try:
            roots = [
                ssl.DER_cert_to_PEM_cert(certificate)
                for certificate, encoding, _trust in ssl.enum_certificates("ROOT")
                if encoding == "x509_asn"
            ]
            if roots:
                context.load_verify_locations(cadata="".join(roots))
        except (OSError, ssl.SSLError, ValueError):
            pass
    return context
