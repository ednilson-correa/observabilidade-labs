#!/usr/bin/env python3
"""Roda as consultas de um dashboard LEGADO de processos (hostmetrics) contra
os três modos do lab e diz o que continua funcionando, o que fica sem dados e
o que "funciona" mas perde o agrupamento (o pior caso: quebra silenciosa).

Uso:  python3 scripts/verificar.py            (Prometheus em localhost:9090)
      PROMETHEUS_URL=http://host:9090 python3 scripts/verificar.py --json
Só biblioteca padrão.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

PROM = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
MODOS = ["legado", "transicao", "rc"]
SEL = 'job="hostmetrics-{modo}", process_executable_name="carga"'

# (nome, consulta legada, label de agrupamento ou None, consulta equivalente RC)
CONSULTAS = [
    ("CPU por modo", 'sum by (state) (rate(process_cpu_time_seconds_total{%s}[1m]))', "state",
     'sum by (cpu_mode) (rate(process_cpu_time_seconds_total{%s}[1m]))'),
    ("Utilização de CPU", 'sum by (state) (process_cpu_utilization_ratio{%s})', "state",
     'sum by (cpu_mode) (process_cpu_utilization_ratio{%s})'),
    ("Alerta de iowait", 'sum(rate(process_cpu_time_seconds_total{%s, state="wait"}[1m]))', None,
     'sum(rate(process_cpu_time_seconds_total{%s, cpu_mode="iowait"}[1m]))'),
    ("Threads", 'max(process_threads{%s})', None,
     'max(process_thread_count{%s})'),
    ("File descriptors", 'max(process_open_file_descriptors{%s})', None,
     'max(process_unix_file_descriptor_count{%s})'),
    ("I/O de disco", 'sum by (direction) (rate(process_disk_io_bytes_total{%s}[1m]))', "direction",
     'sum by (disk_io_direction) (rate(process_disk_io_bytes_total{%s}[1m]))'),
    ("Trocas de contexto", 'sum by (type) (rate(process_context_switches_total{%s}[1m]))', "type",
     'sum by (process_context_switch_type) (rate(process_context_switches_total{%s}[1m]))'),
    ("Page faults", 'sum by (type) (rate(process_paging_faults_total{%s}[1m]))', "type",
     'sum by (system_paging_fault_type) (rate(process_paging_faults_total{%s}[1m]))'),
    ("Memória (RSS)", 'max(process_memory_usage_bytes{%s})', None,
     'max(process_memory_usage_bytes{%s})'),
]


def consulta(expr):
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=10) as r:
        dados = json.load(r)
    if dados.get("status") != "success":
        raise RuntimeError(f"erro na consulta {expr}: {dados}")
    return dados["data"]["result"]


def avalia(expr, label):
    res = consulta(expr)
    if not res:
        return "SEM DADOS"
    if label and any(not s["metric"].get(label) for s in res):
        return "SILENCIOSO"  # retorna número, mas somou tudo numa série só
    return "OK"


def nomes(modo):
    res = consulta('count by (__name__) ({job="hostmetrics-%s", __name__=~"process_.*"})' % modo)
    return sorted(s["metric"]["__name__"] for s in res)


def series(modo):
    res = consulta('count({job="hostmetrics-%s", __name__=~"process_.*"})' % modo)
    return int(float(res[0]["value"][1])) if res else 0


def main():
    resultado = {"modos": {}, "consultas": []}
    for modo in MODOS:
        resultado["modos"][modo] = {"metricas": nomes(modo), "series": series(modo)}
    for nome, legada, label, nova in CONSULTAS:
        linha = {"painel": nome, "legada": {}, "nova": {}}
        for modo in MODOS:
            sel = SEL.format(modo=modo)
            linha["legada"][modo] = avalia(legada % sel, label)
            linha["nova"][modo] = avalia(nova % sel, label and nova.split("by (")[1].split(")")[0])
        resultado["consultas"].append(linha)

    resumo = {}
    for modo in MODOS:
        estados = [c["legada"][modo] for c in resultado["consultas"]]
        resumo[modo] = {e: estados.count(e) for e in ("OK", "SEM DADOS", "SILENCIOSO")}
    resultado["resumo_legadas"] = resumo

    if "--json" in sys.argv:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
        return

    print(f"Prometheus: {PROM}\n")
    print(f"{'modo':<10} {'nomes process_*':>16} {'séries':>8}")
    for modo in MODOS:
        m = resultado["modos"][modo]
        print(f"{modo:<10} {len(m['metricas']):>16} {m['series']:>8}")
    print("\nConsultas do dashboard LEGADO (state / direction / type / process_threads ...)")
    print(f"{'painel':<20} " + " ".join(f"{m:>11}" for m in MODOS))
    for c in resultado["consultas"]:
        print(f"{c['painel']:<20} " + " ".join(f"{c['legada'][m]:>11}" for m in MODOS))
    print("\nConsultas NOVAS (cpu_mode / disk_io_direction / process_thread_count ...)")
    for c in resultado["consultas"]:
        print(f"{c['painel']:<20} " + " ".join(f"{c['nova'][m]:>11}" for m in MODOS))
    print("\nResumo das consultas legadas:")
    for modo, r in resumo.items():
        print(f"  {modo:<10} OK={r['OK']}  SEM DADOS={r['SEM DADOS']}  SILENCIOSO={r['SILENCIOSO']}")
    if not any("process_disk_io_bytes_total" in m["metricas"] for m in resultado["modos"].values()):
        print("\nAviso: process.disk.io não chegou em nenhum modo. O kernel provavelmente não tem")
        print("/proc/<pid>/io (é o caso do WSL2). Confira com: cat /proc/self/io")


if __name__ == "__main__":
    main()
