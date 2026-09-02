import csv
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import serial



# ************************* CONFIGURACIÓN ************************* #

# Puertos de los adaptadores USB-UART CP2102.
PUERTO_RG15 = "/dev/ttyUSB0"
PUERTO_MB7388 = "/dev/ttyUSB1"
BAUDIOS = 9600

# Nombre de la carpeta y nombre base de los archivos.
# Ejemplo diario: datos_sensores/mediciones_2026-08-20.csv
CARPETA_DATOS = "datos_sensores"
NOMBRE_BASE_ARCHIVO = "mediciones"

# Cada cuánto se escribe una fila en el archivo.
FRECUENCIA_GUARDADO_SEGUNDOS = 30

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


def setupRG15():
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
        linea = puertoRG15.readline()
        linea = linea.decode("ascii", errors="replace").strip()

        if not linea:
            continue

        print(f"RG-15 -> Raspberry: {linea}")

        # El comando R también puede producir mensajes que no son mediciones.
        if not linea.startswith("Acc"):
            continue

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

def setupMB7388():
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
    if not distanciasIntervaloMm:
        # Si hubo respuestas 9999, pero ninguna distancia válida,
        # conserva la indicación de que no se detectó un objetivo.
        if sinObjetivoEnIntervalo:
            return 9999

        # No se recibió ninguna trama válida durante el intervalo.
        return None

    frecuencias = Counter(distanciasIntervaloMm)
    frecuenciaMaxima = max(frecuencias.values())

    modas = {
        distancia
        for distancia, frecuencia in frecuencias.items()
        if frecuencia == frecuenciaMaxima
    }

    # Si hay empate, selecciona la moda que apareció más recientemente.
    for distancia in reversed(distanciasIntervaloMm):
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


def obtenerRutaArchivo(fechaHora):
    carpetaPrograma = Path(__file__).resolve().parent
    carpetaDatos = carpetaPrograma / CARPETA_DATOS
    carpetaDatos.mkdir(parents=True, exist_ok=True)

    sufijo = obtenerSufijoArchivo(fechaHora)

    if sufijo:
        nombreArchivo = f"{NOMBRE_BASE_ARCHIVO}_{sufijo}.csv"
    else:
        nombreArchivo = f"{NOMBRE_BASE_ARCHIVO}.csv"

    return carpetaDatos / nombreArchivo


def guardarDatos():
    global sinObjetivoEnIntervalo, tiempoGuardadoAnterior

    tiempoActual = time.monotonic()

    if tiempoActual - tiempoGuardadoAnterior < FRECUENCIA_GUARDADO_SEGUNDOS:
        return

    tiempoGuardadoAnterior = tiempoActual
    fechaHora = datetime.now()
    rutaArchivo = obtenerRutaArchivo(fechaHora)
    distanciaModaMm = calcularModaDistancia()
    cantidadMuestrasDistancia = len(distanciasIntervaloMm)

    archivoNuevo = not rutaArchivo.exists() or rutaArchivo.stat().st_size == 0

    with rutaArchivo.open("a", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)

        if archivoNuevo:
            escritor.writerow([
                "fecha",
                "hora",
                "lluvia_adicional_mm",
                "lluvia_evento_mm",
                "lluvia_total_mm",
                "intensidad_lluvia_mm_h",
                "distancia_moda_mm"
            ])

        escritor.writerow([
            fechaHora.strftime("%Y-%m-%d"),
            fechaHora.strftime("%H:%M:%S"),
            "" if lluviaAdicionalMm is None else f"{lluviaAdicionalMm:.3f}",
            "" if lluviaEventoMm is None else f"{lluviaEventoMm:.3f}",
            "" if lluviaTotalMm is None else f"{lluviaTotalMm:.3f}",
            (
                ""
                if intensidadLluviaMmH is None
                else f"{intensidadLluviaMmH:.3f}"
            ),
            "" if distanciaModaMm is None else distanciaModaMm
        ])

    print(
        f"Guardado: {fechaHora:%Y-%m-%d %H:%M:%S} | "
        f"lluvia total: {lluviaTotalMm} mm | "
        f"moda de distancia: {distanciaModaMm} mm "
        f"({cantidadMuestrasDistancia} muestras válidas) | "
        f"archivo: {rutaArchivo.name}"
    )

    # Inicia la recolección de distancias del siguiente intervalo.
    distanciasIntervaloMm.clear()
    sinObjetivoEnIntervalo = False




# ************************ PROGRAMA PRINCIPAL ********************** #

def main():
    global tiempoGuardadoAnterior

    try:
        abrirPuertos()
        setupRG15()
        setupMB7388()

        print()
        print("Iniciando lectura y registro de los dos sensores...")

        # Permite que la primera fila se guarde inmediatamente.
        tiempoGuardadoAnterior = (
            time.monotonic() - FRECUENCIA_GUARDADO_SEGUNDOS
        )

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