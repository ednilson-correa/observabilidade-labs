#!/usr/bin/env python3
"""Mostra o tamanho e o formato dos checkpoints gravados pelo file_storage.

O file_storage usa um banco bbolt. Este script lê o formato do arquivo direto,
só com a biblioteca padrão, sem abrir o banco (o Collector mantém uma trava nele).

uso: checkpoint.py <arquivo-do-file_storage> [...]
"""
import struct
import sys


def paginas(dados):
    metas = []
    for inicio in (0, None):
        if inicio is None:
            # a segunda meta fica na página 1; o tamanho da página está na primeira
            inicio = struct.unpack_from("<I", dados, 16 + 8)[0]
        cab = dados[inicio + 16:inicio + 16 + 64]
        magic, _ver, tam, _flags, raiz, _seq, _free, _pgid, txid, _ck = struct.unpack("<IIIIQQQQQQ", cab)
        if magic == 0xED0CDAED:
            metas.append((txid, tam, raiz))
    _txid, tam, raiz = max(metas)
    return tam, raiz


def folhas(dados, tam, pg, base=None):
    """Percorre a árvore a partir da página pg (ou de uma página embutida em base)."""
    ini = base if base is not None else pg * tam
    _id, flags, qtd, _over = struct.unpack_from("<QHHI", dados, ini)
    for i in range(qtd):
        el = ini + 16 + i * 16
        if flags & 0x01:  # ramo
            pos, _ksize, filho = struct.unpack_from("<IIQ", dados, el)
            yield from folhas(dados, tam, filho)
        elif flags & 0x02:  # folha
            fl, pos, ksize, vsize = struct.unpack_from("<IIII", dados, el)
            k = dados[el + pos:el + pos + ksize]
            v_ini = el + pos + ksize
            yield fl, k, v_ini, vsize


def listar(caminho):
    dados = open(caminho, "rb").read()
    tam, raiz = paginas(dados)
    for fl, nome, v_ini, _vsize in folhas(dados, tam, raiz):
        if not fl & 0x01:
            continue
        raiz_balde = struct.unpack_from("<Q", dados, v_ini)[0]
        if raiz_balde == 0:  # balde embutido na própria folha
            itens = folhas(dados, tam, 0, base=v_ini + 16)
        else:
            itens = folhas(dados, tam, raiz_balde)
        for _f, chave, ini, vsize in itens:
            valor = dados[ini:ini + vsize]
            if b'"Fingerprint"' in valor:
                formato = "json"
            elif vsize < 16:
                formato = f"vazio ({valor!r})"
            else:
                formato = "protobuf"
            yield chave.decode(errors="replace"), vsize, formato


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arq in sys.argv[1:]:
        for chave, tamanho, formato in listar(arq):
            if "knownFiles" in chave:
                print(f"{arq}\t{chave}\t{tamanho} bytes\t{formato}")
