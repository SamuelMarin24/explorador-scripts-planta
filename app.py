import os
import re
import uuid
import time
import tempfile
import mimetypes
import threading
import subprocess
from datetime import datetime
from collections import deque

from flask import Flask, jsonify, request, render_template, send_file, abort

import config

app = Flask(__name__)

SCRIPTS = {s["id"]: s for s in config.SCRIPTS}
TAREAS = {}
HISTORIAL = deque(maxlen=config.MAX_HISTORIAL)
LOCK = threading.Lock()
EXT_EJECUTABLES = (".bat", ".cmd")
LOCALES = ("127.0.0.1", "::1", "localhost")

# Cómo se previsualiza cada tipo dentro de la ventana emergente
VISTA_TEXTO = ("txt", "log", "csv", "md", "json", "py", "bat", "cmd", "sql", "ini")
VISTA_IMAGEN = ("png", "jpg", "jpeg", "gif", "webp", "bmp")
VISTA_MARCO = ("pdf",)          # el navegador lo dibuja solo
VISTA_POWERBI = ("pbix",)


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def es_local():
    return request.remote_addr in LOCALES


def carpeta_cfg(raiz):
    """Acepta tanto "Nombre": r"ruta" como "Nombre": {"ruta": ..., ...}."""
    c = config.CARPETAS.get(raiz)
    if c is None:
        abort(404, "Carpeta no configurada")
    if isinstance(c, str):
        c = {"ruta": c}
    return {"ruta": c["ruta"], "mostrar": [e.lower().lstrip(".") for e in c.get("mostrar", [])],
            "plano": bool(c.get("plano")), "ejecutar": bool(c.get("ejecutar"))}


def extension(nombre):
    return nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""


def tipo_vista(nombre):
    e = extension(nombre)
    if e in VISTA_POWERBI:
        return "powerbi"
    if e in VISTA_IMAGEN:
        return "imagen"
    if e in VISTA_MARCO:
        return "marco"
    if e in VISTA_TEXTO:
        return "texto"
    return None


def decodificar(linea: bytes) -> str:
    try:
        return linea.decode("utf-8")
    except UnicodeDecodeError:
        return linea.decode("cp850", errors="replace")


def sin_ventana():
    """Para que el .bat corra oculto, sin consola en pantalla."""
    opciones = {"creationflags": 0}
    if os.name != "nt":
        return opciones
    opciones["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    opciones["startupinfo"] = si
    return opciones


_MAPEOS = {"cuando": 0, "datos": []}


def unidades_mapeadas():
    """Lee las unidades de red del usuario, por ejemplo Z: hacia el servidor."""
    if time.time() - _MAPEOS["cuando"] < 60:
        return _MAPEOS["datos"]
    datos = []
    if os.name == "nt":
        try:
            r = subprocess.run(["net", "use"], capture_output=True, timeout=10, **sin_ventana())
            texto = decodificar(r.stdout)
            for linea in texto.splitlines():
                m = re.search(r"([A-Za-z]:)\s+(\\\\[^\s]+)", linea)
                if m:
                    datos.append((m.group(1), m.group(2).rstrip("\\")))
        except Exception:
            pass
    datos.sort(key=lambda x: -len(x[1]))
    _MAPEOS.update({"cuando": time.time(), "datos": datos})
    return datos


def ruta_ejecutable(ruta):
    """Si la ruta es de red y hay una letra mapeada a ese recurso, la usa.
    cmd trabaja mucho mejor con una letra de unidad que con una ruta UNC."""
    if not ruta.startswith("\\\\"):
        return ruta
    bajo = ruta.lower()
    for letra, unc in unidades_mapeadas():
        u = unc.lower()
        if bajo.startswith(u + "\\") or bajo == u:
            return letra + ruta[len(unc):]
    return ruta


def registrar_log(texto):
    try:
        with open(config.ARCHIVO_LOG, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except OSError:
        pass


# ------------------------------------------------------------
#  Ejecución de .bat
# ------------------------------------------------------------
def matar(proceso, tarea):
    tarea["estado"] = "tiempo_agotado"
    tarea["salida"].append("[web] Tiempo máximo alcanzado, se canceló el proceso.")
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proceso.pid)],
                   capture_output=True, **sin_ventana())


def correr(tid):
    t = TAREAS[tid]
    ruta = t["ruta"]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    vigilante = None
    try:
        # pushd le monta una letra de unidad temporal a la carpeta de red y se
        # para ahí; luego se llama al .bat SOLO POR SU NOMBRE. Así, dentro del
        # .bat, %~dp0 queda como una letra (X:\...) y su "cd /d %~dp0" funciona.
        # Si se llamara por la ruta UNC completa, %~dp0 sería \\servidor\... y
        # cmd respondería "La ruta de acceso especificada no es válida".
        # Se escribe un lanzador temporal en vez de mandarle a cmd una orden
        # larga con comillas: al pasar la orden como argumento, Windows
        # reescapa las comillas y la ruta llega partida ("el nombre de
        # directorio no es correcto"). Con un .bat propio eso no ocurre.
        carpeta, archivo = os.path.split(ruta_ejecutable(ruta))
        entrar = "pushd" if carpeta.startswith("\\\\") else "cd /d"
        lanzador = os.path.join(tempfile.gettempdir(), f"lanzar_{tid}.bat")
        cod = "mbcs" if os.name == "nt" else "utf-8"
        with open(lanzador, "w", encoding=cod, errors="replace", newline="") as f:
            f.write("@echo off\r\n")
            f.write(f'{entrar} "{carpeta}"\r\n')
            f.write("if errorlevel 1 exit /b 9009\r\n")
            f.write(f'call "{archivo}"\r\n')
            f.write("exit /b %ERRORLEVEL%\r\n")
        t["lanzador"] = lanzador
        p = subprocess.Popen(
            ["cmd", "/c", lanzador],
            cwd=tempfile.gettempdir(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, **sin_ventana(),
        )
        try:
            if t["entrada"]:
                p.stdin.write(t["entrada"].encode("cp850"))
            p.stdin.close()
        except OSError:
            pass

        vigilante = threading.Timer(t["tiempo_maximo"], matar, args=(p, t))
        vigilante.start()

        for linea in iter(p.stdout.readline, b""):
            t["salida"].append(decodificar(linea).rstrip("\r\n"))
            if len(t["salida"]) > config.MAX_LINEAS_SALIDA:
                del t["salida"][0]
        p.wait()
        t["codigo"] = p.returncode
        if p.returncode == 9009:
            t["salida"].append("[web] No se pudo entrar a la carpeta del proceso:")
            t["salida"].append(f"      {os.path.dirname(ruta_ejecutable(ruta))}")
            m = unidades_mapeadas()
            t["salida"].append("      Unidades de red vistas por la app: "
                               + (", ".join(f"{l} = {u}" for l, u in m) if m else "ninguna"))
            t["salida"].append("      Prueba la misma ruta en una consola para ver el detalle.")
        if t["estado"] == "corriendo":
            t["estado"] = "ok" if p.returncode == 0 else "error"
    except Exception as e:
        t["salida"].append(f"[web] No se pudo ejecutar: {e}")
        t["estado"] = "error"
    finally:
        if vigilante:
            vigilante.cancel()
        try:
            if t.get("lanzador"):
                os.remove(t["lanzador"])
        except OSError:
            pass
        t["fin"] = ahora()
        HISTORIAL.appendleft(resumen(t))
        registrar_log(f'{t["fin"]}\t{t["ip"]}\t{t["nombre"]}\t{t["estado"]}\t{t.get("codigo")}')


def resumen(t):
    return {k: t.get(k) for k in ("id", "script", "nombre", "estado", "inicio", "fin", "codigo", "ip")}


def lanzar(script_id, nombre, ruta, entrada="", tiempo=None):
    with LOCK:
        for t in TAREAS.values():
            if t["script"] == script_id and t["estado"] == "corriendo":
                return None, "Ese proceso ya se está ejecutando. Abre su consola para ver cómo va."
        if not os.path.isfile(ruta):
            return None, f"No se encontró el archivo: {ruta}"
        tid = uuid.uuid4().hex[:10]
        TAREAS[tid] = {
            "id": tid, "script": script_id, "nombre": nombre, "ruta": ruta,
            "entrada": entrada, "tiempo_maximo": tiempo or config.TIEMPO_MAXIMO,
            "estado": "corriendo", "inicio": ahora(), "fin": None, "codigo": None,
            "salida": [], "ip": request.remote_addr,
        }
    threading.Thread(target=correr, args=(tid,), daemon=True).start()
    return tid, None


# ------------------------------------------------------------
#  Rutas seguras (nadie se sale de las carpetas configuradas)
# ------------------------------------------------------------
def resolver(raiz, sub=""):
    cfg = carpeta_cfg(raiz)
    base_abs = os.path.abspath(cfg["ruta"])
    destino = os.path.abspath(os.path.join(base_abs, sub or ""))
    try:
        comun = os.path.commonpath([base_abs, destino])
    except ValueError:
        abort(403)
    if os.path.normcase(comun) != os.path.normcase(base_abs):
        abort(403)
    return cfg, base_abs, destino


def ficha(entrada, rel):
    st = entrada.stat()
    return {"nombre": entrada.name, "carpeta": entrada.is_dir(),
            "ruta": rel.replace("\\", "/"),
            "subcarpeta": os.path.dirname(rel).replace("\\", "/"),
            "tamano": None if entrada.is_dir() else st.st_size,
            "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "vista": None if entrada.is_dir() else tipo_vista(entrada.name),
            "bat": (not entrada.is_dir()) and entrada.name.lower().endswith(EXT_EJECUTABLES)}


def carpeta_tiene(destino, mostrar, nivel=0):
    """True si la carpeta (o alguna subcarpeta) tiene archivos del tipo pedido.
    Sirve para no mostrar carpetas que al entrar aparecerían vacías."""
    if not mostrar or nivel > config.PROFUNDIDAD_PLANO:
        return True
    try:
        with os.scandir(destino) as it:
            subs = []
            for e in it:
                if e.name.startswith((".", "~$")) or e.name == "__pycache__":
                    continue
                if e.is_dir():
                    subs.append(e.path)
                elif extension(e.name) in mostrar:
                    return True
        return any(carpeta_tiene(s, mostrar, nivel + 1) for s in subs)
    except OSError:
        return False


def listar_plano(base, mostrar):
    """Junta los archivos de todas las subcarpetas en una sola lista."""
    items = []
    for raiz_dir, dirs, archivos in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith((".", "~$", "__pycache__"))]
        nivel = raiz_dir[len(base):].count(os.sep)
        if nivel >= config.PROFUNDIDAD_PLANO:
            dirs[:] = []
        for nombre in archivos:
            if nombre.startswith(("~$", ".")):
                continue
            if mostrar and extension(nombre) not in mostrar:
                continue
            try:
                with os.scandir(raiz_dir) as it:
                    pass
                completo = os.path.join(raiz_dir, nombre)
                st = os.stat(completo)
            except OSError:
                continue
            rel = os.path.relpath(completo, base)
            items.append({"nombre": nombre, "carpeta": False,
                          "ruta": rel.replace("\\", "/"),
                          "subcarpeta": os.path.dirname(rel).replace("\\", "/"),
                          "tamano": st.st_size,
                          "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                          "vista": tipo_vista(nombre),
                          "bat": nombre.lower().endswith(EXT_EJECUTABLES)})
            if len(items) >= config.MAX_ARCHIVOS_PLANO:
                return items
    return items


# ------------------------------------------------------------
#  Endpoints
# ------------------------------------------------------------
@app.route("/")
def inicio():
    return render_template("index.html", area=config.NOMBRE_AREA)


@app.route("/api/config")
def api_config():
    carpetas = []
    for nombre in config.CARPETAS:
        c = carpeta_cfg(nombre)
        carpetas.append({"nombre": nombre, "plano": c["plano"], "ejecutar": c["ejecutar"]})
    return jsonify({"carpetas": carpetas,
                    "abrir": config.PERMITIR_ABRIR_EN_SERVIDOR and es_local()})


@app.route("/api/scripts")
def api_scripts():
    datos = []
    for s in config.SCRIPTS:
        ultima = next((h for h in HISTORIAL if h["script"] == s["id"]), None)
        corriendo = next((t["id"] for t in TAREAS.values()
                          if t["script"] == s["id"] and t["estado"] == "corriendo"), None)
        datos.append({"id": s["id"], "nombre": s["nombre"],
                      "descripcion": s.get("descripcion", ""),
                      "existe": os.path.isfile(s["ruta"]),
                      "ultima": ultima, "corriendo": corriendo})
    return jsonify(datos)


@app.route("/api/ejecutar/<script_id>", methods=["POST"])
def api_ejecutar(script_id):
    s = SCRIPTS.get(script_id)
    if not s:
        return jsonify({"error": "Proceso no configurado."}), 404
    tid, err = lanzar(s["id"], s["nombre"], s["ruta"], s.get("entrada", ""), s.get("tiempo_maximo"))
    if err:
        return jsonify({"error": err}), 409
    return jsonify({"tarea": tid})


@app.route("/api/ejecutar_archivo", methods=["POST"])
def api_ejecutar_archivo():
    d = request.get_json(force=True)
    cfg, _, destino = resolver(d.get("raiz"), d.get("ruta"))
    if not cfg["ejecutar"]:
        return jsonify({"error": "Esta carpeta no tiene habilitada la ejecución."}), 403
    if not destino.lower().endswith(EXT_EJECUTABLES):
        return jsonify({"error": "Solo se pueden ejecutar archivos .bat o .cmd"}), 400
    # Respuestas que el usuario escribió en la página para el menú del .bat.
    # Van al stdin del proceso: no pueden lanzar otro comando.
    entrada = str(d.get("entrada") or "")[:500]
    if entrada and not entrada.endswith("\n"):
        entrada += "\n"
    tid, err = lanzar("archivo:" + os.path.normcase(destino), os.path.basename(destino),
                      destino, entrada)
    if err:
        return jsonify({"error": err}), 409
    return jsonify({"tarea": tid})


@app.route("/api/tarea/<tid>")
def api_tarea(tid):
    t = TAREAS.get(tid)
    if not t:
        return jsonify({"error": "No existe"}), 404
    desde = request.args.get("desde", 0, type=int)
    return jsonify({**resumen(t), "salida": t["salida"][desde:], "total": len(t["salida"])})


@app.route("/api/historial")
def api_historial():
    return jsonify(list(HISTORIAL))


@app.route("/api/explorar")
def api_explorar():
    raiz = request.args.get("raiz")
    cfg, base, destino = resolver(raiz, request.args.get("ruta", ""))
    if not os.path.isdir(destino):
        return jsonify({"error": f"No hay acceso a la carpeta: {cfg['ruta']}"}), 404

    if cfg["plano"]:
        items = listar_plano(base, cfg["mostrar"])
        items.sort(key=lambda x: (x["subcarpeta"].lower(), x["nombre"].lower()))
        return jsonify({"raiz": raiz, "ruta": "", "plano": True,
                        "ejecutar": cfg["ejecutar"], "ruta_completa": base, "items": items})

    items = []
    try:
        with os.scandir(destino) as it:
            for e in it:
                if e.name.startswith(("~$", ".")) or e.name == "__pycache__":
                    continue
                if e.is_dir():
                    if config.OCULTAR_CARPETAS_VACIAS and not carpeta_tiene(e.path, cfg["mostrar"]):
                        continue
                elif cfg["mostrar"] and extension(e.name) not in cfg["mostrar"]:
                    continue
                try:
                    rel = os.path.relpath(e.path, base)
                    items.append(ficha(e, rel))
                except OSError:
                    continue
    except PermissionError:
        return jsonify({"error": "Sin permiso para leer esta carpeta."}), 403
    items.sort(key=lambda x: (not x["carpeta"], x["nombre"].lower()))
    rel = os.path.relpath(destino, base)
    return jsonify({"raiz": raiz, "ruta": "" if rel == "." else rel.replace("\\", "/"),
                    "plano": False, "ejecutar": cfg["ejecutar"],
                    "ruta_completa": destino, "items": items})


@app.route("/api/descargar")
def api_descargar():
    _, _, destino = resolver(request.args.get("raiz"), request.args.get("ruta"))
    if not os.path.isfile(destino):
        abort(404)
    adjunto = request.args.get("inline") != "1"
    tipo = mimetypes.guess_type(destino)[0] or "application/octet-stream"
    return send_file(destino, as_attachment=adjunto, mimetype=tipo)


@app.route("/api/vista")
def api_vista():
    """Datos para la ventana emergente."""
    raiz, ruta = request.args.get("raiz"), request.args.get("ruta")
    _, _, destino = resolver(raiz, ruta)
    if not os.path.isfile(destino):
        return jsonify({"error": "El archivo ya no está."}), 404
    nombre = os.path.basename(destino)
    st = os.stat(destino)
    datos = {"nombre": nombre, "tipo": tipo_vista(nombre), "tamano": st.st_size,
             "modificado": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
             "ruta_completa": destino, "contenido": None, "url_bi": None}

    if datos["tipo"] == "powerbi":
        datos["url_bi"] = getattr(config, "INFORMES_POWER_BI", {}).get(nombre)
    elif datos["tipo"] == "texto":
        if st.st_size > config.MAX_MB_VISTA * 1024 * 1024:
            datos["contenido"] = "[El archivo es muy grande para mostrarlo aquí. Descárgalo.]"
        else:
            try:
                with open(destino, "rb") as f:
                    datos["contenido"] = decodificar(f.read(400_000))
            except OSError as e:
                datos["contenido"] = f"[No se pudo leer: {e}]"
    return jsonify(datos)


@app.route("/api/abrir", methods=["POST"])
def api_abrir():
    if not (config.PERMITIR_ABRIR_EN_SERVIDOR and es_local()):
        abort(403)
    d = request.get_json(force=True)
    _, _, destino = resolver(d.get("raiz"), d.get("ruta"))
    try:
        os.startfile(destino)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PUERTO, threaded=True)
