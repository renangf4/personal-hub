"""Lookups de DNS, Whois, IP, TLS, portas, ping e reputacao."""

from __future__ import annotations

import ipaddress
import platform
import socket
import ssl
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import quote, urlparse

import dns.resolver
import dns.reversename
import httpx
import whois

TIPOS_DNS = ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "CAA", "SRV")

PORTAS_COMUNS = (
    21, 22, 25, 53, 80, 110, 143, 443, 465, 587, 993, 995,
    3306, 3389, 5432, 6379, 8080, 8443, 27017,
)

PORTAS_NOMES = {
    21: "FTP",
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    443: "HTTPS",
    465: "SMTPS",
    587: "Submission",
    993: "IMAPS",
    995: "POP3S",
    3306: "MySQL",
    3389: "RDP",
    5432: "PostgreSQL",
    6379: "Redis",
    8080: "HTTP-alt",
    8443: "HTTPS-alt",
    27017: "MongoDB",
}

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

    def _um(ip: str) -> dict[str, Any]:
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
        return item

    lista_ips = ips[:8]
    by_ip: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(lista_ips))) as pool:
        futuros = {pool.submit(_um, ip): ip for ip in lista_ips}
        for fut in as_completed(futuros):
            by_ip[futuros[fut]] = fut.result()
    resultados = [by_ip[ip] for ip in lista_ips]

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

    def _probe(porta: int) -> dict[str, Any]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.8)
        estado = "fechada"
        try:
            if s.connect_ex((ip, porta)) == 0:
                estado = "aberta"
        except Exception:
            estado = "erro"
        finally:
            s.close()
        return {
            "porta": porta,
            "servico": PORTAS_NOMES.get(porta, ""),
            "estado": estado,
        }

    by_porta: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(32, max(4, len(lista)))) as pool:
        futuros = {pool.submit(_probe, p): p for p in lista}
        for fut in as_completed(futuros):
            by_porta[futuros[fut]] = fut.result()

    detalhes = [by_porta[p] for p in lista]
    abertas = [d["porta"] for d in detalhes if d["estado"] == "aberta"]
    fechadas = [d["porta"] for d in detalhes if d["estado"] != "aberta"]

    eh_cf = _ip_cloudflare(ip)
    avisos = []
    if eh_cf:
        avisos.append(
            "Este IP e faixa Cloudflare. O scan bate no proxy da Cloudflare, "
            "nao no VPS de origin — resultado quase nunca reflete SSH/MySQL/RDP reais do servidor."
        )
    if len(abertas) >= max(8, len(lista) // 2) and eh_cf:
        avisos.append(
            "Muitas portas apareceram abertas no edge da Cloudflare; "
            "isso costuma ser engodo do proxy, nao significa que todos esses servicos estao expostos no VPS."
        )

    return {
        "ok": True,
        "alvo": host,
        "ip": ip,
        "cloudflare": eh_cf,
        "detalhes": detalhes,
        "abertas": abertas,
        "fechadas": fechadas,
        "testadas": len(lista),
        "fechadas_qtd": len(fechadas),
        "avisos": avisos,
        "nota": "TCP connect em cada porta da lista abaixo. Aberta = handshake TCP aceito.",
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
    except subprocess.TimeoutExpired as e:
        out = ""
        if e.stdout:
            out += e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", errors="replace")
        if e.stderr:
            err = e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", errors="replace")
            out += ("\n" + err) if out else err
        out = out.strip()
        if out:
            return {
                "ok": True,
                "codigo": -1,
                "saida": out[:12000],
                "parcial": True,
                "aviso": f"Timeout apos {timeout}s — mostrando o que ja chegou (saltos sem resposta demoram).",
            }
        return {"ok": False, "msg": f"Timeout apos {timeout}s sem saida (muitos saltos filtrados/ICMP bloqueado)"}
    except FileNotFoundError:
        return {"ok": False, "msg": f"Comando nao encontrado: {cmd[0]}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def consultar_ping(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    sistema = platform.system()
    if sistema == "Windows":
        cmd = ["ping", "-n", "4", "-w", "2000", host]
    else:
        cmd = ["ping", "-c", "4", "-W", "2", host]
    r = _rodar_cmd(cmd, timeout=15)
    r["alvo"] = host
    r["comando"] = " ".join(cmd)
    return r


def consultar_traceroute(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    sistema = platform.system()
    # Timeouts curtos por salto: hops sem ICMP esticam o comando inteiro.
    if sistema == "Windows":
        # -d sem DNS, -h max hops, -w timeout ms por probe
        cmd = ["tracert", "-d", "-h", "12", "-w", "1000", host]
        timeout = 45
    elif sistema == "Darwin":
        cmd = ["traceroute", "-n", "-m", "12", "-w", "1", "-q", "1", host]
        timeout = 40
    else:
        cmd = ["traceroute", "-n", "-m", "12", "-w", "1", "-q", "1", host]
        timeout = 40
    r = _rodar_cmd(cmd, timeout=timeout)
    if not r.get("ok") and (r.get("msg") or "").startswith("Comando nao encontrado"):
        r2 = _rodar_cmd(["tracepath", "-n", host], timeout=40)
        r2["alvo"] = host
        r2["comando"] = "tracepath -n " + host
        if r2.get("ok") or r2.get("saida"):
            return r2
    r["alvo"] = host
    r["comando"] = " ".join(cmd)
    if r.get("ok") and not r.get("aviso"):
        r["aviso"] = (
            "Traceroute depende de ICMP; Cloudflare/firewalls filtrados mostram * * * "
            "e podem parecer 'travados' — isso e normal."
        )
    return r


def consultar_certificados(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    if _eh_ip(host):
        return {"ok": False, "alvo": host, "msg": "crt.sh funciona melhor com dominio"}

    link = f"https://crt.sh/?q={quote(host)}"
    # crt.sh e um servico publico sobrecarregado: timeouts sao comuns.
    ultimo_erro = "Timeout no crt.sh"
    data = None
    for tentativa in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
                r = client.get(
                    "https://crt.sh/",
                    params={"q": host, "output": "json"},
                    headers={
                        "User-Agent": "PersonalHub/1.0",
                        "Accept": "application/json",
                    },
                )
            if r.status_code in (429, 502, 503, 504):
                ultimo_erro = f"crt.sh sobrecarregado (HTTP {r.status_code})"
                continue
            if r.status_code != 200:
                return {
                    "ok": False,
                    "alvo": host,
                    "msg": f"HTTP {r.status_code}",
                    "link": link,
                }
            raw = (r.text or "").strip()
            if not raw:
                ultimo_erro = "crt.sh respondeu vazio"
                continue
            data = r.json()
            break
        except httpx.TimeoutException:
            ultimo_erro = "Timeout no crt.sh (servico publico costuma ficar lento/sobrecarregado)"
        except Exception as e:
            ultimo_erro = str(e)

    if data is None:
        return {
            "ok": False,
            "alvo": host,
            "msg": f"{ultimo_erro}. Tente de novo ou abra o link.",
            "link": link,
        }

    if not isinstance(data, list):
        return {
            "ok": False,
            "alvo": host,
            "msg": "Resposta inesperada do crt.sh",
            "link": link,
        }

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
        "total_bruto": len(data),
        "itens": itens,
        "link": link,
    }


def consultar_rbl(alvo: str) -> dict[str, Any]:
    host = _normalizar_alvo(alvo)
    ips = _resolver_ips(host, so_ipv4=True)
    if not ips:
        return {"ok": False, "alvo": host, "msg": "Nao resolveu IPv4"}

    def _check_lista(rev: str, zone: str, nome: str) -> dict[str, Any]:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 2.5
        resolver.timeout = 2.0
        q = f"{rev}.{zone}"
        try:
            answers = resolver.resolve(q, "A")
            return {"lista": nome, "listado": True, "codigos": [str(a) for a in answers]}
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return {"lista": nome, "listado": False}
        except Exception as e:
            return {"lista": nome, "listado": None, "erro": str(e)}

    resultados = []
    for ip in ips[:3]:
        partes = ip.split(".")
        if len(partes) != 4:
            continue
        rev = ".".join(reversed(partes))
        with ThreadPoolExecutor(max_workers=len(RBL_ZONES)) as pool:
            futuros = [
                pool.submit(_check_lista, rev, zone, nome)
                for zone, nome in RBL_ZONES
            ]
            listas = [f.result() for f in futuros]
        resultados.append({"ip": ip, "listas": listas})
    return {"ok": True, "alvo": host, "resultados": resultados}


def consultar_shodan(alvo: str, api_key: str) -> dict[str, Any]:
    key = (api_key or "").strip()
    if not key:
        host = _normalizar_alvo(alvo)
        ips = _resolver_ips(host, so_ipv4=True)
        ip = ips[0] if ips else None
        return {
            "ok": False,
            "alvo": host,
            "msg": "API key do Shodan nao configurada. Crie em https://account.shodan.io/",
            "link": f"https://www.shodan.io/host/{ip}" if ip else "https://www.shodan.io/",
            "dica": "Sem key use a aba OSINT (link do Shodan no navegador) ou cadastre a key gratis.",
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


# Faixas publicas Cloudflare (aprox. lista oficial)
_CF_REDES = [
    ipaddress.ip_network(n)
    for n in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
]

_SUBDOMINIOS_ORIGEM = (
    "direct", "origin", "orig", "origin-www", "www-origin", "mail", "email",
    "ftp", "sftp", "cpanel", "whm", "webmail", "smtp", "pop", "pop3", "imap",
    "ns1", "ns2", "admin", "panel", "dashboard", "portal", "api", "staging",
    "stage", "dev", "development", "test", "testing", "server", "vps", "host",
    "backend", "remote", "vpn", "owa", "autodiscover", "exchange", "git",
    "gitlab", "jenkins", "mysql", "db", "ssh", "old", "legacy", "beta", "demo",
    "app", "mobile", "m", "ipv4", "nocdn", "no-cdn", "real", "raw", "shop",
    "store", "static", "cdn",
)

_HDR_INTERESSANTES = (
    "server", "cf-ray", "cf-cache-status", "cf-connecting-ip", "x-forwarded-for",
    "x-real-ip", "x-originating-ip", "x-backend-server", "x-served-by",
    "via", "x-cache", "x-powered-by", "x-host", "x-server-ip", "location",
)


def _ip_cloudflare(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in rede for rede in _CF_REDES)


def _host_de_url(url: str) -> str | None:
    try:
        p = urlparse(url)
        host = p.hostname
        return host.lower() if host else None
    except Exception:
        return None


def _resolver_a(host: str) -> list[str]:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 2.5
    resolver.timeout = 2.0
    ips: list[str] = []
    for tipo in ("A", "AAAA"):
        try:
            answers = resolver.resolve(host, tipo)
            for r in answers:
                ip = str(r).rstrip(".")
                if ip not in ips:
                    ips.append(ip)
        except Exception:
            continue
    return ips


def _extrair_ips_spf(txt: str) -> tuple[list[str], list[str]]:
    """Retorna (ips diretos, hosts a resolver) a partir de um TXT SPF."""
    ips: list[str] = []
    hosts: list[str] = []
    for token in txt.split():
        low = token.lower()
        if low.startswith("ip4:") or low.startswith("ip6:"):
            valor = token.split(":", 1)[1]
            # pode ser CIDR — pega o host da rede
            try:
                if "/" in valor:
                    net = ipaddress.ip_network(valor, strict=False)
                    ips.append(str(net.network_address))
                else:
                    ipaddress.ip_address(valor)
                    ips.append(valor)
            except ValueError:
                continue
        elif low.startswith("a:") or low.startswith("mx:"):
            hosts.append(token.split(":", 1)[1].rstrip("."))
        elif low.startswith("include:") or low.startswith("redirect="):
            hosts.append(token.split(":", 1)[1].split("=", 1)[-1].rstrip("."))
        elif low == "a" or low == "mx":
            pass  # trata no caller com o dominio base
    return ips, hosts


def _add_candidato(
    candidatos: dict[str, dict[str, Any]],
    ip: str,
    fonte: str,
    host: str | None = None,
) -> None:
    if not ip or not _eh_ip(ip):
        return
    if ip not in candidatos:
        candidatos[ip] = {
            "ip": ip,
            "cloudflare": _ip_cloudflare(ip),
            "fontes": [],
            "hosts": [],
        }
    if fonte not in candidatos[ip]["fontes"]:
        candidatos[ip]["fontes"].append(fonte)
    if host and host not in candidatos[ip]["hosts"]:
        candidatos[ip]["hosts"].append(host)


def consultar_origem(alvo: str) -> dict[str, Any]:
    """Heuristicas para achar IP de origin quando o dominio usa Cloudflare."""
    host = _normalizar_alvo(alvo)
    if _eh_ip(host):
        return {
            "ok": False,
            "alvo": host,
            "msg": "Informe um dominio (nao IP). Esta analise procura vazamento de origin atras do proxy.",
        }

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 4.0
    candidatos: dict[str, dict[str, Any]] = {}
    avisos: list[str] = []
    dns_atual: list[dict[str, Any]] = []
    headers_resumo: dict[str, str] = {}
    redirects: list[str] = []
    subdominios: list[dict[str, Any]] = []
    spf_registros: list[str] = []
    mx_hosts: list[str] = []
    cf_detectado = False
    sinais_cf: list[str] = []

    # DNS publico do dominio
    ips_dns = _resolver_a(host)
    for ip in ips_dns:
        eh_cf = _ip_cloudflare(ip)
        dns_atual.append({"ip": ip, "cloudflare": eh_cf})
        _add_candidato(candidatos, ip, "dns-a", host)
        if eh_cf:
            cf_detectado = True
            if "DNS aponta para faixa Cloudflare" not in sinais_cf:
                sinais_cf.append("DNS aponta para faixa Cloudflare")

    # HTTP headers + redirects (sem seguir) e depois uma passagem com follow
    ua = {"User-Agent": "PersonalHub/1.0"}
    try:
        with httpx.Client(timeout=12.0, follow_redirects=False, verify=False) as client:
            for scheme in ("https", "http"):
                url = f"{scheme}://{host}/"
                try:
                    r = client.get(url, headers=ua)
                except Exception as e:
                    avisos.append(f"{scheme}: {e}")
                    continue
                for hk, hv in r.headers.items():
                    low = hk.lower()
                    if low in _HDR_INTERESSANTES:
                        headers_resumo[low] = hv
                srv = (r.headers.get("server") or "").lower()
                if "cloudflare" in srv or r.headers.get("cf-ray"):
                    cf_detectado = True
                    if "Headers Cloudflare (server/cf-ray)" not in sinais_cf:
                        sinais_cf.append("Headers Cloudflare (server/cf-ray)")
                loc = r.headers.get("location")
                cadeias = [url]
                visto = {url}
                atual = loc
                profundidade = 0
                while atual and profundidade < 8:
                    cadeias.append(atual)
                    redirects.append(atual)
                    hloc = _host_de_url(atual)
                    if hloc and hloc != host and not hloc.endswith("." + host):
                        for ip in _resolver_a(hloc):
                            _add_candidato(candidatos, ip, "redirect", hloc)
                    if atual in visto:
                        break
                    visto.add(atual)
                    if not atual.startswith("http"):
                        break
                    try:
                        r2 = client.get(atual, headers=ua)
                        atual = r2.headers.get("location")
                    except Exception:
                        break
                    profundidade += 1
                break
    except Exception as e:
        avisos.append(f"HTTP: {e}")

    if headers_resumo.get("x-forwarded-for"):
        avisos.append(
            "X-Forwarded-For na resposta costuma ser o IP do cliente/proxy interno — "
            "NÃO e o IP do VPS de origin. Cloudflare nao devolve o origin nesse header."
        )
        for parte in headers_resumo["x-forwarded-for"].split(","):
            ip_cand = parte.strip().split(":")[0]
            if _eh_ip(ip_cand):
                _add_candidato(candidatos, ip_cand, "header-x-forwarded-for")

    for chave in ("x-real-ip", "x-originating-ip", "x-server-ip", "cf-connecting-ip"):
        val = headers_resumo.get(chave)
        if not val:
            continue
        ip_cand = val.strip().split(",")[0].strip()
        if _eh_ip(ip_cand):
            _add_candidato(candidatos, ip_cand, f"header-{chave}")

    # SPF
    try:
        answers = resolver.resolve(host, "TXT")
        for rdata in answers:
            partes = [
                p.decode("utf-8", errors="replace") if isinstance(p, bytes) else str(p)
                for p in rdata.strings
            ]
            txt = "".join(partes)
            if not txt.lower().strip().startswith("v=spf1"):
                continue
            spf_registros.append(txt)
            ips_spf, hosts_spf = _extrair_ips_spf(txt)
            for ip in ips_spf:
                _add_candidato(candidatos, ip, "spf", host)
            if " a" in f" {txt.lower()} " or txt.lower().rstrip().endswith(" a") or " a " in f" {txt.lower()} ":
                hosts_spf.append(host)
            hosts_para_spf = hosts_spf[:12]
            with ThreadPoolExecutor(max_workers=min(12, max(1, len(hosts_para_spf)))) as pool:
                mapa = {pool.submit(_resolver_a, h): h for h in hosts_para_spf}
                for fut in as_completed(mapa):
                    h = mapa[fut]
                    for ip in fut.result():
                        _add_candidato(candidatos, ip, "spf-host", h)
    except Exception:
        pass

    # MX
    try:
        answers = resolver.resolve(host, "MX")
        for rdata in answers:
            mx = str(rdata.exchange).rstrip(".")
            if mx not in mx_hosts:
                mx_hosts.append(mx)
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(mx_hosts)))) as pool:
            mapa = {pool.submit(_resolver_a, mx): mx for mx in mx_hosts}
            for fut in as_completed(mapa):
                mx = mapa[fut]
                for ip in fut.result():
                    _add_candidato(candidatos, ip, "mx", mx)
    except Exception:
        pass

    # Subdominios comuns fora do proxy (em paralelo)
    nomes_sub = [f"{sub}.{host}" for sub in _SUBDOMINIOS_ORIGEM]
    with ThreadPoolExecutor(max_workers=24) as pool:
        mapa = {pool.submit(_resolver_a, nome): nome for nome in nomes_sub}
        achados: list[tuple[str, list[str]]] = []
        for fut in as_completed(mapa):
            nome = mapa[fut]
            ips = fut.result()
            if ips:
                achados.append((nome, ips))
        achados.sort(key=lambda x: x[0])
        for nome, ips in achados:
            item = {"host": nome, "ips": []}
            for ip in ips:
                eh_cf = _ip_cloudflare(ip)
                item["ips"].append({"ip": ip, "cloudflare": eh_cf})
                _add_candidato(candidatos, ip, "subdominio", nome)
            subdominios.append(item)

    lista = sorted(
        candidatos.values(),
        key=lambda c: (c["cloudflare"], c["ip"]),
    )
    possiveis = [c for c in lista if not c["cloudflare"]]
    so_cf = [c for c in lista if c["cloudflare"]]

    return {
        "ok": True,
        "alvo": host,
        "cloudflare_detectado": cf_detectado,
        "sinais_cloudflare": sinais_cf,
        "dns_atual": dns_atual,
        "headers": headers_resumo,
        "redirects": redirects,
        "spf": spf_registros,
        "mx": mx_hosts,
        "subdominios": subdominios,
        "candidatos": lista,
        "possiveis_origem": possiveis,
        "ips_cloudflare": so_cf,
        "avisos": avisos,
        "nota": (
            "Procura vazamentos comuns (SPF, MX, subdominios, redirects, headers). "
            "Se o origin estiver bem escondido, pode nao achar nada."
        ),
    }


def consultar_osint(alvo: str) -> dict[str, Any]:
    """Monta links externos uteis pra recon (sem scrape / sem exploit)."""
    host = _normalizar_alvo(alvo)
    eh_ip = _eh_ip(host)
    q = quote(host)
    ips = [] if eh_ip else _resolver_ips(host, so_ipv4=True)[:3]
    ip_principal = host if eh_ip else (ips[0] if ips else None)

    grupos: list[dict[str, Any]] = []

    if not eh_ip:
        grupos.append({
            "titulo": "Historico DNS / origin",
            "links": [
                {
                    "nome": "SecurityTrails — historico A",
                    "url": f"https://securitytrails.com/domain/{q}/history/a",
                    "pra_que": "IPs antigos do dominio (antes do Cloudflare)",
                },
                {
                    "nome": "SecurityTrails — dominio",
                    "url": f"https://securitytrails.com/domain/{q}/dns",
                    "pra_que": "DNS atual + subdominios indexados",
                },
                {
                    "nome": "ViewDNS — IP History",
                    "url": f"https://viewdns.info/iphistory/?domain={q}",
                    "pra_que": "Historico de IPs associados ao dominio",
                },
                {
                    "nome": "ViewDNS — DNS Record",
                    "url": f"https://viewdns.info/dnsrecord/?domain={q}",
                    "pra_que": "Registros DNS publicos",
                },
                {
                    "nome": "ViewDNS — Subdomains",
                    "url": f"https://viewdns.info/subdomains/?domain={q}",
                    "pra_que": "Subdominios conhecidos",
                },
                {
                    "nome": "DNSdumpster",
                    "url": "https://dnsdumpster.com/",
                    "pra_que": "Mapa DNS/subdominios (cole o dominio no site)",
                },
                {
                    "nome": "Completedns — historico",
                    "url": f"https://completedns.com/dns-history/?domain={q}",
                    "pra_que": "Mudancas historicas de DNS",
                },
            ],
        })
        grupos.append({
            "titulo": "Certificados / superficie",
            "links": [
                {
                    "nome": "crt.sh",
                    "url": f"https://crt.sh/?q={q}",
                    "pra_que": "Certificate Transparency — subdominios via TLS",
                },
                {
                    "nome": "urlscan.io",
                    "url": f"https://urlscan.io/search/#{q}",
                    "pra_que": "Scans publicos da URL / dominio",
                },
                {
                    "nome": "Wayback Machine",
                    "url": f"https://web.archive.org/web/*/{q}",
                    "pra_que": "Snapshots antigos do site",
                },
                {
                    "nome": "BuiltWith",
                    "url": f"https://builtwith.com/{q}",
                    "pra_que": "Tecnologias detectadas no site",
                },
            ],
        })

    host_links = []
    if not eh_ip:
        host_links.extend([
            {
                "nome": "Shodan — hostname",
                "url": f"https://www.shodan.io/search?query=hostname%3A{q}",
                "pra_que": "Hosts/banners ligados ao hostname",
            },
            {
                "nome": "Censys — busca",
                "url": f"https://search.censys.io/search?resource=hosts&sort=RELEVANCE&per_page=25&virtual_hosts=EXCLUDE&q={q}",
                "pra_que": "Hosts, certs e servicos indexados",
            },
            {
                "nome": "VirusTotal — dominio",
                "url": f"https://www.virustotal.com/gui/domain/{q}",
                "pra_que": "Reputacao e resolucoes do dominio",
            },
            {
                "nome": "AlienVault OTX",
                "url": f"https://otx.alienvault.com/indicator/domain/{q}",
                "pra_que": "Pulsos / IOCs relacionados",
            },
            {
                "nome": "BGP.he.net — DNS",
                "url": f"https://bgp.he.net/dns/{q}",
                "pra_que": "DNS e prefixes associados",
            },
        ])
    if ip_principal:
        qi = quote(ip_principal)
        host_links.extend([
            {
                "nome": f"Shodan — host {ip_principal}",
                "url": f"https://www.shodan.io/host/{qi}",
                "pra_que": "Portas, banners e vulns indexadas desse IP",
            },
            {
                "nome": f"Censys — host {ip_principal}",
                "url": f"https://search.censys.io/hosts/{qi}",
                "pra_que": "Servicos observados nesse IP",
            },
            {
                "nome": f"AbuseIPDB — {ip_principal}",
                "url": f"https://www.abuseipdb.com/check/{qi}",
                "pra_que": "Reports de abuso",
            },
            {
                "nome": f"VirusTotal — IP {ip_principal}",
                "url": f"https://www.virustotal.com/gui/ip-address/{qi}",
                "pra_que": "Reputacao do IP",
            },
            {
                "nome": f"BGP.he.net — IP {ip_principal}",
                "url": f"https://bgp.he.net/ip/{qi}",
                "pra_que": "ASN, whois de rede",
            },
        ])

    avisos: list[str] = []
    if not eh_ip and ip_principal and _ip_cloudflare(ip_principal):
        avisos.append(
            f"IP atual {ip_principal} e Cloudflare — priorize SecurityTrails / ViewDNS IP History "
            "pra achar origin antigo; Shodan desse IP e o edge da CF, nao o VPS."
        )

    if host_links:
        grupos.append({"titulo": "Hosts / reputacao", "links": host_links})

    if eh_ip:
        grupos.insert(0, {
            "titulo": "IP",
            "links": [
                {
                    "nome": "ViewDNS — Reverse IP",
                    "url": f"https://viewdns.info/reverseip/?host={q}&t=1",
                    "pra_que": "Outros dominios no mesmo IP",
                },
                {
                    "nome": "ViewDNS — Port scan",
                    "url": f"https://viewdns.info/portscan/?host={q}",
                    "pra_que": "Scan de portas via ViewDNS",
                },
            ],
        })

    return {
        "ok": True,
        "alvo": host,
        "ips_resolvidos": ips if not eh_ip else [host],
        "grupos": grupos,
        "avisos": avisos,
        "nota": (
            "Atalhos externos para recon. Nao executa exploit nem scrape — "
            "abra o link e consulte no site (alguns pedem conta)."
        ),
    }
