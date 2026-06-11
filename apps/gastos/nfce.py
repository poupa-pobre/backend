"""
Busca dos itens da NFC-e direto no portal da SEFAZ (RF-024, RN-024).

Quando o app lê o **QR Code** da nota, a URL aponta para a página de consulta
da NFC-e no portal da Fazenda do estado emissor. Essa página traz os itens
**estruturados** (nome, código, quantidade, unidade, valor unitário e total) —
infinitamente mais confiável que reconhecer o cupom amassado por OCR.

Este módulo faz o GET nessa URL e raspa os itens do HTML. É **tolerante a
falhas por projeto**: qualquer problema (rede, timeout, captcha na consulta
completa, layout desconhecido) devolve ``None`` e o chamador cai no parser do
texto do OCR (``parser.parsear_cupom``). Sem dependências externas — usa só a
stdlib (``urllib`` + ``re``), pra manter o backend leve.

O HTML alvo é o template "Consulta NFC-e" adotado pela maioria das UFs, cujo
miolo é uma tabela ``#tabResult`` com uma ``<tr>`` por item::

    <tr id="Item + 1">
      <td>
        <span class="txtTit">DESCRICAO DO PRODUTO</span>
        <span class="RCod">(Código: 7891234567890)</span>
        <span class="Rqtd"><strong>Qtde.:</strong>2</span>
        <span class="RUN"><strong>UN: </strong>UN</span>
        <span class="RvlUnit"><strong>Vl. Unit.:</strong>&#160;3,20</span>
      </td>
      <td class="txtTit noWrap"><span class="valor">6,40</span></td>
    </tr>
"""

from __future__ import annotations

import logging
import re
import ssl
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# Domínios da SEFAZ que mudaram com o tempo: o QR impresso na nota fica com o
# domínio antigo (404), mas a consulta vive no novo. Normalizamos na leitura.
# RN: renomeou SET→SEFAZ em mai/2025; `nfce.set.rn.gov.br` saiu do ar.
_DOMINIOS_OBSOLETOS = {
    "nfce.set.rn.gov.br": "nfce.sefaz.rn.gov.br",
}


def corrigir_dominio(url: str) -> str:
    """Reescreve domínios obsoletos da SEFAZ no link do QR (RN: set→sefaz)."""
    if not url:
        return url
    try:
        partes = urlsplit(url.strip())
    except ValueError:
        return url
    novo = _DOMINIOS_OBSOLETOS.get(partes.netloc.lower())
    return urlunsplit(partes._replace(netloc=novo)) if novo else url

_UA = (
    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Mobile Safari/537.36"
)

# Valor monetário pt-BR: 1.234,56 | 1234,56 | 12,90.
_RE_MOEDA = r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}"

# Cada item: uma <tr> cujo id começa com "Item" (espaços/sinais variam por UF).
_RE_LINHA_ITEM = re.compile(
    r"<tr[^>]*\bid\s*=\s*[\"']?Item[^>]*>(?P<corpo>.*?)</tr>",
    re.IGNORECASE | re.DOTALL,
)

_RE_NOME = re.compile(
    r"<span[^>]*\bclass\s*=\s*[\"'][^\"']*txtTit[^\"']*[\"'][^>]*>(?P<v>.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_RE_CODIGO = re.compile(
    r"C[óo]digo\s*:?\s*(?:</?[^>]*>\s*)?(\d{3,})", re.IGNORECASE
)
_RE_QTD = re.compile(
    r"\bclass\s*=\s*[\"'][^\"']*Rqtd[^\"']*[\"'][^>]*>.*?(?P<v>" + _RE_MOEDA
    + r"|\d+(?:[.,]\d+)?)",
    re.IGNORECASE | re.DOTALL,
)
_RE_UN = re.compile(
    r"\bclass\s*=\s*[\"'][^\"']*RUN[^\"']*[\"'][^>]*>.*?UN\s*:?\s*</strong>\s*"
    r"(?P<v>[A-Za-zÀ-ÿ]{1,6})",
    re.IGNORECASE | re.DOTALL,
)
_RE_VL_UNIT = re.compile(
    r"\bclass\s*=\s*[\"'][^\"']*RvlUnit[^\"']*[\"'][^>]*>.*?(?P<v>" + _RE_MOEDA + r")",
    re.IGNORECASE | re.DOTALL,
)
_RE_VL_TOTAL = re.compile(
    r"\bclass\s*=\s*[\"'][^\"']*valor[^\"']*[\"'][^>]*>\s*(?P<v>" + _RE_MOEDA + r")",
    re.IGNORECASE | re.DOTALL,
)

# Metadados fora da tabela de itens.
_RE_ESTAB = re.compile(
    r"\bclass\s*=\s*[\"'][^\"']*txtTopo[^\"']*[\"'][^>]*>(?P<v>.*?)</",
    re.IGNORECASE | re.DOTALL,
)
_RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_RE_EMISSAO = re.compile(
    r"Emiss[ãa]o\s*:?\s*(?:</?[^>]*>\s*)?(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE
)
_RE_TOTAL = re.compile(
    r"(?:Valor\s*a\s*pagar|Valor\s*total)[^\d]*?(?P<v>" + _RE_MOEDA + r")",
    re.IGNORECASE | re.DOTALL,
)
_RE_DESCONTO = re.compile(
    r"Desconto[s]?[^\d]*?(?P<v>" + _RE_MOEDA + r")", re.IGNORECASE | re.DOTALL
)


def _para_decimal(texto: str | None) -> Decimal | None:
    """Converte "1.234,56" (pt-BR) em Decimal. None se não der."""
    if not texto:
        return None
    limpo = texto.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return None


def _limpar_tags(html: str) -> str:
    """Remove tags e normaliza espaços/entidades de um trecho de HTML."""
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = (
        texto.replace("&nbsp;", " ")
        .replace("&#160;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return re.sub(r"\s+", " ", texto).strip()


def _baixar(url: str, timeout: int) -> str | None:
    """GET na URL do QR; devolve o HTML decodificado ou None em qualquer falha."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    # Alguns portais estaduais têm cadeia de certificados problemática; como só
    # lemos uma página pública de consulta (sem credenciais), tolerar SSL aqui é
    # aceitável e evita perder a leitura — o fallback do OCR continua de pé.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            bruto = resp.read()
            charset = resp.headers.get_content_charset()
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
        logger.info("NFC-e: falha ao baixar %s (%s)", url, e)
        return None
    for enc in (charset, "utf-8", "latin-1"):
        if not enc:
            continue
        try:
            return bruto.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return bruto.decode("utf-8", errors="replace")


def _parsear_item(corpo: str) -> dict | None:
    """Extrai um item de uma <tr> da tabela de resultados. None se não der."""
    m_nome = _RE_NOME.search(corpo)
    nome = _limpar_tags(m_nome.group("v")) if m_nome else ""
    if not nome:
        return None

    m_total = _RE_VL_TOTAL.search(corpo)
    valor = _para_decimal(m_total.group("v")) if m_total else None
    if valor is None or valor <= 0:
        return None

    m_cod = _RE_CODIGO.search(corpo)
    m_qtd = _RE_QTD.search(corpo)
    m_un = _RE_UN.search(corpo)
    m_unit = _RE_VL_UNIT.search(corpo)

    return {
        "nome": nome,
        "codigo": m_cod.group(1) if m_cod else None,
        "quantidade": _para_decimal((m_qtd.group("v") if m_qtd else "").replace(".", ",")),
        "unidade": (m_un.group("v").upper() if m_un else None),
        "valor_unitario": _para_decimal(m_unit.group("v")) if m_unit else None,
        "valor": valor,
        # Veio estruturado da SEFAZ: confiável, não precisa de revisão manual.
        "identificado": True,
    }


def parsear_html(html: str) -> dict | None:
    """Raspa itens + metadados do HTML da consulta NFC-e. None se não achar itens."""
    # Decodifica entidades (&oacute;, &#160;, &atilde;…) uma vez; as tags ficam,
    # então os regex por classe continuam casando.
    html = unescape(html)
    itens: list[dict] = []
    for m in _RE_LINHA_ITEM.finditer(html):
        item = _parsear_item(m.group("corpo"))
        if item:
            itens.append(item)
    if not itens:
        return None

    m_estab = _RE_ESTAB.search(html)
    m_cnpj = _RE_CNPJ.search(html)
    m_emissao = _RE_EMISSAO.search(html)
    m_total = _RE_TOTAL.search(html)
    m_desc = _RE_DESCONTO.search(html)

    return {
        "estabelecimento": (_limpar_tags(m_estab.group("v"))[:120] if m_estab else None) or None,
        "cnpj": m_cnpj.group(0) if m_cnpj else None,
        "data": (f"{m_emissao.group(3)}-{m_emissao.group(2)}-{m_emissao.group(1)}"
                 if m_emissao else None),
        "total": _para_decimal(m_total.group("v")) if m_total else None,
        "desconto": _para_decimal(m_desc.group("v")) if m_desc else None,
        "itens": itens,
    }


def buscar_nfce(url_qr: str, timeout: int = 8) -> dict | None:
    """Busca e parseia a NFC-e da URL do QR. None em qualquer falha (→ fallback OCR)."""
    if not url_qr:
        return None
    html = _baixar(corrigir_dominio(url_qr), timeout)
    if not html:
        return None
    try:
        return parsear_html(html)
    except Exception:  # nunca deixar a raspagem derrubar o request — cai no OCR
        logger.exception("NFC-e: erro inesperado ao parsear o HTML de %s", url_qr)
        return None
