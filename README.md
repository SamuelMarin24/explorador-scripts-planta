# Explorador y Ejecutor de Scripts

Aplicación web en Flask que expone, para un equipo de trabajo, una carpeta compartida de la red como un explorador de archivos navegable desde el navegador, con la posibilidad de ejecutar scripts `.bat` en el servidor y ver su salida en vivo.

## El problema

Los scripts de automatización de un área vivían repartidos en carpetas de red: para correr uno, alguien tenía que conocer la ruta exacta, abrir una consola y ejecutarlo a mano, sin ver el resultado hasta que terminara. Además, cada informe o documento requería recorrer manualmente la estructura de carpetas para encontrarlo.

## La solución

Una única página web que:

- **Explora las carpetas configuradas** como un administrador de archivos, con vista rápida de texto, imágenes, PDF y una lista "plana" que junta archivos de varias subcarpetas en una sola vista.
- **Ejecuta los `.bat` desde el navegador**, mostrando la salida de consola en tiempo real, línea por línea, sin que el usuario necesite abrir una terminal.
- **Destaca procesos clave** como botones grandes en la portada, con su historial de ejecuciones.
- **Descarga o abre archivos** directamente, incluido "abrir en el servidor" para quien navega desde ese mismo equipo.

## Decisiones técnicas

- **Todo dentro de una carpeta permitida:** cada ruta que llega del navegador se resuelve con `os.path.commonpath()` contra la carpeta configurada. Si el resultado se sale de esa carpeta —por ejemplo con `../../`— la petición se rechaza con 403. Nadie puede navegar fuera de lo que el administrador definió.
- **Solo se puede ejecutar lo que está explícitamente permitido:** una carpeta debe tener `"ejecutar": True` en la configuración, y el archivo debe terminar en `.bat` o `.cmd`. Cualquier otra extensión se rechaza antes de tocar el sistema operativo.
- **Unidades de red vs. rutas UNC:** un `.bat` que hace `cd /d %~dp0` se rompe si `%~dp0` es una ruta `\\servidor\carpeta`, porque Windows no puede posicionar la consola ahí directamente. La app resuelve esto detectando qué letra de unidad tiene mapeado el sistema hacia ese recurso (`net use`) y llama al script por esa letra en lugar de por la ruta UNC completa.
- **Lanzador temporal en vez de un comando largo:** en lugar de pasarle a `cmd` una instrucción con comillas anidadas (que Windows termina reescapando mal), la app escribe un `.bat` temporal de tres líneas y lo ejecuta. Es más robusto que armar la línea de comando a mano.
- **Salida en vivo:** el proceso se lanza con la salida como pipe y se va leyendo línea por línea en un hilo, guardándola en memoria; el navegador la consulta por polling. Un temporizador aparte cancela el proceso si se pasa del tiempo máximo configurado.
- **Todo por configuración:** qué carpetas se muestran, qué extensiones, si se puede ejecutar, qué procesos aparecen destacados — todo sale de `config.py`, sin tocar la lógica de la aplicación.

## Consideración de seguridad

Esta aplicación **no tiene autenticación** y puede ejecutar código en el servidor donde corre. Está pensada para desplegarse únicamente en una red interna de confianza (por ejemplo, la red de una planta u oficina), nunca expuesta a internet. Si se va a usar en un entorno donde eso no se puede garantizar, hay que agregarle una capa de autenticación antes de desplegarla.

## Stack

Python 3.10+ · Flask · JavaScript (vanilla, sin framework) · HTML/CSS

## Estructura

```
explorador-scripts-planta/
├── app.py                      # Rutas, exploración de archivos y ejecución de scripts
├── config.py                   # Carpetas, procesos destacados y parámetros
├── templates/
│   └── index.html              # Interfaz: una sola página, sin build ni dependencias JS
├── iniciar_web_analitica.bat   # Arranque en Windows
├── requirements.txt
├── .env.example
└── .gitignore
```

## Cómo usarlo

1. Instalar dependencias:
   ```bash
   pip install -r requirements.txt
   ```
2. Copiar `.env.example` como `.env` y apuntar `AREA` a tu carpeta compartida.
3. Ajustar `CARPETAS` y, si aplica, `SCRIPTS` en `config.py` según tu estructura de carpetas.
4. Ejecutar `python app.py` (o doble clic en `iniciar_web_analitica.bat`).

La app queda escuchando en el puerto configurado, accesible desde cualquier equipo de la misma red.

> Por confidencialidad, este repositorio no incluye rutas de red reales, el nombre de ninguna empresa ni el registro de ejecuciones (que contiene IPs y nombres de scripts internos).
