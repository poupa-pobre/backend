"""
Parser de **notificação de Pix** (Android NotificationListener).

No Android, o app lê o texto das notificações dos apps de banco e manda pra cá.
Aqui extraímos, de forma tolerante (cada banco escreve diferente), se foi Pix
**recebido** (→ vira Receita) ou **enviado** (→ vira Gasto), o **valor** e a
**contraparte** (de quem veio / pra quem foi). Nada é persistido aqui — o que
salva é a caixa de revisão, depois da confirmação do usuário (evita duplicar
com o OFX e lançar lixo).

Exemplos reais:
- Nubank recebido: "Você recebeu uma transferência de R$2,00 de Fulano de Tal"
- Nubank (título/corpo): "Transferência recebida — Recebemos sua transferência de R$ 50,00"
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Valor monetário pt-BR (com ou sem espaço após R$): R$2,00 · R$ 1.234,56.
_RE_MOEDA = r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}"
_RE_VALOR = re.compile(r"R\$\s*(" + _RE_MOEDA + r")", re.IGNORECASE)

_RE_RECEBIDO = re.compile(
    r"recebeu uma transfer|recebemos sua transfer|transfer[êe]ncia recebida|"
    r"pix recebido|voc[êe] recebeu|recebeu um pix|entrou na sua conta",
    re.IGNORECASE,
)
_RE_ENVIADO = re.compile(
    r"transfer[êe]ncia enviada|pix enviado|voc[êe] enviou|enviou um pix|"
    r"enviamos sua transfer|sa[ií]u da sua conta|pagamento enviado",
    re.IGNORECASE,
)


# Package do app → nome do banco. Serve também de **lista branca**: o listener
# nativo só escuta notificações desses packages (privacidade + bateria).
# Best-effort — ajustar os packages conforme aparecerem nos aparelhos reais.
BANCOS = {
    "com.nu.production": "Nubank",
    "com.nubank.app": "Nubank",
    "br.com.intermedium": "Inter",
    "com.c6bank.app": "C6 Bank",
    "br.com.bb.android": "Banco do Brasil",
    "com.itau": "Itaú",
    "com.itau.empresas": "Itaú",
    "com.bradesco": "Bradesco",
    "br.com.gabba.Caixa": "Caixa",
    "com.santander.app": "Santander",
    "com.picpay": "PicPay",
    "com.mercadopago.wallet": "Mercado Pago",
    "br.com.original.bank": "Original",
}


def identificar_banco(pacote: str) -> str | None:
    """Nome do banco a partir do package do app (None se não mapeado)."""
    return BANCOS.get((pacote or "").strip())


def _para_decimal(texto: str | None) -> Decimal | None:
    if not texto:
        return None
    try:
        return Decimal(texto.strip().replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def parsear_notificacao(texto: str = "", titulo: str = "", pacote: str = "") -> dict:
    """Devolve {tipo, valor, contraparte, texto}. `tipo` é 'recebido'/'enviado'/None.
    `pacote` (package do app) fica no retorno pra o chamador decidir o que é banco."""
    full = f"{titulo} {texto}".strip()

    if _RE_ENVIADO.search(full):
        tipo, sep = "enviado", "para"
    elif _RE_RECEBIDO.search(full):
        tipo, sep = "recebido", "de"
    else:
        tipo, sep = None, None

    mv = _RE_VALOR.search(full)
    valor = _para_decimal(mv.group(1)) if mv else None

    # Contraparte: "de <nome>" (recebido) / "para <nome>" (enviado), **depois**
    # do valor (o 1º "de" costuma ser "transferência de R$..."). Pega o resto da
    # frase, sem pontuação final.
    contraparte = None
    if sep and mv:
        m = re.search(rf"\b{sep}\s+(.+)", full[mv.end():], re.IGNORECASE)
        if m:
            nome = re.split(r"[.!\n]", m.group(1))[0]
            contraparte = re.sub(r"\s+", " ", nome).strip(" -–·") or None

    return {
        "tipo": tipo,
        "valor": float(valor) if valor is not None else None,
        "contraparte": contraparte,
        "texto": full,
    }
