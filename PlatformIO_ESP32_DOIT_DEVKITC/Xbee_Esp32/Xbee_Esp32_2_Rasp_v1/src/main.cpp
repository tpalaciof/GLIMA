#include <Arduino.h>

//******************************** PINES **********************************//

// MB7388: TX del sensor -> GPIO16 del ESP32
const int PIN_RX_SENSOR_DIS = 16;
HardwareSerial puertoSensor_dis(2);

// XBee: DOUT -> GPIO26 y DIN <- GPIO27
const int PIN_RX_XBEE = 26;
const int PIN_TX_XBEE = 27;
HardwareSerial puertoXBee(1);

//***************************** CONFIGURACIÓN *****************************//

// Durante las pruebas se envía cada 2 segundos.
// Posteriormente puede cambiarse a 30000.
const unsigned long FRECUENCIA_ENVIO_MS = 2000;

const int DISTANCIA_MAXIMA_MM = 9998;

//******************************* VARIABLES ******************************//

unsigned long tiempoAnteriorEnvio = 0;

String bufferMB7388 = "";

int ultimaDistanciaMm = -1;

// Indica si llegó por lo menos una trama R#### válida
// desde el envío anterior.
bool huboTramaValidaIntervalo = false;

uint32_t secuenciaXBee = 0;

//******************************* FUNCIONES ******************************//

//---------------------------------------------------------------------
// Validar trama MB7388
//---------------------------------------------------------------------

bool tramaValidaMB7388(const String &trama)
{
  // Formato esperado: R1234

  if (trama.length() != 5 || trama[0] != 'R')
  {
    return false;
  }

  for (int i = 1; i < 5; i++)
  {
    if (!isDigit(trama[i]))
    {
      return false;
    }
  }

  return true;
}

//---------------------------------------------------------------------
// Procesar una trama completa del MB7388
//---------------------------------------------------------------------

void procesarTramaMB7388(String trama)
{
  trama.trim();

  if (!tramaValidaMB7388(trama))
  {
    Serial.print("MB7388: trama no valida -> ");
    Serial.println(trama);
    return;
  }

  ultimaDistanciaMm = trama.substring(1).toInt();

  // También R9999 es una trama correctamente formada,
  // aunque signifique que no se detectó un objetivo.
  huboTramaValidaIntervalo = true;
}

//---------------------------------------------------------------------
// Recibir continuamente los caracteres del MB7388
//---------------------------------------------------------------------

void recibirMB7388()
{
  while (puertoSensor_dis.available())
  {
    char caracter = puertoSensor_dis.read();

    // El MB7388 termina cada trama con retorno de carro.
    if (caracter == '\r')
    {
      if (bufferMB7388.length() > 0)
      {
        procesarTramaMB7388(bufferMB7388);
        bufferMB7388 = "";
      }
    }
    else if (caracter != '\n')
    {
      // Una trama normal tiene solo cinco caracteres.
      // Se permite un pequeño margen para evitar
      // crecimiento indefinido si llegan datos corruptos.
      if (bufferMB7388.length() < 10)
      {
        bufferMB7388 += caracter;
      }
      else
      {
        Serial.println(
            "MB7388: buffer descartado por longitud excesiva");

        bufferMB7388 = "";
      }
    }
  }
}

//---------------------------------------------------------------------
// Enviar la última medición por XBee
//---------------------------------------------------------------------

void enviarDistanciaXBee()
{
  int distanciaEnviar;
  int estado;

  /*
      Estado 0: distancia válida entre 0 y 9998 mm.
      Estado 1: el sensor respondió R9999.
      Estado 2: no llegó ninguna trama R#### válida.
  */

  if (!huboTramaValidaIntervalo)
  {
    distanciaEnviar = -1;
    estado = 2;
  }
  else if (ultimaDistanciaMm == 9999)
  {
    distanciaEnviar = 9999;
    estado = 1;
  }
  else if (
      ultimaDistanciaMm >= 0 &&
      ultimaDistanciaMm <= DISTANCIA_MAXIMA_MM)
  {
    distanciaEnviar = ultimaDistanciaMm;
    estado = 0;
  }
  else
  {
    distanciaEnviar = -1;
    estado = 2;
  }

  secuenciaXBee++;

  /*
      Formato transmitido:

      D,secuencia,distancia,estado

      Ejemplo:
      D,25,1340,0
  */

  puertoXBee.printf(
      "D,%lu,%d,%d\n",
      (unsigned long)secuenciaXBee,
      distanciaEnviar,
      estado);

  Serial.println();
  Serial.println("------------------------------");
  Serial.print("Datos enviados por XBee: ");

  Serial.printf(
      "D,%lu,%d,%d\n",
      (unsigned long)secuenciaXBee,
      distanciaEnviar,
      estado);

  Serial.print("Secuencia: ");
  Serial.println(secuenciaXBee);

  if (estado == 0)
  {
    Serial.print("Distancia: ");
    Serial.print(distanciaEnviar);
    Serial.print(" mm (");
    Serial.print(distanciaEnviar / 1000.0, 3);
    Serial.println(" m)");

    if (distanciaEnviar < 500)
    {
      Serial.println(
          "Aviso: esta por debajo del rango especificado "
          "del MB7388.");
    }
  }
  else if (estado == 1)
  {
    Serial.println(
        "Distancia: 9999 -> sin objetivo detectado");
  }
  else
  {
    Serial.println(
        "Distancia: sin trama valida durante el intervalo");
  }

  // Comienza un nuevo intervalo de evaluación.
  huboTramaValidaIntervalo = false;
}

//---------------------------------------------------------------------
// SETUP
//---------------------------------------------------------------------

void setup()
{
  // Monitor serial de PlatformIO
  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println("==============================");
  Serial.println("INICIANDO SISTEMA");
  Serial.println("==============================");

  //========================== MB7388 ===============================//

  puertoSensor_dis.begin(
      9600,
      SERIAL_8N1,
      PIN_RX_SENSOR_DIS,
      -1); // No necesitamos TX hacia el MB7388

  puertoSensor_dis.setTimeout(250);

  Serial.println("MB7388 listo");

  //============================ XBEE ===============================//

  puertoXBee.begin(
      9600,
      SERIAL_8N1,
      PIN_RX_XBEE,
      PIN_TX_XBEE);

  Serial.println("Puerto serial del XBee listo");

  Serial.println();
  Serial.println("Configuracion local:");
  Serial.println("MB7388 -> UART2 -> GPIO16");
  Serial.println("XBee    -> UART1 -> RX26 / TX27");
  Serial.println();

  Serial.println("==============================");
  Serial.println("RECIBIENDO Y ENVIANDO DATOS");
  Serial.println("==============================");

  tiempoAnteriorEnvio = millis();
}

//---------------------------------------------------------------------
// LOOP
//---------------------------------------------------------------------

void loop()
{
  // Esta función se ejecuta continuamente para que no
  // se acumulen tramas antiguas en la UART del MB7388.
  recibirMB7388();

  unsigned long tiempoActual = millis();

  if (tiempoActual - tiempoAnteriorEnvio >= FRECUENCIA_ENVIO_MS)
  {
    tiempoAnteriorEnvio = tiempoActual;

    enviarDistanciaXBee();
  }
}