"""Carga sintética para o lab: CPU (user + system), threads, arquivos abertos,
I/O de disco, trocas de contexto e page faults. Só biblioteca padrão.

O processo roda com o nome "carga" (o compose copia o binário do Python),
que é o filtro usado no hostmetrics/process.
"""
import math
import mmap
import os
import tempfile
import threading
import time

THREADS = int(os.environ.get("THREADS", "6"))
DIR = tempfile.mkdtemp(prefix="carga-")
inicio = time.time()


def intensidade() -> float:
    # Onda lenta (período de 5 min) para os gráficos não ficarem retos
    return 0.35 + 0.25 * math.sin((time.time() - inicio) / 300 * 2 * math.pi)


def cpu_user():
    while True:
        fim = time.time() + 0.1 * intensidade()
        x = 0
        while time.time() < fim:
            x += 1
        time.sleep(0.1 * (1 - intensidade()))


def disco_e_syscalls(n: int):
    caminho = os.path.join(DIR, f"arq-{n}.bin")
    bloco = os.urandom(64 * 1024)
    while True:
        with open(caminho, "wb") as f:  # escrita + fsync = I/O e CPU de sistema
            for _ in range(int(8 * intensidade()) + 1):
                f.write(bloco)
            f.flush()
            os.fsync(f.fileno())
        with open(caminho, "rb") as f:
            while f.read(64 * 1024):
                pass
        time.sleep(0.2)


def memoria():
    # Mapeia memória anônima nova e toca cada página: gera page faults (minor).
    # (mmap direto, porque o malloc reaproveitaria a memória e não haveria faults)
    while True:
        tamanho = int(32 * 1024 * 1024 * intensidade()) // mmap.PAGESIZE * mmap.PAGESIZE
        m = mmap.mmap(-1, tamanho)
        for i in range(0, tamanho, mmap.PAGESIZE):
            m[i] = 1
        m.close()
        time.sleep(1)


# Alguns arquivos ficam abertos de propósito (file descriptors)
abertos = [open(os.path.join(DIR, f"fd-{i}.txt"), "w") for i in range(20)]

alvos = [cpu_user, memoria] + [lambda n=n: disco_e_syscalls(n) for n in range(THREADS - 2)]
for alvo in alvos:
    threading.Thread(target=alvo, daemon=True).start()

print(f"carga rodando: pid={os.getpid()} threads={len(alvos)} dir={DIR}", flush=True)
while True:
    time.sleep(3600)
