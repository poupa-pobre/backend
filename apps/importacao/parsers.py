"""
Leitura de extratos **OFX** e **CSV** (RF-111) — sem dependência externa.

Cada parser devolve uma lista de transações normalizadas:

    {"data": date, "valor": Decimal(>0), "descricao": str, "tipo": "gasto"|"receita"}

O **sinal** do valor no arquivo decide o tipo (negativo/saída = gasto, positivo/
entrada = receita); `valor` é sempre **positivo** (o domínio guarda o módulo e o
tipo à parte). Datas e valores vêm em formatos variados de banco — os helpers
abaixo toleram os mais comuns no Brasil (DD/MM/AAAA, AAAA-MM-DD; vírgula ou
ponto decimal).
"""

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class ArquivoInvalido(ValueError):
    """Conteúdo não reconhecido como OFX/CSV de extrato."""


def _parsear_data(bruto):
    """Aceita AAAAMMDD (OFX), DD/MM/AAAA, DD/MM/AA, AAAA-MM-DD. Devolve date ou None."""
    s = (bruto or "").strip()
    if not s:
        return None
    # OFX: 20240115120000[-3:GMT] → pega os 8 primeiros dígitos.
    m = re.match(r"(\d{8})", s)
    if m and "/" not in s and "-" not in s[:8]:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parsear_valor(bruto):
    """Normaliza '−1.234,56' / '-1234.56' / 'R$ 45,90' → Decimal (com sinal)."""
    s = (bruto or "").strip()
    if not s:
        return None
    negativo = s.startswith("-") or s.startswith("−") or "(" in s
    s = re.sub(r"[^\d,.-]", "", s).lstrip("-−")
    if not s:
        return None
    # Se tem vírgula e ponto, o último separador é o decimal.
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return -v if negativo else v


def _normalizar(data, valor, descricao):
    """Monta a transação no formato do domínio, ou None se faltar dado essencial."""
    if data is None or valor is None or valor == 0:
        return None
    descricao = re.sub(r"\s+", " ", (descricao or "").strip())[:120] or "Lançamento importado"
    return {
        "data": data,
        "valor": abs(valor),
        "descricao": descricao,
        "tipo": "gasto" if valor < 0 else "receita",
    }


# --- OFX -------------------------------------------------------------------

_RE_STMTTRN = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.IGNORECASE | re.DOTALL)


def _tag_ofx(bloco, tag):
    """Lê o valor de uma tag OFX (SGML sem fechamento ou XML)."""
    m = re.search(rf"<{tag}>\s*([^<\r\n]*)", bloco, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parsear_ofx(conteudo):
    blocos = _RE_STMTTRN.findall(conteudo)
    if not blocos:
        raise ArquivoInvalido("Nenhuma transação (<STMTTRN>) encontrada no OFX.")
    transacoes = []
    for b in blocos:
        data = _parsear_data(_tag_ofx(b, "DTPOSTED"))
        valor = _parsear_valor(_tag_ofx(b, "TRNAMT"))
        descricao = _tag_ofx(b, "NAME") or _tag_ofx(b, "MEMO")
        t = _normalizar(data, valor, descricao)
        if t:
            transacoes.append(t)
    return transacoes


# --- CSV -------------------------------------------------------------------

_COLS_DATA = ("data", "date", "dt")
_COLS_VALOR = ("valor", "value", "amount", "montante", "vlr")
_COLS_DESC = ("descri", "histor", "lancamento", "lançamento", "memo", "name", "title", "detalhe")


def _achar_coluna(cabecalho, candidatos):
    for i, col in enumerate(cabecalho):
        c = col.strip().lower()
        if any(k in c for k in candidatos):
            return i
    return None


def parsear_csv(conteudo):
    # Detecta o delimitador (bancos BR usam ';' com frequência).
    amostra = conteudo[:2048]
    delim = ";" if amostra.count(";") >= amostra.count(",") else ","
    linhas = list(csv.reader(io.StringIO(conteudo), delimiter=delim))
    linhas = [l for l in linhas if any(c.strip() for c in l)]
    if not linhas:
        raise ArquivoInvalido("CSV vazio.")

    cabecalho = [c.strip().lower() for c in linhas[0]]
    i_data = _achar_coluna(cabecalho, _COLS_DATA)
    i_valor = _achar_coluna(cabecalho, _COLS_VALOR)
    i_desc = _achar_coluna(cabecalho, _COLS_DESC)

    if i_data is not None and i_valor is not None:
        corpo = linhas[1:]
    else:
        # Sem cabeçalho reconhecível: assume data, descrição, valor por posição.
        i_data, i_desc, i_valor = 0, 1, 2
        corpo = linhas

    transacoes = []
    for linha in corpo:
        if max(i_data, i_valor, (i_desc or 0)) >= len(linha):
            continue
        data = _parsear_data(linha[i_data])
        valor = _parsear_valor(linha[i_valor])
        descricao = linha[i_desc] if i_desc is not None and i_desc < len(linha) else ""
        t = _normalizar(data, valor, descricao)
        if t:
            transacoes.append(t)
    if not transacoes:
        raise ArquivoInvalido("Nenhuma transação válida no CSV.")
    return transacoes


def parsear(conteudo, formato):
    """Despacha pelo formato ('ofx'|'csv'); detecta sozinho se vier vazio/auto."""
    fmt = (formato or "").lower().lstrip(".")
    if fmt == "ofx":
        return parsear_ofx(conteudo)
    if fmt == "csv":
        return parsear_csv(conteudo)
    # Auto: OFX tem a tag; senão tenta CSV.
    if "<STMTTRN>" in conteudo.upper():
        return parsear_ofx(conteudo)
    return parsear_csv(conteudo)
