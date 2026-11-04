#!/usr/bin/env python3
"""Gera grafana/dashboards/lab-filelog-checkpoint.json. Rodar só ao mudar o dashboard."""
import json
import pathlib

DS = {"type": "prometheus", "uid": "prometheus"}
CORES = {"json-0.163.1": "#f0643c", "protobuf-0.163.1": "#6e8cff", "protobuf-0.164.0": "#3ddc97"}
J, P, N = '{instancia="json-0.163.1"}', '{instancia="protobuf-0.163.1"}', '{instancia="protobuf-0.164.0"}'
JAN = "[5m]"
CPU = "rate(otelcol_process_cpu_seconds{sel}" + JAN + ")"
ALOC = "rate(otelcol_process_runtime_total_alloc_bytes{sel}" + JAN + ")"
_id = 0


def prox():
    global _id
    _id += 1
    return _id


def sobrepoe():
    return [{"matcher": {"id": "byName", "options": n},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]}
            for n, c in CORES.items()]


def alvo(expr, legenda="{{instancia}}", ref="A", instant=False):
    return {"datasource": DS, "refId": ref, "expr": expr, "legendFormat": legenda, "instant": instant, "range": not instant}


def linha(titulo, y):
    return {"id": prox(), "type": "row", "title": titulo, "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []}


def stat(titulo, desc, expr, unidade, x, y, w=6, cor="#6e8cff", dec=1):
    return {"id": prox(), "type": "stat", "title": titulo, "description": desc, "datasource": DS,
            "gridPos": {"h": 5, "w": w, "x": x, "y": y},
            "targets": [alvo(expr, legenda="", instant=True)],
            "options": {"colorMode": "background", "graphMode": "none", "justifyMode": "center", "textMode": "value",
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            "fieldConfig": {"defaults": {"unit": unidade, "decimals": dec,
                                         "color": {"mode": "fixed", "fixedColor": cor}},
                            "overrides": []}}


def serie(titulo, desc, expr, unidade, x, y, w=12, h=9):
    return {"id": prox(), "type": "timeseries", "title": titulo, "description": desc, "datasource": DS,
            "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "targets": [alvo(expr)],
            "options": {"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "lastNotNull"]},
                        "tooltip": {"mode": "multi", "sort": "desc"}},
            "fieldConfig": {"defaults": {"unit": unidade, "min": 0, "custom": {"lineWidth": 2, "fillOpacity": 8, "showPoints": "never"}},
                            "overrides": sobrepoe()}}


def barra(titulo, desc, expr, unidade, x, y, w=12, h=7):
    return {"id": prox(), "type": "bargauge", "title": titulo, "description": desc, "datasource": DS,
            "gridPos": {"h": h, "w": w, "x": x, "y": y},
            "targets": [alvo(expr, instant=True)],
            "options": {"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True,
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
            "fieldConfig": {"defaults": {"unit": unidade, "min": 0, "color": {"mode": "fixed", "fixedColor": "#6e8cff"}},
                            "overrides": sobrepoe()}}


painel = [
    linha("Resultado: JSON x protobuf com a mesma carga", 0),
    stat("Redução de CPU", "Quanto menos CPU a instância protobuf usa em relação à JSON, mesma versão do Collector.",
         f"1 - {CPU.format(sel=P)} / ignoring(instancia, instance) {CPU.format(sel=J)}", "percentunit", 0, 1, cor="#f0643c"),
    stat("Redução de memória alocada", "Bytes alocados por segundo: protobuf em relação a JSON, mesma versão.",
         f"1 - {ALOC.format(sel=P)} / ignoring(instancia, instance) {ALOC.format(sel=J)}", "percentunit", 6, 1, cor="#f0643c"),
    stat("CPU JSON", "Núcleos usados pela instância JSON (0.163.1, gate desligada).", CPU.format(sel=J), "cores", 12, 1, w=4, cor="#f0643c", dec=3),
    stat("CPU protobuf 0.163.1", "Núcleos usados pela instância protobuf na 0.163.1.", CPU.format(sel=P), "cores", 16, 1, w=4, dec=3),
    stat("CPU protobuf 0.164.0", "Núcleos usados pela instância na 0.164.0.", CPU.format(sel=N), "cores", 20, 1, w=4, cor="#3ddc97", dec=3),
    linha("Custo do Collector ao longo do tempo", 6),
    serie("CPU por instância", "rate() de 5 min do CPU do processo. A coleta é a mesma: a diferença vem do checkpoint.",
          "rate(otelcol_process_cpu_seconds" + JAN + ")", "cores", 0, 7),
    serie("Memória alocada por segundo", "Pressão no garbage collector. Cada checkpoint aloca a cada poll.",
          "rate(otelcol_process_runtime_total_alloc_bytes" + JAN + ")", "Bps", 12, 7),
    serie("RSS", "Memória residente de cada processo.", "otelcol_process_memory_rss", "bytes", 0, 16),
    serie("Heap em uso", "Heap Go alocado no momento da leitura.", "otelcol_process_runtime_heap_alloc_bytes", "bytes", 12, 16),
    linha("Prova de que a carga é igual", 25),
    barra("Linhas de log aceitas", "As três instâncias precisam aceitar o mesmo volume. Se divergir, a comparação não vale.",
          "otelcol_receiver_accepted_log_records", "short", 0, 26),
    serie("Linhas de log aceitas por segundo", "Vazão de cada instância.",
          "rate(otelcol_receiver_accepted_log_records" + JAN + ")", "short", 12, 26, h=7),
]

dash = {"uid": "lab-filelog-checkpoint", "title": "Lab: filelog com checkpoint JSON x protobuf", "tags": ["labs", "opentelemetry", "filelog"],
        "description": "Três Collectors lendo os mesmos arquivos. Compara o custo do checkpoint JSON e do protobuf.",
        "schemaVersion": 41, "version": 1, "editable": True, "style": "dark", "refresh": "10s", "graphTooltip": 1,
        "time": {"from": "now-30m", "to": "now"}, "timezone": "browser", "templating": {"list": []}, "annotations": {"list": []},
        "panels": painel}
destino = pathlib.Path(__file__).parent.parent / "grafana/dashboards/lab-filelog-checkpoint.json"
destino.write_text(json.dumps(dash, indent=2, ensure_ascii=False) + "\n")
