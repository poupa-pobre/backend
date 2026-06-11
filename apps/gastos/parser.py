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

# Formato NFC-e/SAT **sem "x"**, ancorado no fim da linha:
# "<descrição> <qtd><un> <vl_unit> <vl_total>" (o vl_unit é opcional).
# Ex.: "BISC ANDRI 1UN  2,99  2,99" · "ARROZ 1,5KG  5,90  8,85" · "PAO 3 UN 1,00".
# Unidades multi-char antes das de 1 char pra a alternância casar a maior.
_RE_ITEM_FIM = re.compile(
    r"(?P<qtd>\d+(?:[.,]\d{1,3})?)\s*"
    r"(?P<un>UNID|UND|UN|KGS|KG|PCT|PC|ML|MT|GR|CX|DZ|L|G|M)\s+"
    r"(?P<v1>" + _RE_MOEDA + r")"
    r"(?:\s+(?P<v2>" + _RE_MOEDA + r"))?\s*$",
    re.IGNORECASE,
)

# Data de emissão (DD/MM/AA ou DD/MM/AAAA) — primeira ocorrência no cupom.
_RE_DATA_OCR = re.compile(r"\b(\d{2})/(\d{2})/(\d{2}|\d{4})\b")

# Linha **só de quantidade** (a 2ª linha física do item em muitos cupons):
# começa com "<qtd><un> x <vl_unit>". Ex.: "1,000UN x 6,49 F" · "0,678KG x 12,99".
# É mesclada no item da linha anterior (descrição+total).
_RE_LINHA_QTD = re.compile(
    r"^\s*(?P<qtd>\d+(?:[.,]\d{1,3})?)\s*"
    r"(?P<un>UNID|UND|UN|KGS|KG|PCT|PC|ML|MT|GR|CX|DZ|L|G|M)\s*"
    r"[xX*]\s*(?P<vunit>" + _RE_MOEDA + r")",
    re.IGNORECASE,
)

# Linha que carrega o total da nota. Inclui formas comuns de comprovante de
# maquininha/recibo ("VALOR R$", "VALOR PAGO", "VALOR COBRADO"), não só NFC-e.
_RE_TOTAL = re.compile(
    r"(VALOR\s*A\s*PAGAR|VALOR\s*TOTAL|VL\.?\s*TOTAL|TOTAL\s*R\$|^TOTAL|"
    r"VALOR\s*PAGO|VALOR\s*COBRADO|VALOR\s*DA\s*COMPRA|VALOR\s*R\$)",
    re.IGNORECASE,
)
_RE_DESCONTO = re.compile(r"DESCONTO|DESC\.", re.IGNORECASE)
_RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_RE_ITENS_TOTAL = re.compile(
    r"(?:QTD\.?\s*TOTAL\s*DE\s*ITEN?S?|TOTAL\s*DE\s*ITEN?S?)\D*(\d+)", re.IGNORECASE
)

# Forma de pagamento estampada no comprovante (maquininha imprime déb/créd).
_FORMAS_OCR = [
    ("pix", re.compile(r"\bPIX\b", re.IGNORECASE)),
    ("debito", re.compile(r"D[ÉE]BITO|CART[ÃA]O\s*DE\s*D[ÉE]BITO|\bDEB\b", re.IGNORECASE)),
    ("credito", re.compile(r"CR[ÉE]DITO|CART[ÃA]O\s*DE\s*CR[ÉE]DITO|\bCRED\b", re.IGNORECASE)),
    ("dinheiro", re.compile(r"DINHEIRO|ESP[ÉE]CIE|TROCO", re.IGNORECASE)),
]


def _detectar_forma(texto: str) -> str | None:
    """Adivinha a forma de pagamento pelo texto do comprovante. None se incerto."""
    for forma, rx in _FORMAS_OCR:
        if rx.search(texto):
            return forma
    return None


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
    # Salva já com o domínio corrigido (RN: set→sefaz), pro link funcionar depois.
    from .nfce import corrigir_dominio

    out["url_nfce"] = corrigir_dominio(url_qr)
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


# Trechos que marcam linha de cabeçalho/rodapé/pagamento — nunca são item.
_RUIDO = (
    "CNPJ", "CPF", "CUPOM", "SAT", "NFC-E", "NFCE", "CHAVE", "PROTOCOLO",
    "CONSULTE", "CONSUMIDOR", "TRIBUTOS", "TROCO", "DINHEIRO", "CARTAO",
    "CARTÃO", "FORMA", "PAGAMENTO", "TOTAL", "DESCONTO", "ACRESCIMO",
    "QTD. TOTAL", "EXTRATO", "EMISSAO", "EMISSÃO", "WWW", "HTTP",
    # rodapé/pagamento que vazava como "item":
    "VALOR", "PAGAR", "PAGO", "CARTEIRA", "PIX", "DEBITO", "DÉBITO",
    "CREDITO", "CRÉDITO", "ESTAB", "AUTORIZA", "SERIE", "SÉRIE", "VIA ",
    "TEF", "SITEF", "FISERV", "TRANSACAO", "TRANSAÇÃO",
)


def _eh_ruido(linha: str) -> bool:
    return any(p in linha.upper() for p in _RUIDO)


def _eh_linha_de_item(linha: str) -> bool:
    """Filtra linhas que claramente não são itens (cabeçalho/rodapé/totais)."""
    if _eh_ruido(linha):
        return False
    return bool(re.search(_RE_MOEDA, linha))


def _parsear_item(linha: str, so_descricao: bool = False) -> dict | None:
    """Tenta extrair um item de uma linha. Devolve dict ou None.

    Com `so_descricao=True` (a linha de baixo é uma continuação de `qtd x unit`),
    não tenta extrair qtd/unidade da linha — assim "RICHESTER 125G" não vira
    qtd=125, un=G; o nome e o total ficam, e a qtd vem da linha seguinte.
    """
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

    m = None if so_descricao else _RE_QTD_X_UNIT.search(resto)
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
    elif not so_descricao and (mf := _RE_ITEM_FIM.search(resto)):
        # Formato sem "x" (o mais comum nas NFC-e): "<desc> <qtd><un> [vl_unit] vl_total".
        item["nome"] = resto[: mf.start()].strip(" .-")
        item["quantidade"] = _para_decimal(mf.group("qtd").replace(".", ","))
        item["unidade"] = mf.group("un").upper()
        if mf.group("v2"):  # tem unitário E total
            item["valor_unitario"] = _para_decimal(mf.group("v1"))
            item["valor"] = _para_decimal(mf.group("v2"))
        else:  # só o total
            item["valor"] = _para_decimal(mf.group("v1"))
        # Estruturado (tem qtd+un): confiável. Se temos unit, confere a conta.
        if item["quantidade"] and item["valor_unitario"]:
            esperado = (item["quantidade"] * item["valor_unitario"]).quantize(Decimal("0.01"))
            item["identificado"] = abs(item["valor"] - esperado) <= Decimal("0.05")
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


def _novo_item() -> dict:
    return {
        "nome": "", "codigo": None, "quantidade": None, "unidade": None,
        "valor_unitario": None, "valor": None, "identificado": False,
    }


def _parsear_descricao(linha: str) -> dict | None:
    """Linha de **descrição** de um item de 2 linhas — pode **não ter valor**
    (o valor está na linha de `qtd x unit` seguinte). Extrai nome + código +
    o total (se houver na própria linha). None se for ruído ou sem nome."""
    if _eh_ruido(linha):
        return None
    item = _novo_item()
    resto = linha.strip()
    m_cod = re.match(r"^\s*((?:\d{3,}\s+)+)", resto)
    if m_cod:
        item["codigo"] = max(m_cod.group(1).split(), key=len)
        resto = resto[m_cod.end():]
    item["valor"] = _ultima_moeda(resto)
    nome = re.sub(_RE_MOEDA, "", resto).strip(" .-")
    if len(nome) < 2:
        return None
    item["nome"] = nome
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


def _limpar_ocr(texto: str) -> str:
    """Conserta ruídos comuns do OCR térmico nos valores, sem tocar em códigos:
    "3, 19"→"3,19" (espaço no decimal) e "6.49"→"6,49" (ponto no lugar da vírgula,
    só com 2 casas — não mexe em milhar tipo "1.234,56" nem em EAN/CNPJ)."""
    texto = re.sub(r"(\d)\s*,\s+(\d{2})(?!\d)", r"\1,\2", texto)
    texto = re.sub(r"(\d)\.(\d{2})(?!\d)", r"\1,\2", texto)
    return texto


def _achar_data(texto: str) -> str | None:
    """Primeira data DD/MM/AA(AA) do cupom → ISO AAAA-MM-DD. None se não houver/for inválida."""
    from datetime import date

    for m in _RE_DATA_OCR.finditer(texto or ""):
        d, mes, ano = m.groups()
        ano = "20" + ano if len(ano) == 2 else ano
        try:
            return date(int(ano), int(mes), int(d)).isoformat()
        except ValueError:
            continue
    return None


def _maior_moeda(linhas: list[str]) -> Decimal | None:
    """Maior valor monetário do texto — fallback p/ comprovante sem 'total' claro
    (maquininha/recibo), onde o valor principal costuma ser o maior."""
    valores = [
        _para_decimal(m) for linha in linhas for m in re.findall(_RE_MOEDA, linha)
    ]
    valores = [v for v in valores if v is not None]
    return max(valores) if valores else None


def _num(d: Decimal | None):
    return float(d) if d is not None else None


def _preview_da_nfce(nfce: dict, qr: dict) -> dict:
    """Monta o preview a partir dos itens estruturados buscados no portal (RN-024).

    Esses itens são confiáveis (vêm da SEFAZ, não do OCR), então `origem="qr"`
    e cada item já entra `identificado=True`.
    """
    itens = nfce["itens"]
    total_itens_valor = sum((i["valor"] for i in itens), Decimal("0"))
    total = nfce.get("total") or total_itens_valor
    total_confere = bool(itens) and abs(total - total_itens_valor) <= Decimal("0.10")
    return {
        "origem": "qr",
        "estabelecimento": nfce.get("estabelecimento"),
        "data": nfce.get("data"),
        "categoria_sugerida": None,
        "forma_sugerida": None,
        "url_nfce": qr["url_nfce"],
        "uf": qr["uf"],
        "cnpj": nfce.get("cnpj") or qr.get("cnpj"),
        "chave": qr["chave"],
        "total": _num(total),
        "total_itens": len(itens),
        "desconto": _num(nfce.get("desconto")),
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


def _mesclar_qtd(item: dict, mq: re.Match, total_linha: Decimal | None = None) -> None:
    """Aplica a linha de quantidade (`qtd un x vl_unit [tax] [total]`) num item.
    Se o item ainda não tem total, usa o `total_linha` (último valor da própria
    linha de quantidade)."""
    item["quantidade"] = _para_decimal(mq.group("qtd").replace(".", ","))
    item["unidade"] = mq.group("un").upper()
    item["valor_unitario"] = _para_decimal(mq.group("vunit"))
    if item["valor"] is None:
        item["valor"] = total_linha
    if item["quantidade"] and item["valor_unitario"] and item["valor"] is not None:
        esperado = (item["quantidade"] * item["valor_unitario"]).quantize(Decimal("0.01"))
        item["identificado"] = abs(item["valor"] - esperado) <= Decimal("0.05")
    elif item["valor"] is not None:
        item["identificado"] = True


def parsear_cupom(
    texto_ocr: str = "",
    url_qr: str | None = None,
    linhas_ocr: list[dict] | None = None,
    buscar_online: bool = True,
) -> dict:
    """Parser principal. Devolve o preview (dict) consumido pelo app.

    Tendo a URL do QR, tenta primeiro buscar os **itens estruturados** no portal
    da SEFAZ (`nfce.buscar_nfce`) — muito mais confiável. Falhando (sem rede,
    captcha, layout desconhecido) ou sem QR, cai no parser **heurístico do texto
    do OCR**. `buscar_online=False` desliga a rede (usado nos testes).

    `linhas_ocr` são os fragmentos do OCR com geometria (`{text,x,y,h,w}`); quando
    presentes, o texto é **reconstruído** por posição (`ocr_layout.reconstruir_texto`),
    o que conserta o embaralhamento de colunas do ML Kit. Itens em 2 linhas físicas
    (descrição+total numa, `qtd un x vl_unit` na outra) são mesclados.
    """
    qr = _dados_do_qr(url_qr)

    if url_qr and buscar_online:
        from django.conf import settings

        if getattr(settings, "NFCE_FETCH_ENABLED", True):
            from .nfce import buscar_nfce

            nfce = buscar_nfce(
                url_qr, timeout=getattr(settings, "NFCE_FETCH_TIMEOUT", 8)
            )
            if nfce and nfce.get("itens"):
                return _preview_da_nfce(nfce, qr)

    origem = "qr" if url_qr else "ocr"

    if linhas_ocr:
        from .ocr_layout import reconstruir_texto

        texto_ocr = reconstruir_texto(linhas_ocr)

    texto_ocr = _limpar_ocr(texto_ocr or "")
    linhas = [l for l in texto_ocr.splitlines() if l.strip()]

    # Itens em 2 linhas físicas: uma de descrição (com ou sem o total) e a
    # seguinte de "qtd un x vl_unit". Guardamos a descrição em `pendente` e
    # casamos com a linha de quantidade. Itens de 1 linha são resolvidos direto.
    itens: list[dict] = []
    pendente: dict | None = None

    def _soltar_pendente():
        nonlocal pendente
        if pendente and pendente["valor"] is not None and pendente["valor"] > 0:
            itens.append(pendente)
        pendente = None

    n = len(linhas)
    for idx, linha in enumerate(linhas):
        mq = _RE_LINHA_QTD.match(linha)
        if mq:
            total_linha = _ultima_moeda(linha)
            alvo = pendente
            pendente = None
            if alvo is None and itens and itens[-1].get("quantidade") is None:
                alvo = itens.pop()
            if alvo is not None:
                _mesclar_qtd(alvo, mq, total_linha)
                if alvo["nome"] and alvo["valor"] is not None and alvo["valor"] > 0:
                    itens.append(alvo)
            continue

        _soltar_pendente()
        proxima = linhas[idx + 1] if idx + 1 < n else ""
        if _RE_LINHA_QTD.match(proxima):
            # Esta é a linha de descrição de um item de 2 linhas (a qtd vem na
            # próxima) — pode estar sem valor; segura como pendente.
            pendente = _parsear_descricao(linha)
        else:
            item = _parsear_item(linha)
            if item:
                itens.append(item)
    _soltar_pendente()

    total_itens = sum((i["valor"] for i in itens), Decimal("0"))
    total = _achar_total(linhas)
    if total is None:
        # Sem "total" explícito: com itens, soma deles; sem itens (comprovante de
        # maquininha/recibo), o maior valor monetário do texto.
        total = total_itens if itens else _maior_moeda(linhas)

    # Confere se a soma dos itens bate com o total. Havendo desconto na nota, a
    # soma dos itens fica acima do pago — a diferença é o próprio desconto, e
    # isso ainda é consistente (não é erro de OCR).
    tem_desconto = any(_RE_DESCONTO.search(l) for l in linhas)
    desconto = None
    total_confere = False
    if itens and total is not None:
        diff = total_itens - total
        if abs(diff) <= Decimal("0.10"):
            total_confere = True
        elif tem_desconto and Decimal("0") < diff <= total_itens:
            desconto = diff
            total_confere = True

    cnpj_match = _RE_CNPJ.search(texto_ocr or "")
    estabelecimento = _achar_estabelecimento(linhas)
    quantidade_itens = None
    m_qtd = _RE_ITENS_TOTAL.search(texto_ocr or "")
    if m_qtd:
        quantidade_itens = int(m_qtd.group(1))

    return {
        "origem": origem,
        "estabelecimento": estabelecimento,
        "data": _achar_data(texto_ocr or ""),
        "categoria_sugerida": None,
        "forma_sugerida": _detectar_forma(texto_ocr or ""),
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
