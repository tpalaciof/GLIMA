import time
from datetime import datetime
from zoneinfo import ZoneInfo

import serial


# ************************* CONFIGURACIÓN ************************* #

# Puerto del adaptador USB donde está conectado el XBee.
PUERTO_XBEE = "/dev/ttyUSB0"
BAUDIOS = 9600

# Zona horaria de Medellín, Colombia.
ZONA_HORARIA = ZoneInfo("America/Bogota")

DISTANCIA_MAXIMA_MM = 9998


# ************************ VARIABLES GLOBALES ********************* #

puertoXBee = None
secuenciaAnterior = None


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

        tipoMensaje = campos[0]

        if tipoMensaje != "D":
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

        fechaHora = datetime.now(ZONA_HORARIA)

        if estado == 0:
            if distanciaMm < 0 or distanciaMm > DISTANCIA_MAXIMA_MM:
                print(
                    "Mensaje XBee no válido: el estado 0 requiere "
                    "una distancia entre 0 y 9998 mm."
                )
                continue

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


# ************************ PROGRAMA PRINCIPAL ********************* #

def main():
    try:
        abrirPuertoXBee()
        configurarXBee()

        print()
        print("Iniciando recepción de datos de distancia...")

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