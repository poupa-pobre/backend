"""
Export PDF do relatório de gastos por categoria (RF-101) — via reportlab
(pure-Python, sem dependência de sistema, compatível com o deploy).

Cabeçalho com o nome do relatório e o período, tabela de categorias com valor e
percentual, o total do mês × mês anterior, e a data de geração no rodapé.
"""

from datetime import datetime
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_MESES = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

_VERDE = colors.HexColor("#2DD4A7")
_CINZA = colors.HexColor("#6B7280")


def _brl(valor):
    v = Decimal(str(valor or 0)).quantize(Decimal("0.01"))
    inteiro, _, dec = f"{v:.2f}".partition(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return f"{sinal}R$ {'.'.join(grupos)},{dec}"


def gerar_pdf_relatorio(dados, nome_usuario=""):
    """Recebe o dict de `montar_relatorio` e devolve os bytes do PDF."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Relatório de gastos por categoria",
    )
    estilos = getSampleStyleSheet()
    h_titulo = ParagraphStyle(
        "Titulo", parent=estilos["Title"], fontSize=20, textColor=colors.HexColor("#111827")
    )
    h_sub = ParagraphStyle("Sub", parent=estilos["Normal"], fontSize=11, textColor=_CINZA)
    rodape = ParagraphStyle("Rodape", parent=estilos["Normal"], fontSize=8, textColor=_CINZA)

    mes = dados["mes_referencia"]
    periodo = f"{_MESES[mes.month]} de {mes.year}"
    total = Decimal(str(dados["total"]))
    anterior = Decimal(str(dados["total_mes_anterior"]))

    elementos = [
        Paragraph("Gastos por categoria", h_titulo),
        Paragraph(f"Período: {periodo}" + (f" · {nome_usuario}" if nome_usuario else ""), h_sub),
        Spacer(1, 8 * mm),
    ]

    linhas = [["Categoria", "Valor", "%"]]
    for c in dados["categorias"]:
        v = Decimal(str(c["total"]))
        pct = (v / total * 100) if total > 0 else Decimal("0")
        linhas.append([c["nome"], _brl(v), f"{pct:.1f}%"])
    if len(linhas) == 1:
        linhas.append(["Nenhum gasto no período", "—", "—"])
    linhas.append(["Total", _brl(total), "100%"])

    tabela = Table(linhas, colWidths=[90 * mm, 50 * mm, 30 * mm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _VERDE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, _CINZA),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F3F4F6")]),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elementos.append(tabela)

    elementos.append(Spacer(1, 6 * mm))
    delta = total - anterior
    comparativo = (
        f"Mês anterior: {_brl(anterior)} · "
        f"{'+' if delta >= 0 else '−'}{_brl(abs(delta))} em relação ao mês anterior"
    )
    elementos.append(Paragraph(comparativo, h_sub))

    elementos.append(Spacer(1, 14 * mm))
    gerado = datetime.now().strftime("%d/%m/%Y às %H:%M")
    elementos.append(Paragraph(f"Gerado em {gerado} · Poupa Pobre", rodape))

    doc.build(elementos)
    return buffer.getvalue()
