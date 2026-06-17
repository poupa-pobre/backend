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
_RE_MOEDA = r"\d{1,3}(?:\.\d{3})*,\d{2,4}|\d+,\d{2,4}"

# Padrão "qtd [unidade] x valor_unitário" no meio da linha do item.
_RE_QTD_X_UNIT = re.compile(
    r"(?P<qtd>\d+(?:[.,]\d{1,3})?)\s*"
    r"(?P<un>UN|UNID|KG|G|L|ML|PC|PCT|CX|DZ|MT|M)?\s*"
    r"(?:[xX*H8-]\s*|(?<=\bUN)\s+|(?<=\bUND)\s+|(?<=\bUNID)\s+|(?<=\bKG)\s+|(?<=\bKGS)\s+)"
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
    r"(?:[xX*H8-]\s*|(?<=\bUN)\s+|(?<=\bUND)\s+|(?<=\bUNID)\s+|(?<=\bKG)\s+|(?<=\bKGS)\s+)"
    r"(?P<vunit>" + _RE_MOEDA + r")",
    re.IGNORECASE,
)

# Linha de quantidade fallback (procura em qualquer parte do texto)
_RE_FALLBACK_QTD_UN = re.compile(
    r"\b(?P<qtd>\d+(?:[.,]\d{1,3})?)\s*(?P<un>UNID|UND|UN|KGS|KG|PCT|PC|ML|MT|GR|CX|DZ|L|G|M)\b",
    re.IGNORECASE,
)



# Número sequencial do item (001, 002, ...) que abre cada produto na NFC-e.
# Casa um número de 1-3 dígitos **como token isolado** (seguido de espaço + algo),
# pra não confundir com o EAN colado (13 dígitos sem espaço no meio).
# Aceita letras comumente confundidas com dígitos (O, U, Q, D).
_RE_SEQ = re.compile(r"^\s*([0-9OUQDouqd]{1,3})\s+\S")

# Linha que carrega o total da nota. Inclui formas comuns de comprovante de
# maquininha/recibo ("VALOR R$", "VALOR PAGO", "VALOR COBRADO"), não só NFC-e.
_RE_TOTAL = re.compile(
    r"(VALOR\s*A\s*PAGAR|VALOR\s*TOTAL|VL\.?\s*TOTAL|TOTAL\s*R\$|^TOTAL|"
    r"VALOR\s*PAGO|VALOR\s*COBRADO|VALOR\s*DA\s*COMPRA|VALOR\s*R\$)",
    re.IGNORECASE,
)
_RE_DESCONTO = re.compile(r"DESCONTO|DESC\.", re.IGNORECASE)
# Cabeçalho da tabela de itens ("#|COD|DESCRICAO|QTD|UN|VL UN|VL TOTAL"). Fica no
# **topo**, antes dos itens, e contém "VL TOTAL" — então confundia o detector de
# rodapé/total, que cortava os itens logo na largada. Nunca é rodapé nem item.
_RE_CABECALHO_COL = re.compile(r"DESCRI[CÇ]|VL\.?\s*UN", re.IGNORECASE)
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


# Palavras de rodapé/pagamento **distintivas** (nenhum produto se chama assim) que
# o OCR térmico costuma embaralhar — casadas por distância de edição, não exato:
# "TROCO"→"Iroco"/"ir0co", "DINHEIRO"→"Dirieiro"/"Dirheiro", "TRIBUTOS"→"ribatos".
_RUIDO_FUZZY = (
    "troco", "dinheiro", "tributos", "pagamento", "federal", "incidentes",
    "autorizacao", "contingencia", "fiserv", "sitef", "estadual", "municipal",
)

_RE_ACENTO = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüç", "aaaaaeeeeiiiiooooouuuuc")


def _normalizar(palavra: str) -> str:
    """Minúsculo, sem acento, só letras, com as trocas típicas do OCR (0→o, 1→i)."""
    p = palavra.lower().translate(_RE_ACENTO)
    p = p.replace("0", "o").replace("1", "i").replace("5", "s")
    return re.sub(r"[^a-z]", "", p)


def _distancia(a: str, b: str) -> int:
    """Distância de Levenshtein (curta — palavras de rodapé têm ~5-12 letras)."""
    if a == b:
        return 0
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        atual = [i]
        for j, cb in enumerate(b, 1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1,
                             anterior[j - 1] + (ca != cb)))
        anterior = atual
    return anterior[-1]


def _eh_rodape_fuzzy(linha: str) -> bool:
    """True se algum token da linha casa (com folga p/ ruído do OCR) uma palavra
    de rodapé/pagamento. Tolera 1 erro em palavras curtas, 2 nas longas."""
    for token in re.split(r"\s+", linha):
        norm = _normalizar(token)
        if len(norm) < 5:
            continue
        for alvo in _RUIDO_FUZZY:
            limite = 2 if len(alvo) >= 7 else 1
            if abs(len(norm) - len(alvo)) <= limite and _distancia(norm, alvo) <= limite:
                return True
    return False


def _eh_ruido(linha: str) -> bool:
    return any(p in linha.upper() for p in _RUIDO) or _eh_rodape_fuzzy(linha)


def _eh_linha_de_item(linha: str) -> bool:
    """Filtra linhas que claramente não são itens (cabeçalho/rodapé/totais)."""
    if _eh_ruido(linha):
        return False
    return bool(re.search(_RE_MOEDA, linha))


def _separar_item_do_cabecalho(linha: str) -> str:
    """Quando a reconstrução funde o cabeçalho de colunas com o 1º item (ficam
    quase na mesma altura Y), a linha vira "...VL TOTAL  001 EAN PRODUTO 6,49" e o
    item se perde (não abre com o sequencial). Se houver um item (seq + EAN) depois
    do cabeçalho, devolve só a parte do item; senão deixa a linha intacta."""
    if not _RE_CABECALHO_COL.search(linha):
        return linha
    m = re.search(r"\b[0-9OUQDouqd]{1,3}\s+\d{8,}", linha)
    return linha[m.start():] if m else linha


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
    else:
        # Se for grudado por vírgula, espaço ou sem nada (ex: "7891152801842,BISCQITO")
        m_cod_grudado = re.match(r"^\s*(\d{8,15})(?=[^\d]|$)", resto)
        if m_cod_grudado:
            item["codigo"] = m_cod_grudado.group(1)
            resto = resto[m_cod_grudado.end():].strip(" ,.-")

    m = None if so_descricao else _RE_QTD_X_UNIT.search(resto)
    if m:
        # Formato rico: "<descrição> qtd [un] x vl_unit", com o total antes OU
        # depois (depende do layout/reconstrução do OCR).
        item["nome"] = resto[: m.start()].strip(" .-")
        item["quantidade"] = _para_decimal(m.group("qtd").replace(".", ","))
        item["unidade"] = (m.group("un") or "").upper() or None
        item["valor_unitario"] = _para_decimal(m.group("unit"))
        if item["quantidade"] and item["valor_unitario"]:
            # O total é a moeda da linha que melhor casa com qtd×unit — assim não
            # confunde com o vl_unitário nem importa se o total veio antes do "x".
            esperado = (item["quantidade"] * item["valor_unitario"]).quantize(Decimal("0.01"))
            cand = [c for c in (_para_decimal(x) for x in re.findall(_RE_MOEDA, resto)) if c is not None]
            valid_cand = [c for c in cand if abs(c - esperado) <= Decimal("0.05")]
            if valid_cand:
                melhor = min(valid_cand, key=lambda c: abs(c - esperado))
                item["valor"] = melhor
                item["identificado"] = True
            else:
                item["valor"] = esperado
                item["identificado"] = True
        else:
            item["valor"] = _ultima_moeda(resto[m.end():]) or _ultima_moeda(resto)
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
            if item["quantidade"] and item["quantidade"] > 0:
                item["valor_unitario"] = (item["valor"] / item["quantidade"]).quantize(Decimal("0.01"))
        # Estruturado (tem qtd+un): confiável. Se temos unit, confere a conta.
        if item["quantidade"] and item["valor_unitario"]:
            esperado = (item["quantidade"] * item["valor_unitario"]).quantize(Decimal("0.01"))
            item["identificado"] = abs(item["valor"] - esperado) <= Decimal("0.05")
        else:
            item["identificado"] = item["valor"] is not None
    else:
        # Fallback robusto/heurístico para blocos com ruído de OCR
        # 1. Tenta achar quantidade e unidade em qualquer lugar do resto
        qtd_matches = list(_RE_FALLBACK_QTD_UN.finditer(resto))
        best_match = None
        if qtd_matches:
            # Prioriza o match que está perto de um 'x' ou '*'
            for m in qtd_matches:
                after_text = resto[m.end():m.end()+10]
                if re.search(r"^\s*[xX*]", after_text):
                    best_match = m
                    break
            if not best_match:
                best_match = qtd_matches[-1]

        resto_sem_qtd = resto
        if best_match:
            item["quantidade"] = _para_decimal(best_match.group("qtd").replace(".", ","))
            if item["quantidade"] == Decimal("0"):
                item["quantidade"] = Decimal("1")
            item["unidade"] = best_match.group("un").upper()
            # Remove a quantidade da string de resto para não confundir a busca por preços
            resto_sem_qtd = resto[:best_match.start()] + " " + resto[best_match.end():]

        # 2. Encontra todos os números com formato de valor decimal no bloco
        prices = []
        # Encontra tokens decimais (com ponto ou vírgula e 2 a 4 decimais)
        for token in re.split(r"\s+", resto_sem_qtd):
            # Remove caracteres adicionais comuns que grudam no valor (como F, T20, R$, etc.)
            token_limpo = re.sub(r"[^\d.,]", "", token)
            # Se for um decimal válido
            if re.match(r"^\d+[.,]\d{2,4}$", token_limpo):
                val = _para_decimal(token_limpo)
                if val is not None and val > 0:
                    prices.append(val)

        if prices:
            if len(prices) >= 2:
                item["valor"] = prices[-1]
                item["valor_unitario"] = prices[-2]
            else:
                item["valor"] = prices[0]
                if item["quantidade"]:
                    item["valor_unitario"] = (item["valor"] / item["quantidade"]).quantize(Decimal("0.01"))

            # 3. Tenta reconstruir o nome do produto limpando o código, a quantidade e os valores
            nome = resto
            if best_match:
                nome = nome.replace(best_match.group(0), "")
            for p in re.findall(r"\b\d+[.,]\d{2,4}\b|\b\d+[.,]\d{2}\b", nome):
                nome = nome.replace(p, "")
            
            # Remove códigos/barras que possam ter sobrado (ex. tokens com 8+ dígitos)
            nome = re.sub(r"\b\d{8,}\b", "", nome)
            # Remove termos de unidade avulsos
            nome = re.sub(r"\b(UN|UNID|KG|G|L|ML|PC|PCT|CX|DZ|MT|M)\b", "", nome, flags=re.IGNORECASE)
            # Remove ruídos de alíquotas fiscais típicas do OCR (S19F, 9E, T20, F1, I1, T18, etc.)
            nome = re.sub(r"\b([sS]\d+[fF]|[0-9OUQDouqd]{1,3}[eE]|[tT]\d+|[fFiInNtTgGsS]\d*|[fFiInNtTgGsS]\d*%?)\b", "", nome)
            # Remove operadores e caracteres especiais
            nome = re.sub(r"[xX*+\-/=]", " ", nome)
            item["nome"] = re.sub(r"\s+", " ", nome).strip(" .-")
            
            # Valida math de verificação
            if item["quantidade"] and item["valor_unitario"]:
                esperado = (item["quantidade"] * item["valor_unitario"]).quantize(Decimal("0.01"))
                item["identificado"] = abs(item["valor"] - esperado) <= Decimal("0.05")
            else:
                item["identificado"] = False
        else:
            # Fallback definitivo de emergência
            valor = _ultima_moeda(resto)
            if valor is None:
                return None
            nome = re.sub(_RE_MOEDA, "", resto)
            nome = re.sub(r"\b(UN|UNID|KG|G|L|ML|PC|PCT|CX|DZ|MT|M)\b", "", nome, flags=re.IGNORECASE)
            item["nome"] = nome.strip(" .-xX*")
            item["valor"] = valor
            item["identificado"] = False

    # Um nome de produto nunca contém um valor monetário (ex.: quando a descrição
    # e o total caem na mesma linha reconstruída) — limpa qualquer moeda do nome.
    if item["nome"]:
        item["nome"] = re.sub(_RE_MOEDA, "", item["nome"]).strip(" .-")

    if not item["nome"] or item["valor"] is None or item["valor"] <= 0:
        return None
    # Todo produto tem nome com letras; "8", "1 00" ou um token de rodapé garbled
    # que escapou viram lixo na lista. Exige ao menos 2 letras no nome.
    if sum(c.isalpha() for c in item["nome"]) < 2:
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
        if _RE_CABECALHO_COL.search(linha):  # "VL TOTAL" do cabeçalho não é o total
            continue
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


def _seq_do_inicio(linha: str) -> int | None:
    """Se a linha abre um item, devolve o número sequencial; senão None.

    Exige o sequencial como token isolado e que o resto pareça um item de fato —
    tem EAN (8+ dígitos) **ou** uma descrição (3+ letras) — pra não confundir com
    a linha de quantidade "1 UN X 6,49" (que começa com número, mas é continuação).
    Normaliza letras comumente confundidas com dígitos (O, U, Q, D).
    """
    m = _RE_SEQ.match(linha)
    if not m or _RE_LINHA_QTD.match(linha):
        return None

    token = m.group(1)
    for c in "OUQDouqd":
        token = token.replace(c, "0").replace(c.lower(), "0")

    if not token.strip("0"):
        return None

    resto = linha[m.start(1) + len(m.group(1)) :]
    tem_ean = re.search(r"\d{8,}", resto)
    tem_texto = re.search(r"[A-Za-zÀ-ÿ]{3,}", resto)
    try:
        val = int(token)
        return val if (tem_ean or tem_texto) else None
    except ValueError:
        return None


def encontrar_melhor_sequencia(candidates: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Encontra a maior subsequência crescente de números sequenciais usando LIS (gaps de até 4)."""
    if not candidates:
        return []

    memo = {}

    def get_longest_chain(start_idx):
        if start_idx in memo:
            return memo[start_idx]

        best_chain = [candidates[start_idx]]
        curr_line, curr_val = candidates[start_idx]

        for next_idx in range(start_idx + 1, len(candidates)):
            next_line, next_val = candidates[next_idx]
            if next_val > curr_val and (next_val - curr_val) <= 4:
                chain = [candidates[start_idx]] + get_longest_chain(next_idx)
                if len(chain) > len(best_chain):
                    best_chain = chain

        memo[start_idx] = best_chain
        return best_chain

    overall_best = []
    for i in range(len(candidates)):
        chain = get_longest_chain(i)
        if len(chain) > len(overall_best):
            overall_best = chain

    return overall_best


def _parsear_por_sequencial(linhas: list[str]) -> list[dict] | None:
    """Estratégia principal do OCR: ancora nos números sequenciais dos itens.

    Acha as linhas que abrem cada item (sequencial crescente,
    tolerando lacunas — o OCR às vezes pula um), delimita o bloco de cada item
    (da sua âncora até a próxima, ou até o rodapé/total) e roda o `_parsear_item`
    no bloco inteiro — assim itens em 2 linhas (descrição numa, "qtd un x vlr
    total" na outra) ficam juntos. Devolve `None` se não achar um
    sequencial confiável (≥2 itens), pra cair no heurístico.
    """
    # Os itens vivem **antes** da 1ª linha de total/desconto/qtd-de-itens — tudo
    # dali pra frente é rodapé e não pode virar item nem poluir o último bloco.
    fim_itens = len(linhas)
    for idx, linha in enumerate(linhas):
        if _RE_CABECALHO_COL.search(linha):  # cabeçalho de colunas não fecha os itens
            continue
        if (
            _RE_TOTAL.search(linha)
            or _RE_DESCONTO.search(linha)
            or _RE_ITENS_TOTAL.search(linha)
        ):
            fim_itens = idx
            break

    candidates = []
    for idx in range(fim_itens):
        seq = _seq_do_inicio(linhas[idx])
        if seq is not None:
            candidates.append((idx, seq))

    overall_best = encontrar_melhor_sequencia(candidates)
    if len(overall_best) < 2:
        return None

    anchors = [line_idx for line_idx, seq_val in overall_best]
    first_val = overall_best[0][1]
    first_line = overall_best[0][0]

    # Prepend backwards (tenta resgatar âncoras anteriores corrompidas)
    current_line = first_line
    for expected_val in range(first_val - 1, 0, -1):
        found_line = None
        for prev_line in range(current_line - 1, max(-1, current_line - 5), -1):
            m = _RE_SEQ.match(linhas[prev_line])
            if m and not _RE_LINHA_QTD.match(linhas[prev_line]) and not _eh_ruido(linhas[prev_line]):
                found_line = prev_line
                break
        if found_line is not None:
            anchors.insert(0, found_line)
            current_line = found_line
        else:
            break

    # Gap filling no meio
    final_anchors = []
    for i in range(len(overall_best)):
        curr_line, curr_val = overall_best[i]
        if i > 0:
            prev_line, prev_val = overall_best[i - 1]
            if curr_val - prev_val > 1:
                possible_mid_lines = []
                for mid_line in range(prev_line + 1, curr_line):
                    m = _RE_SEQ.match(linhas[mid_line])
                    if m and not _RE_LINHA_QTD.match(linhas[mid_line]) and not _eh_ruido(linhas[mid_line]):
                        possible_mid_lines.append(mid_line)
                final_anchors.extend(possible_mid_lines)
        if not final_anchors or curr_line > final_anchors[-1]:
            final_anchors.append(curr_line)

    all_anchors = sorted(list(set(anchors + final_anchors)))

    itens: list[dict] = []
    for i, start in enumerate(all_anchors):
        end = all_anchors[i + 1] if i + 1 < len(all_anchors) else fim_itens
        bloco = " ".join(l.strip() for l in linhas[start:end])
        bloco = re.sub(r"^\s*[0-9OUQDouqd]{1,3}\s+", "", bloco, count=1)  # tira o sequencial
        item = _parsear_item(bloco)
        if item:
            itens.append(item)
    return itens or None


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
    linhas = [_separar_item_do_cabecalho(l) for l in texto_ocr.splitlines() if l.strip()]

    # Estratégia principal: ancorar nos sequenciais (001, 002…). Robusta a
    # mudanças de layout entre cupons. Só cai no parser heurístico linha-a-linha
    # quando não há um sequencial confiável.
    itens: list[dict] = _parsear_por_sequencial(linhas) or []

    if not itens:
        # Fallback heurístico — itens em 2 linhas físicas: uma de descrição (com
        # ou sem o total) e a seguinte de "qtd un x vl_unit". Guardamos a
        # descrição em `pendente` e casamos com a linha de quantidade; itens de 1
        # linha vão direto.
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
                # Linha de descrição de um item de 2 linhas (a qtd vem na próxima)
                # — pode estar sem valor; segura como pendente.
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
