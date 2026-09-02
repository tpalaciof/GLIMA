import csv
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import serial


# ************************* CONFIGURACIÓN ************************* #

# Puertos de los adaptadores USB-UART CP2102.
PUERTO_RG15 = "/dev/ttyUSB0"
PUERTO_MB7388 = "/dev/ttyUSB1"
BAUDIOS = 9600

# Zona horaria de Medellín, Colombia.
# Se usa explícitamente para no depender de la configuración de la Raspberry.
ZONA_HORARIA = ZoneInfo("America/Bogota")

# Carpetas y nombre base de los archivos.
# Los TXT quedan sueltos en datos_sensores.
# Los CSV quedan dentro de datos_sensores/csv.
CARPETA_DATOS = "datos_sensores"
CARPETA_CSV = "csv"
NOMBRE_BASE_ARCHIVO = "mediciones"

# Cada cuánto se escribe una fila en el archivo.
FRECUENCIA_GUARDADO_SEGUNDOS = 30.0

# Cada cuánto se crea un archivo nuevo.
# Opciones: "hora", "diario", "mensual" o "unico".
FRECUENCIA_ARCHIVO = "hora"

# El RG-15 se consulta cada 200 ms, igual que en el programa original.
FRECUENCIA_CONSULTA_RG15_MS = 60000

DISTANCIA_MAXIMA_MM = 9998


# ************************ VARIABLES GLOBALES ********************** #

puertoRG15 = None
puertoMB7388 = None

distanciasIntervaloMm = []  
sinObjetivoEnIntervalo = False
lluviaAdicionalMm = None
lluviaEventoMm = None
lluviaTotalMm = None
intensidadLluviaMmH = None

tiempoConsultaAnteriorMs = 0
tiempoGuardadoAnterior = 0.0

# Separa los cuatro valores de la respuesta del RG-15:
# Acc 0.00 mm, EventAcc 0.00 mm, TotalAcc 0.00 mm, RInt 0.00 mmph
PATRON_LLUVIA = re.compile(
    r"^Acc\s+([0-9]+(?:\.[0-9]+)?)\s+mm,\s*"
    r"EventAcc\s+([0-9]+(?:\.[0-9]+)?)\s+mm,\s*"
    r"TotalAcc\s+([0-9]+(?:\.[0-9]+)?)\s+mm,\s*"
    r"RInt\s+([0-9]+(?:\.[0-9]+)?)\s+mmph\b"
)

# Nombres y anchos utilizados únicamente en el archivo TXT de visualización.
COLUMNAS_VISUALES = [
    ("FECHA", 10, "<"),
    ("HORA", 8, "<"),
    ("ACC (mm)", 10, ">"),
    ("EVENTO (mm)", 11, ">"),
    ("TOTAL (mm)", 10, ">"),
    ("INTENSIDAD (mm/h)", 18, ">"),
    ("DISTANCIA (mm)", 15, ">")
]


# ************************* FUNCIONES COMUNES ********************** #

def millis():
    return int(time.monotonic() * 1000)


def abrirPuertos():
    global puertoRG15, puertoMB7388

    puertoRG15 = serial.Serial(
        port=PUERTO_RG15,
        baudrate=BAUDIOS,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.250
    )

    puertoMB7388 = serial.Serial(
        port=PUERTO_MB7388,
        baudrate=BAUDIOS,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.250
    )


# ***************************** RG-15 ******************************* #

def enviarComandoRG15(comando):
    puertoRG15.write((comando + "\n").encode("ascii"))
    print(f"Raspberry -> RG-15: {comando}")


def configurarRG15():
    print()
    print("Iniciando comunicacion con el RG-15...")

    time.sleep(1)

    # M: unidades metricas.
    # H: resolucion alta.
    # P: modo de consulta; el sensor responde cuando recibe R.
    enviarComandoRG15("M")
    time.sleep(0.1)

    enviarComandoRG15("H")
    time.sleep(0.1)

    enviarComandoRG15("P")
    time.sleep(0.1)

    puertoRG15.reset_input_buffer()
    print("RG-15 listo")


def consultarRG15():
    global tiempoConsultaAnteriorMs

    tiempoActualMs = millis()

    if tiempoActualMs - tiempoConsultaAnteriorMs >= FRECUENCIA_CONSULTA_RG15_MS:
        tiempoConsultaAnteriorMs = tiempoActualMs
        enviarComandoRG15("R")


def recibirRG15():
    global lluviaAdicionalMm
    global lluviaEventoMm
    global lluviaTotalMm
    global intensidadLluviaMmH

    while puertoRG15.in_waiting > 0:
        linea = puertoRG15.readline() #extrae bytes del puerto hasta encontrar el carácter de fin de línea \n
        linea = linea.decode("ascii", errors="replace").strip()

        if not linea: #Una cadena vacía se considera falsa. En ese caso, continue regresa directamente al comienzo del while, sin intentar procesarla.
            continue #Abandone esta repetición del while y vuelva a comenzar con la siguiente repetición

        print(f"RG-15 -> Raspberry: {linea}")

        # El comando R también puede producir mensajes que no son mediciones.
        if not linea.startswith("Acc"): #Esta condición comprueba si la línea comienza exactamente con: Acc
            continue #Abandone esta repetición del while y vuelva a comenzar con la siguiente repetición

        coincidencia = PATRON_LLUVIA.search(linea)

        if coincidencia is None:
            print("Respuesta de medición no válida del RG-15.")
            continue

        # Cada respuesta nueva actualiza directamente los cuatro valores.
        # TotalAcc es el acumulado mantenido por el propio RG-15.
        lluviaAdicionalMm = float(coincidencia.group(1))
        lluviaEventoMm = float(coincidencia.group(2))
        lluviaTotalMm = float(coincidencia.group(3))
        intensidadLluviaMmH = float(coincidencia.group(4))


# **************************** MB7388 ******************************* #

def configurarMB7388():
    print()
    print("Iniciando comunicacion con el MB7388...")

    time.sleep(1)
    puertoMB7388.reset_input_buffer()

    print("MB7388 listo")


def recibirMB7388():
    global sinObjetivoEnIntervalo

    while puertoMB7388.in_waiting > 0:
        # El sensor transmite R + cuatro dígitos + retorno de carro.
        # Ejemplo: R1234\r
        trama = puertoMB7388.read_until(b"\r")
        trama = trama.decode("ascii", errors="replace").strip()

        if len(trama) != 5 or trama[0] != "R" or not trama[1:].isdigit():
            print(f"Trama no válida del MB7388: {trama!r}")
            continue

        distanciaMm = int(trama[1:])

        if distanciaMm == 9999:
            sinObjetivoEnIntervalo = True
            print(f"MB7388: {trama} -> sin objetivo detectado")

        elif distanciaMm <= DISTANCIA_MAXIMA_MM:
            # Conserva todas las distancias válidas recibidas durante
            # el intervalo de 30 segundos.
            distanciasIntervaloMm.append(distanciaMm)

            print(
                f"MB7388: {trama} -> distancia: "
                f"{distanciaMm} mm ({distanciaMm / 1000.0:.3f} m)"
            )

            if distanciaMm < 500:
                print(
                    "Aviso: está por debajo del rango "
                    "especificado del MB7388."
                )


# ************************ REGISTRO DE DATOS *********************** #

def calcularModaDistancia():
    if not distanciasIntervaloMm: #será True cuando no haya ninguna distancia válida almacenada.
        # Si hubo respuestas 9999, pero ninguna distancia válida,
        # conserva la indicación de que no se detectó un objetivo.
        if sinObjetivoEnIntervalo:
            return 9999

        # No se recibió ninguna trama válida durante el intervalo.
        return None

    frecuencias = Counter(distanciasIntervaloMm) #Contar cuántas veces aparece cada distancia
    frecuenciaMaxima = max(frecuencias.values()) #frecuencias.values() =[3, 2, 1]

    modas = {
        distancia
        for distancia, frecuencia in frecuencias.items() #frecuencias.items() = (500, 3), (501, 2), (502, 1)
        if frecuencia == frecuenciaMaxima # como la frecuencia máxima es 3, solo se queda con la distancia 500
    }

    # Si hay empate, selecciona la moda que apareció más recientemente.
    for distancia in reversed(distanciasIntervaloMm): #reversed() recorre la lista desde el final hacia el principio, sin modificar la lista original.
        if distancia in modas:
            return distancia


def obtenerSufijoArchivo(fechaHora):
    if FRECUENCIA_ARCHIVO == "hora":
        return fechaHora.strftime("%Y-%m-%d_%H")

    if FRECUENCIA_ARCHIVO == "diario":
        return fechaHora.strftime("%Y-%m-%d")

    if FRECUENCIA_ARCHIVO == "mensual":
        return fechaHora.strftime("%Y-%m")

    if FRECUENCIA_ARCHIVO == "unico":
        return ""

    raise ValueError(
        "FRECUENCIA_ARCHIVO debe ser: "
        "'hora', 'diario', 'mensual' o 'unico'."
    )


def obtenerRutaArchivo(fechaHora, extension):
    carpetaPrograma = Path(__file__).resolve().parent #__file__ contiene la ruta del archivo de Python que se está ejecutando.
    carpetaDatos = carpetaPrograma / CARPETA_DATOS    #.resolve() Convierte la ruta en una ruta absoluta y resuelve elementos especiales.
    carpetaDatos.mkdir(parents=True, exist_ok=True)   # .parent devuelve el directorio padre de la ruta. mkdir() crea el directorio si no existe, y exist_ok=True evita errores si ya existe.

    sufijo = obtenerSufijoArchivo(fechaHora)

    if sufijo:
        nombreArchivo = f"{NOMBRE_BASE_ARCHIVO}_{sufijo}.{extension}"
    else:
        nombreArchivo = f"{NOMBRE_BASE_ARCHIVO}.{extension}"

    if extension == "csv":
        carpetaCsv = carpetaDatos / CARPETA_CSV
        carpetaCsv.mkdir(parents=True, exist_ok=True)

        # Reorganiza los CSV antiguos que todavía estén sueltos.
        for rutaAnterior in carpetaDatos.glob("*.csv"):  #glob("*.csv") busca todos los archivos que estén directamente dentro de datos_sensores; y terminen en .csv.
            rutaNueva = carpetaCsv / rutaAnterior.name

            if not rutaNueva.exists():
                rutaAnterior.rename(rutaNueva)

        return carpetaCsv / nombreArchivo

    return carpetaDatos / nombreArchivo


def formatearFilaVisual(valores):
    celdas = []

    for valor, (_, ancho, alineacion) in zip(valores, COLUMNAS_VISUALES):
        texto = str(valor)
        celdas.append(f"{texto:{alineacion}{ancho}}")

    return " | ".join(celdas)


def crearArchivoVisualDesdeCsv(rutaTxt, rutaCsv):
    encabezado = " | ".join(
        titulo.center(ancho)
        for titulo, ancho, _ in COLUMNAS_VISUALES
    )
    separador = "-+-".join(
        "-" * ancho
        for _, ancho, _ in COLUMNAS_VISUALES
    )

    with rutaTxt.open("w", encoding="utf-8") as archivoTxt:
        archivoTxt.write(encabezado + "\n")
        archivoTxt.write(separador + "\n")

        with rutaCsv.open("r", newline="", encoding="utf-8") as archivoCsv:
            lector = csv.reader(archivoCsv)

            # Omite los encabezados del CSV.
            next(lector, None)

            for fila in lector:
                archivoTxt.write(formatearFilaVisual(fila) + "\n")


def agregarFilaArchivoVisual(rutaTxt, fila):
    with rutaTxt.open("a", encoding="utf-8") as archivoTxt:
        archivoTxt.write(formatearFilaVisual(fila) + "\n")


def guardarDatos():
    global sinObjetivoEnIntervalo, tiempoGuardadoAnterior

    tiempoActual = time.monotonic()

    if tiempoActual - tiempoGuardadoAnterior < FRECUENCIA_GUARDADO_SEGUNDOS:
        return

    tiempoGuardadoAnterior = tiempoActual
    fechaHora = datetime.now(ZONA_HORARIA)
    rutaCsv = obtenerRutaArchivo(fechaHora, "csv")
    rutaTxt = obtenerRutaArchivo(fechaHora, "txt")
    distanciaModaMm = calcularModaDistancia()
    cantidadMuestrasDistancia = len(distanciasIntervaloMm)

    archivoCsvNuevo = not rutaCsv.exists() or rutaCsv.stat().st_size == 0
    archivoTxtNuevo = not rutaTxt.exists() or rutaTxt.stat().st_size == 0

    filaDatos = [
        fechaHora.strftime("%Y-%m-%d"),
        fechaHora.strftime("%H:%M:%S"),
        "" if lluviaAdicionalMm is None else f"{lluviaAdicionalMm:.3f}",
        "" if lluviaEventoMm is None else f"{lluviaEventoMm:.3f}",
        "" if lluviaTotalMm is None else f"{lluviaTotalMm:.3f}",
        (
        "" if intensidadLluviaMmH is None else f"{intensidadLluviaMmH:.3f}"),
        "" if distanciaModaMm is None else distanciaModaMm
    ]

    with rutaCsv.open("a", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)

        if archivoCsvNuevo:
            escritor.writerow([
                "fecha",
                "hora",
                "lluvia_adicional_mm",
                "lluvia_evento_mm",
                "lluvia_total_mm",
                "intensidad_lluvia_mm_h",
                "distancia_moda_mm"
            ])

        escritor.writerow(filaDatos)

    if archivoTxtNuevo:
        # Si el CSV ya tenía datos anteriores, también los lleva al TXT.
        crearArchivoVisualDesdeCsv(rutaTxt, rutaCsv)
    else:
        agregarFilaArchivoVisual(rutaTxt, filaDatos)

    print(
        f"Guardado: {fechaHora:%Y-%m-%d %H:%M:%S} | "
        f"lluvia total: {lluviaTotalMm} mm | "
        f"moda de distancia: {distanciaModaMm} mm "
        f"({cantidadMuestrasDistancia} muestras válidas) | "
        f"archivos: {rutaCsv.name} y {rutaTxt.name}"
    )

    # Inicia la recolección de distancias del siguiente intervalo.
    distanciasIntervaloMm.clear()
    sinObjetivoEnIntervalo = False


# ************************ PROGRAMA PRINCIPAL ********************** #

def main():
    global tiempoGuardadoAnterior

    try:
        abrirPuertos()
        configurarRG15()
        configurarMB7388()

        print()
        print("Iniciando lectura y registro de los dos sensores...")

        # La primera fila se guarda después de completar el primer intervalo.
        tiempoGuardadoAnterior = time.monotonic()

        while True:
            recibirRG15()
            recibirMB7388()
            consultarRG15()
            guardarDatos()

            # Evita mantener innecesariamente ocupado el procesador.
            time.sleep(0.005)

    except KeyboardInterrupt:
        print("\nPrograma detenido.")

    except (serial.SerialException, OSError, ValueError) as error:
        print(f"\nError: {error}")

    finally:
        if puertoRG15 is not None and puertoRG15.is_open:
            puertoRG15.close()

        if puertoMB7388 is not None and puertoMB7388.is_open:
            puertoMB7388.close()


if __name__ == "__main__":
    main()