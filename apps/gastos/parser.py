"""
Parser do cupom fiscal (RF-024/025).

A entrada é o **texto cru do OCR** (ML Kit, on-device) e/ou a **URL do QR Code**
da NFC-e. A saída é um preview (`dict`) com os itens e os metadados da nota —
nada é persistido aqui; quem salva é o `GastoSerializer` com `compra_detalhada`.

O OCR de cupom é inerentemente ruidoso, então o parsing é **heurístico e
tolerante**: tenta achar linhas no formato comum da NFC-e brasileira
(`cod  descrição  qtd UN x valor_unit  valor_total`) e cai para formatos mais
simples (descrição + valor no fim da linha). Itens que não casam o padrão
limpo vêm com `identificado=False` para a pessoa revisar no app.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

# Código IBGE da UF (2 primeiros dígitos da chave de acesso) → sigla.
UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
    "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}

# Sufixos típicos de razão social, para identificar o estabelecimento.
_SUFIXOS_EMPRESA = re.compile(
    r"\b(LTDA|EIRELI|S/?A|ME|EPP|MERCANTIL|COMERCIO|COMÉRCIO|SUPERMERCAD|"
    r"MERCAD|ATACAD|FARMACIA|FARMÁCIA|DROGARIA|PADARIA|RESTAURANTE)\b",
    re.IGNORECASE,
)

# Valor monetário pt-BR: 1.234,56 | 1234,56 | 12,90 (vírgula decimal obrigatória).
_RE_MOEDA = r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}"

# Padrão "qtd [unidade] x valor_unitário" no meio da linha do item.
_RE_QTD_X_UNIT = re.compile(
    r"(?P<qtd>\d+(?:[.,]\d{1,3})?)\s*"
    r"(?P<un>UN|UNID|KG|G|L|ML|PC|PCT|CX|DZ|MT|M)?\s*"
    r"[xX*]\s*"
    r"(?P<unit>" + _RE_MOEDA + r")",
    re.IGNORECASE,
)

# Linha que carrega o total da nota.
_RE_TOTAL = re.compile(
    r"(VALOR\s*A\s*PAGAR|VALOR\s*TOTAL|VL\.?\s*TOTAL|TOTAL\s*R\$|^TOTAL)\b",
    re.IGNORECASE,
)
_RE_DESCONTO = re.compile(r"DESCONTO|DESC\.", re.IGNORECASE)
_RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_RE_ITENS_TOTAL = re.compile(
    r"(?:QTD\.?\s*TOTAL\s*DE\s*ITEN?S?|TOTAL\s*DE\s*ITEN?S?)\D*(\d+)", re.IGNORECASE
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


def _ultima_moeda(linha: str) -> Decimal | None:
    achados = re.findall(_RE_MOEDA, linha)
    return _para_decimal(achados[-1]) if achados else None


def _dados_do_qr(url_qr: str | None) -> dict:
    """Extrai chave/UF/url da URL do QR da NFC-e (RN-024)."""
    out: dict = {"url_nfce": None, "chave": None, "uf": None}
    if not url_qr:
        return out
    out["url_nfce"] = url_qr.strip()
    # A chave de acesso (44 dígitos) costuma vir no param `p` ou na própria URL.
    chave = None
    try:
        qs = parse_qs(urlparse(url_qr).query)
        if "p" in qs:
            chave = re.sub(r"\D", "", qs["p"][0].split("|")[0])
    except ValueError:
        pass
    if not chave or len(chave) < 44:
        m = re.search(r"\d{44}", re.sub(r"\s", "", url_qr))
        if m:
            chave = m.group(0)
    if chave and len(chave) >= 44:
        chave = chave[:44]
        out["chave"] = chave
        out["uf"] = UF_POR_CODIGO.get(chave[:2])
    return out


def _eh_linha_de_item(linha: str) -> bool:
    """Filtra linhas que claramente não são itens (cabeçalho/rodapé/totais)."""
    up = linha.upper()
    ruido = (
        "CNPJ", "CPF", "CUPOM", "SAT", "NFC-E", "NFCE", "CHAVE", "PROTOCOLO",
        "CONSULTE", "CONSUMIDOR", "TRIBUTOS", "TROCO", "DINHEIRO", "CARTAO",
        "CARTÃO", "FORMA", "PAGAMENTO", "TOTAL", "DESCONTO", "ACRESCIMO",
        "QTD. TOTAL", "EXTRATO", "EMISSAO", "EMISSÃO", "WWW", "HTTP",
    )
    if any(p in up for p in ruido):
        return False
    return bool(re.search(_RE_MOEDA, linha))


def _parsear_item(linha: str) -> dict | None:
    """Tenta extrair um item de uma linha. Devolve dict ou None."""
    if not _eh_linha_de_item(linha):
        return None

    item: dict = {
        "nome": "",
        "codigo": None,
        "quantidade": None,
        "unidade": None,
        "valor_unitario": None,
        "valor": None,
        "identificado": False,
    }

    # Tokens numéricos no começo (sequencial + código de barras): consome todos
    # e guarda o mais longo como `codigo` (em geral o EAN/barras).
    resto = linha.strip()
    m_cod = re.match(r"^\s*((?:\d{3,}\s+)+)", resto)
    if m_cod:
        numeros = m_cod.group(1).split()
        item["codigo"] = max(numeros, key=len)
        resto = resto[m_cod.end():]

    m = _RE_QTD_X_UNIT.search(resto)
    if m:
        # Formato rico: descrição vem antes do "qtd x unit"; total é a última moeda.
        item["nome"] = resto[: m.start()].strip(" .-")
        item["quantidade"] = _para_decimal(m.group("qtd").replace(".", ","))
        item["unidade"] = (m.group("un") or "").upper() or None
        item["valor_unitario"] = _para_decimal(m.group("unit"))
        total = _ultima_moeda(resto[m.end():]) or _ultima_moeda(resto)
        item["valor"] = total
        # Coerência: se temos qtd e unit, o total deve bater (tolerância 1 centavo).
        if item["quantidade"] and item["valor_unitario"]:
            esperado = (item["quantidade"] * item["valor_unitario"]).quantize(Decimal("0.01"))
            if item["valor"] is None:
                item["valor"] = esperado
            item["identificado"] = abs((item["valor"] or esperado) - esperado) <= Decimal("0.05")
        else:
            item["identificado"] = item["valor"] is not None
    else:
        # Formato simples: "<descrição> ... <valor>".
        valor = _ultima_moeda(resto)
        if valor is None:
            return None
        nome = re.sub(_RE_MOEDA, "", resto)
        nome = re.sub(r"\b(UN|UNID|KG|G|L|ML|PC|PCT|CX|DZ|MT|M)\b", "", nome, flags=re.IGNORECASE)
        item["nome"] = nome.strip(" .-xX*")
        item["valor"] = valor
        item["identificado"] = False  # sem qtd/unit, pedimos revisão

    if not item["nome"] or item["valor"] is None or item["valor"] <= 0:
        return None
    return item


def _achar_estabelecimento(linhas: list[str]) -> str | None:
    """Heurística: linha com sufixo de empresa; senão a 1ª linha "textual"."""
    for linha in linhas[:8]:
        if _SUFIXOS_EMPRESA.search(linha):
            return linha.strip()[:120]
    for linha in linhas[:5]:
        t = linha.strip()
        letras = sum(c.isalpha() for c in t)
        if len(t) >= 4 and letras >= len(t) * 0.6 and not re.search(_RE_MOEDA, t):
            return t[:120]
    return None


def _achar_total(linhas: list[str]) -> Decimal | None:
    for linha in linhas:
        if _RE_TOTAL.search(linha) and not _RE_DESCONTO.search(linha):
            valor = _ultima_moeda(linha)
            if valor is not None:
                return valor
    return None


def parsear_cupom(texto_ocr: str = "", url_qr: str | None = None) -> dict:
    """Parser principal. Devolve o preview (dict) consumido pelo app."""
    qr = _dados_do_qr(url_qr)
    origem = "qr" if url_qr else "ocr"

    linhas = [l for l in (texto_ocr or "").splitlines() if l.strip()]

    itens: list[dict] = []
    for linha in linhas:
        item = _parsear_item(linha)
        if item:
            itens.append(item)

    total_itens = sum((i["valor"] for i in itens), Decimal("0"))
    total = _achar_total(linhas)
    desconto = None
    for linha in linhas:
        if _RE_DESCONTO.search(linha):
            desconto = _ultima_moeda(linha)
            break

    if total is None:
        total = total_itens
    total_confere = bool(itens) and abs(total - total_itens) <= Decimal("0.10")

    cnpj_match = _RE_CNPJ.search(texto_ocr or "")
    estabelecimento = _achar_estabelecimento(linhas)
    quantidade_itens = None
    m_qtd = _RE_ITENS_TOTAL.search(texto_ocr or "")
    if m_qtd:
        quantidade_itens = int(m_qtd.group(1))

    def _num(d: Decimal | None):
        return float(d) if d is not None else None

    return {
        "origem": origem,
        "estabelecimento": estabelecimento,
        "data": None,
        "categoria_sugerida": None,
        "url_nfce": qr["url_nfce"],
        "uf": qr["uf"],
        "cnpj": cnpj_match.group(0) if cnpj_match else None,
        "chave": qr["chave"],
        "total": _num(total),
        "total_itens": quantidade_itens if quantidade_itens is not None else len(itens),
        "desconto": _num(desconto),
        "total_confere": total_confere,
        "itens": [
            {
                "nome": i["nome"],
                "codigo": i["codigo"],
                "quantidade": _num(i["quantidade"]),
                "unidade": i["unidade"],
                "valor_unitario": _num(i["valor_unitario"]),
                "valor": _num(i["valor"]),
                "identificado": i["identificado"],
            }
            for i in itens
        ],
    }
