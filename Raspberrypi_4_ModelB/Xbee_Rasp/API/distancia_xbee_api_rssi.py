import time
from datetime import datetime
from zoneinfo import ZoneInfo

import serial


# ************************* CONFIGURACIÓN ************************* #

# Puerto del adaptador USB donde está conectado el XBee receptor.
PUERTO_XBEE = "/dev/ttyUSB0"
BAUDIOS = 9600

# Este programa requiere en el XBee conectado a la Raspberry:
# AP = 1  -> modo API sin escapes
# AO = 0  -> los datos recibidos salen en tramas 0x90

# El XBee conectado a la ESP32 puede continuar en modo transparente:
# AP = 0

# Zona horaria de Medellín, Colombia.
ZONA_HORARIA = ZoneInfo("America/Bogota")

DISTANCIA_MAXIMA_MM = 9998

# Protección frente a una longitud corrupta recibida por la UART.
LONGITUD_MAXIMA_TRAMA_API = 2048

# Si el XBee no responde al comando DB dentro de este tiempo,
# el mensaje se procesa sin RSSI para no perder la medición.
TIEMPO_MAXIMO_RESPUESTA_DB_S = 1.0


# ************************ VARIABLES GLOBALES ********************* #

puertoXBee = None
secuenciaAnterior = None

# Los identificadores API válidos para solicitar una respuesta son
# 1 a 255. El identificador 0 desactiva la respuesta.
identificadorApi = 0

# Relaciona la respuesta 0x88 del comando DB con la trama 0x90
# que produjo la consulta.
paquetesPendientesRssi = {}


# ***************************** XBEE ******************************* #

def abrirPuertoXBee():
    global puertoXBee

    puertoXBee = serial.Serial(
        port=PUERTO_XBEE,
        baudrate=BAUDIOS,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.100
    )


def configurarXBee():
    print()
    print("Iniciando comunicación con el XBee...")
    print("Configuración requerida: AP = 1 y AO = 0")

    time.sleep(1)
    puertoXBee.reset_input_buffer()

    print("XBee listo")


def calcularChecksum(datosTrama):
    """
    Calcula el checksum API.

    No se incluyen el delimitador 0x7E ni los dos bytes de longitud.
    La suma de datosTrama y checksum debe terminar en 0xFF.
    """

    return 0xFF - (sum(datosTrama) & 0xFF)


def construirTramaApi(datosTrama):
    longitud = len(datosTrama)

    return bytes([
        0x7E,
        (longitud >> 8) & 0xFF,
        longitud & 0xFF
    ]) + datosTrama + bytes([calcularChecksum(datosTrama)])


def obtenerIdentificadorApi():
    global identificadorApi

    identificadorApi += 1

    if identificadorApi > 255:
        identificadorApi = 1

    return identificadorApi


def leerExactamente(cantidadBytes, tiempoMaximoS=0.500):
    datos = bytearray()
    tiempoLimite = time.monotonic() + tiempoMaximoS

    while len(datos) < cantidadBytes:
        bloque = puertoXBee.read(cantidadBytes - len(datos))

        if bloque:
            datos.extend(bloque)
            continue

        if time.monotonic() >= tiempoLimite:
            return None

    return bytes(datos)


def leerTramaApi():
    """
    Busca el delimitador 0x7E y devuelve únicamente los datos de
    una trama API válida. Devuelve None si todavía no hay una trama.
    """

    while puertoXBee.in_waiting > 0:
        inicio = puertoXBee.read(1)

        if inicio != b"\x7E":
            print(
                "Aviso: byte descartado mientras se buscaba "
                "el inicio 0x7E."
            )
            continue

        bytesLongitud = leerExactamente(2)

        if bytesLongitud is None:
            print("Trama API incompleta: no se recibió la longitud.")
            return None

        longitud = int.from_bytes(bytesLongitud, byteorder="big")

        if longitud == 0 or longitud > LONGITUD_MAXIMA_TRAMA_API:
            print(f"Longitud de trama API no válida: {longitud}.")
            continue

        datosYChecksum = leerExactamente(longitud + 1)

        if datosYChecksum is None:
            print("Trama API incompleta: faltan datos o checksum.")
            return None

        datosTrama = datosYChecksum[:-1]
        checksumRecibido = datosYChecksum[-1]

        if ((sum(datosTrama) + checksumRecibido) & 0xFF) != 0xFF:
            print("Trama API descartada por checksum incorrecto.")
            continue

        return datosTrama

    return None


def solicitarRssiUltimoPaquete(paqueteRecibido):
    """
    Envía una trama 0x08 con el comando local AT DB.

    Trama sin escapes:
    7E 00 04 08 ID 44 42 CHECKSUM
    """

    identificador = obtenerIdentificadorApi()

    # 0x08: Local AT Command Request
    # 0x44 0x42: caracteres ASCII D y B
    datosTrama = bytes([
        0x08,
        identificador,
        ord("D"),
        ord("B")
    ])

    paquetesPendientesRssi[identificador] = paqueteRecibido

    puertoXBee.write(construirTramaApi(datosTrama))
    puertoXBee.flush()


# *********************** MENSAJE DE DISTANCIA ******************* #

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


def procesarLineaDistancia(
        linea,
        fechaHora,
        direccionOrigen,
        opcionesRecepcion,
        rssiDbm):

    print()
    print(f"XBee de origen: {direccionOrigen}")
    print(f"Opciones de recepción: 0x{opcionesRecepcion:02X}")

    if rssiDbm is None:
        print("RSSI: no disponible")
    else:
        print(f"RSSI: {rssiDbm} dBm")

    print(f"XBee -> Raspberry: {linea}")

    campos = linea.split(",")

    if len(campos) != 4:
        print("Mensaje XBee no válido: se esperaban cuatro campos.")
        return

    tipoMensaje = campos[0]

    if tipoMensaje != "D":
        print("Mensaje XBee no válido: el primer campo debe ser D.")
        return

    try:
        secuencia = int(campos[1])
        distanciaMm = int(campos[2])
        estado = int(campos[3])

    except ValueError:
        print(
            "Mensaje XBee no válido: secuencia, distancia "
            "y estado deben ser números enteros."
        )
        return

    if estado == 0:
        if distanciaMm < 0 or distanciaMm > DISTANCIA_MAXIMA_MM:
            print(
                "Mensaje XBee no válido: el estado 0 requiere "
                "una distancia entre 0 y 9998 mm."
            )
            return

        verificarSecuencia(secuencia)

        print(f"Fecha y hora: {fechaHora:%Y-%m-%d %H:%M:%S}")
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

        print(f"Fecha y hora: {fechaHora:%Y-%m-%d %H:%M:%S}")
        print(f"Secuencia: {secuencia}")
        print("MB7388: sin objetivo detectado.")

    elif estado == 2 and distanciaMm == -1:
        verificarSecuencia(secuencia)

        print(f"Fecha y hora: {fechaHora:%Y-%m-%d %H:%M:%S}")
        print(f"Secuencia: {secuencia}")
        print("MB7388: no se recibió una trama válida.")

    else:
        print(
            "Mensaje XBee no válido: la distancia "
            "no corresponde con el estado recibido."
        )


def procesarPaqueteConRssi(paqueteRecibido, rssiDbm):
    datosRf = paqueteRecibido["datosRf"]
    fechaHora = paqueteRecibido["fechaHora"]
    direccionOrigen = paqueteRecibido["direccionOrigen"]
    opcionesRecepcion = paqueteRecibido["opcionesRecepcion"]

    texto = datosRf.decode("ascii", errors="replace")
    lineas = texto.splitlines()

    if not lineas and texto:
        lineas = [texto]

    if not lineas:
        print("Paquete 0x90 recibido sin datos RF.")
        return

    # Normalmente cada paquete contiene una sola línea. Si el XBee
    # agrupa varias, todas pertenecen al mismo paquete RF y RSSI.
    for linea in lineas:
        linea = linea.strip()

        if linea:
            procesarLineaDistancia(
                linea,
                fechaHora,
                direccionOrigen,
                opcionesRecepcion,
                rssiDbm
            )


# ************************** TRAMAS API *************************** #

def procesarTramaRecepcion90(datosTrama):
    """
    Estructura de datosTrama para 0x90:

    [0]       Tipo 0x90
    [1:9]     Dirección de origen de 64 bits
    [9:11]    Campo reservado
    [11]      Opciones de recepción
    [12:]     Datos RF
    """

    if len(datosTrama) < 12:
        print("Trama 0x90 demasiado corta.")
        return

    direccionOrigen = datosTrama[1:9].hex().upper()
    opcionesRecepcion = datosTrama[11]
    datosRf = datosTrama[12:]

    paqueteRecibido = {
        "fechaHora": datetime.now(ZONA_HORARIA),
        "tiempoRecepcion": time.monotonic(),
        "direccionOrigen": direccionOrigen,
        "opcionesRecepcion": opcionesRecepcion,
        "datosRf": datosRf
    }

    # DB se consulta inmediatamente después de recibir el 0x90.
    solicitarRssiUltimoPaquete(paqueteRecibido)


def procesarRespuestaAt88(datosTrama):
    """
    Estructura de datosTrama para 0x88:

    [0]       Tipo 0x88
    [1]       Identificador de trama
    [2:4]     Comando AT
    [4]       Estado
    [5:]      Valor devuelto
    """

    if len(datosTrama) < 5:
        print("Trama 0x88 demasiado corta.")
        return

    identificador = datosTrama[1]
    comando = datosTrama[2:4]
    estadoComando = datosTrama[4]
    valor = datosTrama[5:]

    if comando != b"DB":
        print(
            "Respuesta 0x88 recibida para otro comando AT: "
            f"{comando.decode('ascii', errors='replace')}"
        )
        return

    paqueteRecibido = paquetesPendientesRssi.pop(
        identificador,
        None
    )

    if paqueteRecibido is None:
        print(
            "Respuesta AT DB sin una trama 0x90 pendiente "
            f"para el identificador {identificador}."
        )
        return

    if estadoComando != 0x00:
        print(
            "El XBee rechazó el comando AT DB. "
            f"Estado: 0x{estadoComando:02X}."
        )
        procesarPaqueteConRssi(paqueteRecibido, None)
        return

    if len(valor) != 1:
        print(
            "La respuesta AT DB no contiene exactamente "
            "un byte de RSSI."
        )
        procesarPaqueteConRssi(paqueteRecibido, None)
        return

    rssiAbsoluto = valor[0]

    # DB = 0 indica que el XBee se reinició y todavía no había
    # recibido un paquete cuando se consultó el parámetro.
    if rssiAbsoluto == 0:
        print("El parámetro DB devolvió 0: RSSI no disponible.")
        procesarPaqueteConRssi(paqueteRecibido, None)
        return

    rssiDbm = -rssiAbsoluto

    procesarPaqueteConRssi(paqueteRecibido, rssiDbm)


def procesarTramaApi(datosTrama):
    tipoTrama = datosTrama[0]

    if tipoTrama == 0x90:
        procesarTramaRecepcion90(datosTrama)

    elif tipoTrama == 0x88:
        procesarRespuestaAt88(datosTrama)

    elif tipoTrama == 0x8A:
        if len(datosTrama) >= 2:
            print(
                "Estado del módem XBee recibido: "
                f"0x{datosTrama[1]:02X}"
            )

    else:
        print(f"Trama API 0x{tipoTrama:02X} no procesada.")


def procesarConsultasDbVencidas():
    tiempoActual = time.monotonic()
    identificadoresVencidos = []

    for identificador, paquete in paquetesPendientesRssi.items():
        tiempoEspera = tiempoActual - paquete["tiempoRecepcion"]

        if tiempoEspera >= TIEMPO_MAXIMO_RESPUESTA_DB_S:
            identificadoresVencidos.append(identificador)

    for identificador in identificadoresVencidos:
        paquete = paquetesPendientesRssi.pop(identificador)

        print(
            "No llegó la respuesta 0x88 del comando DB para "
            f"el identificador {identificador}."
        )

        procesarPaqueteConRssi(paquete, None)


def recibirXBee():
    while True:
        datosTrama = leerTramaApi()

        if datosTrama is None:
            break

        procesarTramaApi(datosTrama)

    procesarConsultasDbVencidas()


# ************************ PROGRAMA PRINCIPAL ********************* #

def main():
    try:
        abrirPuertoXBee()
        configurarXBee()

        print()
        print("Iniciando recepción API de datos de distancia...")

        while True:
            recibirXBee()

            # Evita mantener innecesariamente ocupado el procesador.
            time.sleep(0.005)

    except KeyboardInterrupt:
        print("\nPrograma detenido.")

    except (serial.SerialException, OSError, ValueError) as error:
        print(f"\nError: {error}")

    finally:
        if puertoXBee is not None and puertoXBee.is_open:
            puertoXBee.close()


if __name__ == "__main__":
    main()
