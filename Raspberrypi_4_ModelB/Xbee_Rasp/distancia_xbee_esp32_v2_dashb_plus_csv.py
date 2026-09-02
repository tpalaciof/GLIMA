import csv
import logging
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import serial
from tb_gateway_mqtt import TBDeviceMqttClient


# ************************* CONFIGURACIÓN ************************* #

# Puerto del adaptador USB donde está conectado el XBee.
PUERTO_XBEE = "/dev/ttyUSB0"
BAUDIOS = 9600

# Zona horaria de Medellín, Colombia.
# Se usa explícitamente para no depender de la configuración de la Raspberry.
ZONA_HORARIA = ZoneInfo("America/Bogota")

# Carpetas y nombre base de los archivos.
# Los TXT quedan sueltos en datos_sensores.
# Los CSV quedan dentro de datos_sensores/csv.
CARPETA_DATOS = "datos_sensores"
CARPETA_CSV = "csv"
NOMBRE_BASE_ARCHIVO = "mediciones_distancia"

# Cada cuánto se calcula la moda, se guarda una fila y se envía al dashboard.
FRECUENCIA_GUARDADO_SEGUNDOS = 30.0

# Cada cuánto se crea un archivo nuevo.
# Opciones: "hora", "diario", "mensual" o "unico".
FRECUENCIA_ARCHIVO = "hora"

DISTANCIA_MAXIMA_MM = 9998

# Configuración de ThingsBoard Cloud.
ACCESS_TOKEN = "P4YiIHsuZmtKuAGO0LGu"
THINGSBOARD_SERVER = "mqtt.thingsboard.cloud"

logging.basicConfig(level=logging.WARNING)


# ************************ VARIABLES GLOBALES ********************* #

puertoXBee = None
client = None
secuenciaAnterior = None

# Mediciones recibidas durante el intervalo actual de 30 segundos.
distanciasIntervaloMm = []
sinObjetivoEnIntervalo = False

tiempoGuardadoAnterior = 0.0

# Contadores acumulativos del archivo actual.
sufijoCalidadActual = None
valoresDistanciaTotalesArchivo = 0
valoresDistanciaCorrectosArchivo = 0

ENCABEZADOS_CSV = [
    "fecha",
    "hora",
    "distancia_moda_mm",
    "porcentaje_datos_correctos_distancia"
]

# Nombres y anchos utilizados únicamente en el archivo TXT.
COLUMNAS_VISUALES = [
    ("FECHA", 10, "<"),
    ("HORA", 8, "<"),
    ("DISTANCIA (mm)", 15, ">"),
    ("DIST. CORRECTA (%)", 19, ">")
]


# ***************************** XBEE ******************************* #

def abrirPuertoXBee():
    global puertoXBee

    puertoXBee = serial.Serial(
        port=PUERTO_XBEE,
        baudrate=BAUDIOS,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.250
    )


def configurarXBee():
    print()
    print("Iniciando comunicación con el XBee...")

    time.sleep(1)
    puertoXBee.reset_input_buffer()

    print("XBee listo")


def verificarSecuencia(secuencia):
    global secuenciaAnterior

    if secuenciaAnterior is None:
        secuenciaAnterior = secuencia
        return

    if secuencia == secuenciaAnterior:
        print(f"Aviso: se repitió la secuencia {secuencia}.")

    elif secuenciaAnterior == 0xFFFFFFFF and secuencia == 0:
        # Desbordamiento normal de una variable uint32_t.
        pass

    elif secuencia > secuenciaAnterior + 1:
        cantidadPerdida = secuencia - secuenciaAnterior - 1

        print(
            "Aviso: posiblemente se perdieron "
            f"{cantidadPerdida} mensaje(s)."
        )

    elif secuencia < secuenciaAnterior:
        print(
            "Aviso: la secuencia retrocedió. "
            "La ESP32 pudo haberse reiniciado."
        )

    secuenciaAnterior = secuencia


def recibirXBee():
    global sinObjetivoEnIntervalo

    while puertoXBee.in_waiting > 0:
        # La ESP32 termina cada mensaje con un salto de línea.
        # Ejemplo: D,79,527,0\n
        linea = puertoXBee.readline()
        linea = linea.decode("ascii", errors="replace").strip()

        if not linea:
            continue

        print()
        print(f"XBee -> Raspberry: {linea}")

        campos = linea.split(",")

        if len(campos) != 4:
            print("Mensaje XBee no válido: se esperaban cuatro campos.")
            continue

        if campos[0] != "D":
            print("Mensaje XBee no válido: el primer campo debe ser D.")
            continue

        try:
            secuencia = int(campos[1])
            distanciaMm = int(campos[2])
            estado = int(campos[3])

        except ValueError:
            print(
                "Mensaje XBee no válido: secuencia, distancia "
                "y estado deben ser números enteros."
            )
            continue

        if estado == 0 and 0 <= distanciaMm <= DISTANCIA_MAXIMA_MM:
            verificarSecuencia(secuencia)

            # Conserva todas las distancias válidas recibidas durante
            # el intervalo para calcular posteriormente la moda.
            distanciasIntervaloMm.append(distanciaMm)

            print(f"Secuencia: {secuencia}")
            print(
                f"Distancia: {distanciaMm} mm "
                f"({distanciaMm / 1000.0:.3f} m)"
            )

            if distanciaMm < 500:
                print(
                    "Aviso: está por debajo del rango "
                    "especificado del MB7388."
                )

        elif estado == 1 and distanciaMm == 9999:
            verificarSecuencia(secuencia)
            sinObjetivoEnIntervalo = True
            print(f"Secuencia: {secuencia}")
            print("MB7388: sin objetivo detectado.")

        elif estado == 2 and distanciaMm == -1:
            verificarSecuencia(secuencia)
            print(f"Secuencia: {secuencia}")
            print("MB7388: no se recibió una trama válida.")

        else:
            print(
                "Mensaje XBee no válido: la distancia "
                "no corresponde con el estado recibido."
            )


# *************************** THINGSBOARD ************************* #

def configurarThingsBoard():
    global client

    print()
    print("Conectando con ThingsBoard...")

    try:
        client = TBDeviceMqttClient(
            THINGSBOARD_SERVER,
            username=ACCESS_TOKEN
        )
        client.connect()
        print("ThingsBoard conectado")

    except Exception as error:
        # El registro local puede continuar aunque Internet no esté disponible.
        client = None
        print(f"Aviso: no fue posible conectar con ThingsBoard: {error}")


def enviarDatosThingsBoard(
    fechaHora,
    distanciaModaMm,
    porcentajeDistancia
):
    global client

    valores = {
        "distancia_moda_mm": distanciaModaMm,
        "porcentaje_datos_correctos_distancia": porcentajeDistancia
    }

    # Un valor inexistente no se envía como telemetría.
    valores = {
        nombre: valor
        for nombre, valor in valores.items()
        if valor is not None
    }

    if not valores:
        return

    # Si una conexión anterior falló, intenta recuperarla en el siguiente
    # intervalo de guardado sin detener el registro local.
    if client is None:
        configurarThingsBoard()

    if client is None:
        return

    telemetria = {
        "ts": int(fechaHora.timestamp() * 1000),
        "values": valores
    }

    try:
        client.send_telemetry(telemetria)

    except Exception as error:
        print(f"Aviso: no se pudo enviar la telemetría: {error}")

        try:
            client.disconnect()
        except Exception:
            pass

        client = None


def cerrarThingsBoard():
    if client is not None:
        try:
            client.disconnect()
        except Exception as error:
            print(f"Aviso al cerrar ThingsBoard: {error}")


# ************************ REGISTRO DE DATOS ********************** #

def calcularModaDistancia():
    if not distanciasIntervaloMm:
        # Si hubo respuestas 9999, pero ninguna distancia válida,
        # conserva la indicación de que no se detectó un objetivo.
        if sinObjetivoEnIntervalo:
            return 9999

        # No se recibió ninguna distancia válida durante el intervalo.
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


def obtenerRutaArchivo(fechaHora, extension):
    carpetaPrograma = Path(__file__).resolve().parent
    carpetaDatos = carpetaPrograma / CARPETA_DATOS
    carpetaDatos.mkdir(parents=True, exist_ok=True)

    sufijo = obtenerSufijoArchivo(fechaHora)

    if sufijo:
        nombreArchivo = f"{NOMBRE_BASE_ARCHIVO}_{sufijo}.{extension}"
    else:
        nombreArchivo = f"{NOMBRE_BASE_ARCHIVO}.{extension}"

    if extension == "csv":
        carpetaCsv = carpetaDatos / CARPETA_CSV
        carpetaCsv.mkdir(parents=True, exist_ok=True)
        return carpetaCsv / nombreArchivo

    return carpetaDatos / nombreArchivo


def esModaDistanciaValida(distanciaModaMm):
    return (
        isinstance(distanciaModaMm, (int, float))
        and 0 <= distanciaModaMm <= DISTANCIA_MAXIMA_MM
    )


def cargarContadoresCalidadDesdeCsv(rutaCsv):
    global valoresDistanciaTotalesArchivo
    global valoresDistanciaCorrectosArchivo

    if not rutaCsv.exists() or rutaCsv.stat().st_size == 0:
        return

    with rutaCsv.open("r", newline="", encoding="utf-8") as archivo:
        lector = csv.DictReader(archivo)

        if lector.fieldnames != ENCABEZADOS_CSV:
            raise ValueError(
                f"El encabezado de {rutaCsv.name} no corresponde "
                "al programa de distancia por XBee."
            )

        for fila in lector:
            valoresDistanciaTotalesArchivo += 1

            try:
                distancia = int(fila["distancia_moda_mm"])
            except (TypeError, ValueError):
                distancia = None

            if esModaDistanciaValida(distancia):
                valoresDistanciaCorrectosArchivo += 1


def prepararContadoresCalidad(fechaHora, rutaCsv):
    global sufijoCalidadActual
    global valoresDistanciaTotalesArchivo
    global valoresDistanciaCorrectosArchivo

    sufijoActual = obtenerSufijoArchivo(fechaHora)

    if sufijoActual == sufijoCalidadActual:
        return

    valoresDistanciaTotalesArchivo = 0
    valoresDistanciaCorrectosArchivo = 0

    cargarContadoresCalidadDesdeCsv(rutaCsv)
    sufijoCalidadActual = sufijoActual


def registrarCalidadFila(distanciaModaMm):
    global valoresDistanciaTotalesArchivo
    global valoresDistanciaCorrectosArchivo

    valoresDistanciaTotalesArchivo += 1

    if esModaDistanciaValida(distanciaModaMm):
        valoresDistanciaCorrectosArchivo += 1

    return round(
        valoresDistanciaCorrectosArchivo
        / valoresDistanciaTotalesArchivo
        * 100,
        2
    )


def formatearFilaVisual(valores):
    celdas = []

    for valor, (_, ancho, alineacion) in zip(valores, COLUMNAS_VISUALES):
        texto = str(valor)
        celdas.append(f"{texto:{alineacion}{ancho}}")

    return " | ".join(celdas)


def escribirEncabezadoTxt(rutaTxt):
    encabezado = " | ".join(
        titulo.center(ancho)
        for titulo, ancho, _ in COLUMNAS_VISUALES
    )
    separador = "-+-".join(
        "-" * ancho
        for _, ancho, _ in COLUMNAS_VISUALES
    )

    with rutaTxt.open("w", encoding="utf-8") as archivo:
        archivo.write(encabezado + "\n")
        archivo.write(separador + "\n")


def crearArchivoVisualDesdeCsv(rutaTxt, rutaCsv):
    escribirEncabezadoTxt(rutaTxt)

    with rutaCsv.open("r", newline="", encoding="utf-8") as archivoCsv:
        lector = csv.reader(archivoCsv)

        # Omite los encabezados del CSV.
        next(lector, None)

        with rutaTxt.open("a", encoding="utf-8") as archivoTxt:
            for fila in lector:
                archivoTxt.write(formatearFilaVisual(fila) + "\n")


def agregarFilaArchivoVisual(rutaTxt, fila):
    with rutaTxt.open("a", encoding="utf-8") as archivo:
        archivo.write(formatearFilaVisual(fila) + "\n")


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
    cantidadMuestrasValidas = len(distanciasIntervaloMm)

    prepararContadoresCalidad(fechaHora, rutaCsv)
    porcentajeDistancia = registrarCalidadFila(distanciaModaMm)

    archivoCsvNuevo = not rutaCsv.exists() or rutaCsv.stat().st_size == 0
    archivoTxtNuevo = not rutaTxt.exists() or rutaTxt.stat().st_size == 0

    filaDatos = [
        fechaHora.strftime("%Y-%m-%d"),
        fechaHora.strftime("%H:%M:%S"),
        "" if distanciaModaMm is None else distanciaModaMm,
        f"{porcentajeDistancia:.2f}"
    ]

    with rutaCsv.open("a", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)

        if archivoCsvNuevo:
            escritor.writerow(ENCABEZADOS_CSV)

        escritor.writerow(filaDatos)

    if archivoTxtNuevo:
        # Si el CSV ya tenía datos, también los recupera en el TXT nuevo.
        crearArchivoVisualDesdeCsv(rutaTxt, rutaCsv)
    else:
        agregarFilaArchivoVisual(rutaTxt, filaDatos)

    # Envía a ThingsBoard exactamente la medición que se acaba de guardar.
    enviarDatosThingsBoard(
        fechaHora,
        distanciaModaMm,
        porcentajeDistancia
    )

    print()
    print(
        f"Guardado: {fechaHora:%Y-%m-%d %H:%M:%S} | "
        f"moda de distancia: {distanciaModaMm} mm "
        f"({cantidadMuestrasValidas} muestras válidas) | "
        f"calidad de distancia: {porcentajeDistancia:.2f}% | "
        f"archivos: {rutaCsv.name} y {rutaTxt.name}"
    )

    # Inicia la recolección del siguiente intervalo.
    distanciasIntervaloMm.clear()
    sinObjetivoEnIntervalo = False


# ************************ PROGRAMA PRINCIPAL ********************* #

def main():
    global tiempoGuardadoAnterior

    try:
        abrirPuertoXBee()
        configurarXBee()
        configurarThingsBoard()

        print()
        print("Iniciando recepción y registro de distancia...")

        # La primera fila se guarda después de completar el primer intervalo.
        tiempoGuardadoAnterior = time.monotonic()

        while True:
            recibirXBee()
            guardarDatos()

            # Evita mantener innecesariamente ocupado el procesador.
            time.sleep(0.005)

    except KeyboardInterrupt:
        print("\nPrograma detenido.")

    except (serial.SerialException, OSError, ValueError) as error:
        print(f"\nError: {error}")

    finally:
        cerrarThingsBoard()

        if puertoXBee is not None and puertoXBee.is_open:
            puertoXBee.close()


if __name__ == "__main__":
    main()