"""Lookups de DNS, Whois, IP, TLS, portas, ping e reputacao."""

from __future__ import annotations

import ipaddress
import platform
import socket
import ssl
import subprocess
from typing import Any
from urllib.parse import quote

import dns.resolver
import dns.reversename
import httpx
import whois

TIPOS_DNS = ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "CAA", "SRV")

PORTAS_COMUNS = (
    21, 22, 25, 53, 80, 110, 143, 443, 465, 587, 993, 995,
    3306, 3389, 5432, 6379, 8080, 8443, 27017,
)

RBL_ZONES = (
    ("zen.spamhaus.org", "Spamhaus ZEN"),
    ("bl.spamcop.net", "SpamCop"),
    ("b.barracudacentral.org", "Barracuda"),
    ("dnsbl.sorbs.net", "SORBS"),
)


def _normalizar_alvo(alvo: str) -> str:
    s = (alvo or "").strip()
    if not s:
        raise ValueError("Informe um dominio ou IP")
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if s.startswith("[") and "]" in s:
        s = s[1 : s.index("]")]
    elif ":" in s and s.count(":") == 1 and not s.replace(":", "").replace(".", "").isdigit():
        host, porta = s.rsplit(":", 1)
        if porta.isdigit():
            s = host
    return s.strip(".").lower() if not _eh_ip(s) else s


def _eh_ip(valor: str) -> bool:
    try:
        ipaddress.ip_address(valor)
        return True
    except ValueError:
        return False


def _resolver_ips(host: str, so_ipv4: bool = False) -> list[str]:
    if _eh_ip(host):
        return [host]
    family = socket.AF_INET if so_ipv4 else 0
    ips: list[str] = []
    try:
        infos = socket.getaddrinfo(host, None, family)
        for info in infos:
            ip = info[4][0]
            if so_ipv4 and ":" in ip:
                continue
            if ip not in ips:
                ips.append(ip)
    except socket.gaierror:
        pass
    return ips


def _parse_email_txt(txts: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"spf": [], "dmarc": [], "dkim_hints": []}
    for t in txts:
        low = t.lower().strip()
        if low.startswith("v=spf1"):
            out["spf"].append(t)
        elif "v=dmarc1" in low:
            out["dmarc"].append(t)
        elif "v=dkim1" in low or "dkim" in low:
            out["dkim_hints"].append(t)
    return out


def consultar_dns(alvo: str, tipos: list[str] | None = None) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5.0
    registros: dict[str, list[str]] = {}
    erros: dict[str, str] = {}
    email: dict[str, list[str]] = {}

    if _eh_ip(host):
        # PTR reverso
        try:
            rev = dns.reversename.from_address(host)
            answers = resolver.resolve(rev, "PTR")
            registros["PTR"] = [str(r).rstrip(".") for r in answers]
        except Exception as e:
            erros["PTR"] = str(e)
        return {"ok": True, "alvo": host, "registros": registros, "erros": erros, "email": email}

    escolhidos = [t.upper() for t in (tipos or list(TIPOS_DNS)) if t.upper() in TIPOS_DNS]
    if not escolhidos:
        escolhidos = list(TIPOS_DNS)

    for tipo in escolhidos:
        try:
            qname = host
            if tipo == "SRV":
                # tenta alguns servicos comuns
                srv_nomes = [
                    f"_sip._tcp.{host}",
                    f"_xmpp-server._tcp.{host}",
                    f"_autodiscover._tcp.{host}",
                ]
                linhas: list[str] = []
                for nome in srv_nomes:
                    try:
                        answers = resolver.resolve(nome, "SRV")
                        for rdata in answers:
                            linhas.append(
                                f"{nome} {rdata.priority} {rdata.weight} {rdata.port} {str(rdata.target).rstrip('.')}"
                            )
                    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
                        continue
                registros["SRV"] = linhas
                continue

            answers = resolver.resolve(qname, tipo)
            linhas = []
            for rdata in answers:
                if tipo == "MX":
                    linhas.append(f"{rdata.preference} {str(rdata.exchange).rstrip('.')}")
                elif tipo == "TXT":
                    partes = [
                        p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p)
                        for p in rdata.strings
                    ]
                    linhas.append("".join(partes))
                elif tipo == "CAA":
                    linhas.append(f"{rdata.flags} {rdata.tag} {rdata.value}")
                elif tipo == "SOA":
                    linhas.append(str(rdata).rstrip("."))
                else:
                    linhas.append(str(rdata).rstrip("."))
            registros[tipo] = linhas
        except dns.resolver.NXDOMAIN:
            erros[tipo] = "Dominio nao existe (NXDOMAIN)"
            break
        except dns.resolver.NoAnswer:
            registros[tipo] = []
        except dns.resolver.NoNameservers:
            erros[tipo] = "Sem nameservers"
        except Exception as e:
            erros[tipo] = str(e)

    # DMARC em _dmarc.host
    try:
        answers = resolver.resolve(f"_dmarc.{host}", "TXT")
        dmarc = []
        for rdata in answers:
            partes = [
                p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p)
                for p in rdata.strings
            ]
            dmarc.append("".join(partes))
        if dmarc:
            registros["DMARC"] = dmarc
    except Exception:
        pass

    txts = list(registros.get("TXT") or []) + list(registros.get("DMARC") or [])
    email = _parse_email_txt(txts)

    return {"ok": True, "alvo": host, "registros": registros, "erros": erros, "email": email}


def consultar_whois(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    try:
        data = whois.whois(host)
    except Exception as e:
        return {"ok": False, "alvo": host, "msg": str(e)}

    if data is None:
        return {"ok": False, "alvo": host, "msg": "Sem dados Whois"}

    def _fmt(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, list):
            return [_fmt(x) for x in v]
        if hasattr(v, "isoformat"):
            try:
                return v.isoformat()
            except Exception:
                return str(v)
        return str(v) if not isinstance(v, (str, int, float, bool)) else v

    campos = {
        "domain_name": _fmt(getattr(data, "domain_name", None)),
        "registrar": _fmt(getattr(data, "registrar", None)),
        "creation_date": _fmt(getattr(data, "creation_date", None)),
        "expiration_date": _fmt(getattr(data, "expiration_date", None)),
        "updated_date": _fmt(getattr(data, "updated_date", None)),
        "name_servers": _fmt(getattr(data, "name_servers", None)),
        "status": _fmt(getattr(data, "status", None)),
        "emails": _fmt(getattr(data, "emails", None)),
        "org": _fmt(getattr(data, "org", None)),
        "country": _fmt(getattr(data, "country", None)),
        "city": _fmt(getattr(data, "city", None)),
        "address": _fmt(getattr(data, "address", None)),
        "whois_server": _fmt(getattr(data, "whois_server", None)),
    }
    campos = {k: v for k, v in campos.items() if v not in (None, "", [], {})}
    texto = getattr(data, "text", None)
    return {
        "ok": True,
        "alvo": host,
        "campos": campos,
        "texto": (texto[:8000] if isinstance(texto, str) else None),
    }


def consultar_ip(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    ips = _resolver_ips(host)
    if not ips:
        return {"ok": False, "alvo": host, "msg": "Nenhum IP encontrado"}

    resultados = []
    for ip in ips[:8]:
        item: dict[str, Any] = {"ip": ip}
        try:
            item["reverso"] = socket.gethostbyaddr(ip)[0]
        except Exception:
            item["reverso"] = None
        try:
            with httpx.Client(timeout=8.0) as client:
                r = client.get(
                    f"http://ip-api.com/json/{ip}",
                    params={
                        "fields": "status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,query,reverse,mobile,proxy,hosting",
                    },
                )
                data = r.json()
            if data.get("status") == "success":
                item["geo"] = {
                    "pais": data.get("country"),
                    "regiao": data.get("regionName"),
                    "cidade": data.get("city"),
                    "cep": data.get("zip"),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "fuso": data.get("timezone"),
                    "isp": data.get("isp"),
                    "org": data.get("org"),
                    "as": data.get("as"),
                    "proxy": data.get("proxy"),
                    "hosting": data.get("hosting"),
                    "mobile": data.get("mobile"),
                }
            else:
                item["geo_erro"] = data.get("message") or "Falha na consulta"
        except Exception as e:
            item["geo_erro"] = str(e)
        resultados.append(item)

    return {"ok": True, "alvo": host, "resultados": resultados}


def meu_ip_publico() -> dict[str, Any]:
    try:
        with httpx.Client(timeout=6.0) as client:
            r = client.get("https://api.ipify.org", params={"format": "json"})
            r.raise_for_status()
            data = r.json()
        ip = data.get("ip")
        if not ip:
            return {"ok": False, "msg": "Resposta sem IP"}
        return {"ok": True, "ip": ip}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def consultar_http_tls(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    resultado: dict[str, Any] = {"ok": True, "alvo": host, "http": None, "tls": None}

    # HTTP(S) headers
    urls = [f"https://{host}/", f"http://{host}/"]
    if _eh_ip(host):
        urls = [f"http://{host}/", f"https://{host}/"]

    with httpx.Client(timeout=12.0, follow_redirects=True, verify=False) as client:
        for url in urls:
            try:
                r = client.get(url, headers={"User-Agent": "PersonalHub/1.0"})
                resultado["http"] = {
                    "url_final": str(r.url),
                    "status": r.status_code,
                    "http_version": r.http_version,
                    "headers": {k: v for k, v in r.headers.items()},
                    "redirects": [str(x.url) for x in r.history],
                }
                break
            except Exception as e:
                resultado["http"] = {"erro": str(e), "tentativa": url}

    # Certificado TLS
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=None if _eh_ip(host) else host) as ssock:
                cert = ssock.getpeercert()
                cipher = ssock.cipher()
                versao = ssock.version()
        sans = []
        for typ, val in cert.get("subjectAltName") or []:
            sans.append(f"{typ}:{val}")
        subject = {k: v for tup in cert.get("subject", ()) for k, v in tup}
        issuer = {k: v for tup in cert.get("issuer", ()) for k, v in tup}
        resultado["tls"] = {
            "versao": versao,
            "cipher": cipher[0] if cipher else None,
            "subject": subject,
            "issuer": issuer,
            "not_before": cert.get("notBefore"),
            "not_after": cert.get("notAfter"),
            "san": sans,
            "serial": cert.get("serialNumber"),
        }
    except Exception as e:
        resultado["tls"] = {"erro": str(e)}

    return resultado


def consultar_portas(alvo: str, portas: list[int] | None = None) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    ips = _resolver_ips(host, so_ipv4=True)
    if not ips:
        return {"ok": False, "alvo": host, "msg": "Nao resolveu IPv4"}
    ip = ips[0]
    lista = portas or list(PORTAS_COMUNS)
    abertas = []
    fechadas = []
    for porta in lista:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.6)
        try:
            if s.connect_ex((ip, porta)) == 0:
                abertas.append(porta)
            else:
                fechadas.append(porta)
        except Exception:
            fechadas.append(porta)
        finally:
            s.close()
    return {
        "ok": True,
        "alvo": host,
        "ip": ip,
        "abertas": abertas,
        "testadas": len(lista),
        "fechadas_qtd": len(fechadas),
    }


def _rodar_cmd(cmd: list[str], timeout: int = 45) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        return {"ok": proc.returncode == 0 or bool(out.strip()), "codigo": proc.returncode, "saida": out.strip()[:12000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": "Timeout"}
    except FileNotFoundError:
        return {"ok": False, "msg": f"Comando nao encontrado: {cmd[0]}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def consultar_ping(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    sistema = platform.system()
    if sistema == "Windows":
        cmd = ["ping", "-n", "4", host]
    else:
        cmd = ["ping", "-c", "4", host]
    r = _rodar_cmd(cmd, timeout=20)
    r["alvo"] = host
    r["comando"] = " ".join(cmd)
    return r


def consultar_traceroute(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    sistema = platform.system()
    if sistema == "Windows":
        cmd = ["tracert", "-d", "-h", "15", host]
    elif sistema == "Darwin":
        cmd = ["traceroute", "-n", "-m", "15", host]
    else:
        cmd = ["traceroute", "-n", "-m", "15", host]
    r = _rodar_cmd(cmd, timeout=60)
    if not r.get("ok") and r.get("msg", "").startswith("Comando nao encontrado"):
        r2 = _rodar_cmd(["tracepath", "-n", host], timeout=60)
        r2["alvo"] = host
        r2["comando"] = "tracepath -n " + host
        return r2
    r["alvo"] = host
    r["comando"] = " ".join(cmd)
    return r


def consultar_certificados(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    if _eh_ip(host):
        return {"ok": False, "alvo": host, "msg": "crt.sh funciona melhor com dominio"}
    try:
        with httpx.Client(timeout=25.0) as client:
            r = client.get(
                "https://crt.sh/",
                params={"q": host, "output": "json"},
                headers={"User-Agent": "PersonalHub/1.0"},
            )
            if r.status_code != 200:
                return {"ok": False, "alvo": host, "msg": f"HTTP {r.status_code}"}
            data = r.json()
    except Exception as e:
        return {"ok": False, "alvo": host, "msg": str(e)}

    vistos: set[str] = set()
    itens = []
    for row in data[:80]:
        nome = row.get("name_value") or ""
        key = f"{nome}|{row.get('not_before')}|{row.get('issuer_name')}"
        if key in vistos:
            continue
        vistos.add(key)
        itens.append({
            "id": row.get("id"),
            "nomes": nome.replace("\n", ", "),
            "issuer": row.get("issuer_name"),
            "not_before": row.get("not_before"),
            "not_after": row.get("not_after"),
            "serial": row.get("serial_number"),
        })
    return {
        "ok": True,
        "alvo": host,
        "total_bruto": len(data) if isinstance(data, list) else 0,
        "itens": itens,
        "link": f"https://crt.sh/?q={quote(host)}",
    }


def consultar_rbl(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    ips = _resolver_ips(host, so_ipv4=True)
    if not ips:
        return {"ok": False, "alvo": host, "msg": "Nao resolveu IPv4"}
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4.0
    resultados = []
    for ip in ips[:3]:
        partes = ip.split(".")
        if len(partes) != 4:
            continue
        rev = ".".join(reversed(partes))
        listas = []
        for zone, nome in RBL_ZONES:
            q = f"{rev}.{zone}"
            try:
                answers = resolver.resolve(q, "A")
                codigos = [str(a) for a in answers]
                listas.append({"lista": nome, "listado": True, "codigos": codigos})
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
                listas.append({"lista": nome, "listado": False})
            except Exception as e:
                listas.append({"lista": nome, "listado": None, "erro": str(e)})
        resultados.append({"ip": ip, "listas": listas})
    return {"ok": True, "alvo": host, "resultados": resultados}


def consultar_shodan(alvo: str, api_key: str) -> dict[str, Any]:
    key = (api_key or "").strip()
    if not key:
        return {
            "ok": False,
            "msg": "API key do Shodan nao configurada. Crie em https://account.shodan.io/",
        }

    host = _normalizar_alvo(alvo)
    ips = _resolver_ips(host, so_ipv4=True)
    if not ips:
        return {"ok": False, "alvo": host, "msg": "Nenhum IPv4 para consultar no Shodan"}

    resultados = []
    with httpx.Client(timeout=20.0) as client:
        for ip in ips[:3]:
            try:
                r = client.get(f"https://api.shodan.io/shodan/host/{ip}", params={"key": key})
                if r.status_code == 404:
                    resultados.append({"ip": ip, "ok": False, "msg": "Sem dados no Shodan para este IP"})
                    continue
                if r.status_code == 401:
                    return {"ok": False, "alvo": host, "msg": "API key do Shodan invalida"}
                if r.status_code != 200:
                    resultados.append({"ip": ip, "ok": False, "msg": f"HTTP {r.status_code}: {r.text[:200]}"})
                    continue
                data = r.json()
                services = []
                for item in (data.get("data") or [])[:20]:
                    services.append({
                        "porta": item.get("port"),
                        "proto": item.get("transport"),
                        "produto": item.get("product") or (item.get("_shodan") or {}).get("module"),
                        "versao": item.get("version"),
                        "banner": (item.get("data") or "")[:400],
                    })
                resultados.append({
                    "ip": ip,
                    "ok": True,
                    "org": data.get("org"),
                    "isp": data.get("isp"),
                    "asn": data.get("asn"),
                    "os": data.get("os"),
                    "pais": data.get("country_name") or data.get("country_code"),
                    "cidade": data.get("city"),
                    "hostnames": data.get("hostnames") or [],
                    "portas": data.get("ports") or [],
                    "tags": data.get("tags") or [],
                    "vulns": list(data.get("vulns") or [])[:30],
                    "ultimo_update": data.get("last_update"),
                    "servicos": services,
                    "link": f"https://www.shodan.io/host/{ip}",
                })
            except Exception as e:
                resultados.append({"ip": ip, "ok": False, "msg": str(e)})

    return {"ok": True, "alvo": host, "resultados": resultados}


def consultar_abuseipdb(alvo: str, api_key: str) -> dict[str, Any]:
    key = (api_key or "").strip()
    if not key:
        return {
            "ok": False,
            "msg": "API key AbuseIPDB nao configurada. https://www.abuseipdb.com/account/api",
        }
    host = _normalizar_alvo(alvo)
    ips = _resolver_ips(host, so_ipv4=True)
    if not ips:
        return {"ok": False, "alvo": host, "msg": "Nenhum IPv4"}
    resultados = []
    with httpx.Client(timeout=15.0) as client:
        for ip in ips[:3]:
            try:
                r = client.get(
                    "https://api.abuseipdb.com/api/v2/check",
                    params={"ipAddress": ip, "maxAgeInDays": 90, "verbose": True},
                    headers={"Key": key, "Accept": "application/json"},
                )
                if r.status_code == 401:
                    return {"ok": False, "msg": "API key AbuseIPDB invalida"}
                if r.status_code != 200:
                    resultados.append({"ip": ip, "ok": False, "msg": f"HTTP {r.status_code}"})
                    continue
                d = (r.json() or {}).get("data") or {}
                resultados.append({
                    "ip": ip,
                    "ok": True,
                    "score": d.get("abuseConfidenceScore"),
                    "total_reports": d.get("totalReports"),
                    "pais": d.get("countryCode"),
                    "isp": d.get("isp"),
                    "uso": d.get("usageType"),
                    "dominio": d.get("domain"),
                    "whitelisted": d.get("isWhitelisted"),
                    "ultimo": d.get("lastReportedAt"),
                    "link": f"https://www.abuseipdb.com/check/{ip}",
                })
            except Exception as e:
                resultados.append({"ip": ip, "ok": False, "msg": str(e)})
    return {"ok": True, "alvo": host, "resultados": resultados}


def consultar_virustotal(alvo: str, api_key: str) -> dict[str, Any]:
    key = (api_key or "").strip()
    if not key:
        return {
            "ok": False,
            "msg": "API key VirusTotal nao configurada. https://www.virustotal.com/gui/my-apikey",
        }
    host = _normalizar_alvo(alvo)
    headers = {"x-apikey": key, "Accept": "application/json"}
    with httpx.Client(timeout=20.0) as client:
        try:
            if _eh_ip(host):
                r = client.get(f"https://www.virustotal.com/api/v3/ip_addresses/{host}", headers=headers)
            else:
                r = client.get(f"https://www.virustotal.com/api/v3/domains/{host}", headers=headers)
            if r.status_code == 401:
                return {"ok": False, "msg": "API key VirusTotal invalida"}
            if r.status_code == 404:
                return {"ok": False, "alvo": host, "msg": "Sem dados no VirusTotal"}
            if r.status_code != 200:
                return {"ok": False, "alvo": host, "msg": f"HTTP {r.status_code}: {r.text[:200]}"}
            attrs = ((r.json() or {}).get("data") or {}).get("attributes") or {}
            stats = attrs.get("last_analysis_stats") or {}
            return {
                "ok": True,
                "alvo": host,
                "stats": stats,
                "reputation": attrs.get("reputation"),
                "as_owner": attrs.get("as_owner"),
                "country": attrs.get("country"),
                "categories": attrs.get("categories"),
                "last_analysis_date": attrs.get("last_analysis_date"),
                "link": (
                    f"https://www.virustotal.com/gui/ip-address/{host}"
                    if _eh_ip(host)
                    else f"https://www.virustotal.com/gui/domain/{host}"
                ),
            }
        except Exception as e:
            return {"ok": False, "alvo": host, "msg": str(e)}
