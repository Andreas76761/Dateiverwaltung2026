"""HTTPS für das lokale Netz: eigene kleine Zertifizierungsstelle (CA) + Serverzertifikat für Rechnername und LAN-Adressen.

    python -m app.tls erstellen     # legt <data_dir>/tls/ca.pem, server.pem, server-key.pem an (vorhandene bleiben erhalten)
    python -m app.tls zeigen        # Fingerabdruck der CA – zum Abgleich auf den Agent-Computern

Agenten prüfen den Server über den CA-Fingerabdruck (`--fingerprint`): Beim ersten Kontakt wird die CA geladen, mit dem
Fingerabdruck verglichen und gespeichert; danach ist jede Verbindung verschlüsselt und gegen Abhören/Umleiten geschützt.
Im Browser erscheint einmalig eine Warnung (eigenes Zertifikat) – optional `ca.pem` als vertrauenswürdig importieren.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket
import sys
from pathlib import Path

from .config import get_settings



def _cn(name: str) -> str:
    """Zertifikatsname höchstens 64 Zeichen (lange Mac-Rechnernamen); gültig ist ohnehin der SAN-Eintrag."""
    return name if len(name) <= 64 else name[:61] + "..."

def tls_dir() -> Path:
    d = get_settings().data_dir / "tls"
    d.mkdir(parents=True, exist_ok=True)
    return d


def paths() -> dict[str, Path]:
    d = tls_dir()
    return {"ca": d / "ca.pem", "ca_key": d / "ca-key.pem", "cert": d / "server.pem", "key": d / "server-key.pem"}


def _local_names() -> tuple[list[str], list[str]]:
    names = {"localhost", socket.gethostname()}
    try:
        names.add(socket.getfqdn())
    except OSError:
        pass
    ips = {"127.0.0.1", "::1"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(info[4][0].split("%")[0])
    except OSError:
        pass
    return sorted(n for n in names if n), sorted(ips)


def _write_key(path: Path, key) -> None:
    from cryptography.hazmat.primitives import serialization

    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure(extra_names: list[str] | None = None) -> dict[str, Path]:
    """CA und Serverzertifikat anlegen, falls noch nicht vorhanden (bestehende werden nie ersetzt)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    p = paths()
    if p["cert"].exists() and p["key"].exists() and p["ca"].exists():
        return p
    now = dt.datetime.now(dt.timezone.utc)
    if p["ca"].exists() and p["ca_key"].exists():
        ca_cert = x509.load_pem_x509_certificate(p["ca"].read_bytes())
        ca_key = serialization.load_pem_private_key(p["ca_key"].read_bytes(), None)
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _cn(f"Future Dateiverwaltung CA ({socket.gethostname()})"))])
        ca_cert = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
                   .not_valid_after(now + dt.timedelta(days=3650))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   # Schlüssel-Kennungen: von strengen Prüfungen (z. B. Python ≥ 3.13, VERIFY_X509_STRICT) verlangt
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                   .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                                data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                                                encipher_only=False, decipher_only=False), critical=True)
                   .sign(ca_key, hashes.SHA256()))
        _write_key(p["ca_key"], ca_key)
        p["ca"].write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    names, ips = _local_names()
    names += [n for n in (extra_names or []) if n]
    san = [x509.DNSName(n) for n in dict.fromkeys(names)]
    for ip in ips:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _cn(socket.gethostname() or "localhost"))]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=True, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(ca_key, hashes.SHA256()))
    _write_key(p["key"], key)
    # Serverzertifikat + CA als Kette – so prüfen Agenten und Browser die ganze Kette
    p["cert"].write_bytes(cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))
    return p


def fingerprint(pem_path: Path | None = None) -> str | None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    p = pem_path or paths()["ca"]
    if not p.exists():
        return None
    cert = x509.load_pem_x509_certificate(p.read_bytes())
    return cert.fingerprint(hashes.SHA256()).hex(":").upper()


def info() -> dict:
    p = paths()
    enabled = bool((get_settings().raw.get("server") or {}).get("tls"))
    names = None
    if p["cert"].exists():
        from cryptography import x509
        c = x509.load_pem_x509_certificate(p["cert"].read_bytes())
        san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        names = [str(x.value) for x in san]
        valid_to = c.not_valid_after_utc.isoformat(timespec="seconds")
    else:
        valid_to = None
    return {"aktiv": enabled, "zertifikat": p["cert"].exists(), "fingerprint": fingerprint(), "namen": names, "gueltig_bis": valid_to,
            "ca_datei": str(p["ca"])}


def main(argv: list[str] | None = None) -> None:
    cmd = (argv or sys.argv[1:] or ["zeigen"])[0]
    if cmd == "erstellen":
        p = ensure(argv[1:] if argv else sys.argv[2:])
        print(f"Zertifikat: {p['cert']}\nCA:         {p['ca']}")
    print(f"CA-Fingerabdruck (SHA-256): {fingerprint() or '– noch keins (python -m app.tls erstellen)'}")


if __name__ == "__main__":
    main()
