"""Generate a self-signed X.509 certificate + PFX bundle for App Registration."""

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def generate_cert(tenant_name: str) -> dict:
    """Create a self-signed cert valid for 2 years.

    Returns dict with keys:
        cert_pem_b64  – base-64 encoded DER of the certificate (for Graph keyCredentials)
        private_key_pem – PEM-encoded private key (string)
        pfx_bytes     – PKCS12 bundle bytes
        pfx_password  – password protecting the PFX
        thumbprint    – SHA-1 thumbprint of the cert (hex, used as customKeyIdentifier)
    Also writes the .pfx to output/{tenant_name}/cert.pfx
    """
    # Generate RSA key
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"{tenant_name}-app-cert"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, tenant_name),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=730))
        .sign(private_key, hashes.SHA256())
    )

    # PEM-encoded private key
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    # DER-encoded certificate → base64 (what Graph API expects for keyCredentials)
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_pem_b64 = base64.b64encode(cert_der).decode()

    # SHA-1 thumbprint (customKeyIdentifier)
    thumbprint = hashlib.sha1(cert_der).hexdigest()

    # PFX / PKCS12 bundle
    pfx_password = secrets.token_urlsafe(16)
    pfx_bytes = serialization.pkcs12.serialize_key_and_certificates(
        name=tenant_name.encode(),
        key=private_key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(pfx_password.encode()),
    )

    # Persist to disk
    out_dir = os.path.join(os.path.dirname(__file__), "output", tenant_name)
    os.makedirs(out_dir, exist_ok=True)
    pfx_path = os.path.join(out_dir, "cert.pfx")
    with open(pfx_path, "wb") as f:
        f.write(pfx_bytes)
    print(f"  [cert] Saved PFX → {pfx_path}")

    return {
        "cert_pem_b64": cert_pem_b64,
        "private_key_pem": private_key_pem,
        "pfx_bytes": pfx_bytes,
        "pfx_password": pfx_password,
        "thumbprint": thumbprint,
    }
