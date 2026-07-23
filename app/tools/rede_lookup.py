"""Lookups de DNS, Whois e informacoes de IP."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import dns.resolver
import httpx
import whois

TIPOS_DNS = ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA")


def _normalizar_alvo(alvo: str) -> str:
    s = (alvo or "").strip()
    if not s:
        raise ValueError("Informe um dominio ou IP")
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if s.startswith("[" ) and "]" in s:
        s = s[1 : s.index("]")]
    elif ":" in s and s.count(":") == 1 and not s.replace(":", "").replace(".", "").isdigit():
        # host:porta
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


def consultar_dns(alvo: str, tipos: list[str] | None = None) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    if _eh_ip(host):
        raise ValueError("DNS lookup precisa de um dominio (nao IP)")

    escolhidos = [t.upper() for t in (tipos or list(TIPOS_DNS)) if t.upper() in TIPOS_DNS]
    if not escolhidos:
        escolhidos = list(TIPOS_DNS)

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5.0
    registros: dict[str, list[str]] = {}
    erros: dict[str, str] = {}

    for tipo in escolhidos:
        try:
            answers = resolver.resolve(host, tipo)
            linhas: list[str] = []
            for rdata in answers:
                if tipo == "MX":
                    linhas.append(f"{rdata.preference} {rdata.exchange}".rstrip("."))
                elif tipo == "TXT":
                    partes = [p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p) for p in rdata.strings]
                    linhas.append("".join(partes))
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

    return {"ok": True, "alvo": host, "registros": registros, "erros": erros}


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
    # remove vazios
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
    ips: list[str] = []

    if _eh_ip(host):
        ips = [host]
    else:
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                ip = info[4][0]
                if ip not in ips:
                    ips.append(ip)
        except socket.gaierror as e:
            return {"ok": False, "alvo": host, "msg": f"Nao resolveu: {e}"}

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
                r = client.get(f"http://ip-api.com/json/{ip}", params={
                    "fields": "status,message,country,regionName,city,zip,lat,lon,timezone,isp,org,as,query,reverse,mobile,proxy,hosting",
                })
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
    """IP publico visto por servicos externos (Whois/geo)."""
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


def consultar_shodan(alvo: str, api_key: str) -> dict[str, Any]:
    """Consulta host no Shodan (Google de IPs). Requer API key."""
    key = (api_key or "").strip()
    if not key:
        return {
            "ok": False,
            "msg": "API key do Shodan nao configurada. Crie em https://account.shodan.io/",
        }

    host = _normalizar_alvo(alvo)
    ips: list[str] = []
    if _eh_ip(host):
        ips = [host]
    else:
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET)
            for info in infos:
                ip = info[4][0]
                if ip not in ips:
                    ips.append(ip)
        except socket.gaierror as e:
            return {"ok": False, "alvo": host, "msg": f"Nao resolveu: {e}"}

    if not ips:
        return {"ok": False, "alvo": host, "msg": "Nenhum IPv4 para consultar no Shodan"}

    resultados = []
    with httpx.Client(timeout=20.0) as client:
        for ip in ips[:3]:
            try:
                r = client.get(
                    f"https://api.shodan.io/shodan/host/{ip}",
                    params={"key": key},
                )
                if r.status_code == 404:
                    resultados.append({
                        "ip": ip,
                        "ok": False,
                        "msg": "Sem dados no Shodan para este IP",
                    })
                    continue
                if r.status_code == 401:
                    return {"ok": False, "alvo": host, "msg": "API key do Shodan invalida"}
                if r.status_code != 200:
                    resultados.append({
                        "ip": ip,
                        "ok": False,
                        "msg": f"HTTP {r.status_code}: {r.text[:200]}",
                    })
                    continue
                data = r.json()
                ports = data.get("ports") or []
                hostnames = data.get("hostnames") or []
                vulns = list(data.get("vulns") or [])
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
                    "pais": (data.get("country_name") or data.get("country_code")),
                    "cidade": data.get("city"),
                    "hostnames": hostnames,
                    "portas": ports,
                    "tags": data.get("tags") or [],
                    "vulns": vulns[:30],
                    "ultimo_update": data.get("last_update"),
                    "servicos": services,
                    "link": f"https://www.shodan.io/host/{ip}",
                })
            except Exception as e:
                resultados.append({"ip": ip, "ok": False, "msg": str(e)})

    return {"ok": True, "alvo": host, "resultados": resultados}
