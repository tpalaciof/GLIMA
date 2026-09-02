#include <Arduino.h>

/*
  Lectura analogica del sensor MaxBotix MB7388 con un ESP32.

  Suposiciones de esta primera prueba:
  - Placa ESP32 DevKit.
  - Sensor alimentado con 3.3 V.

    MB7388 pin 3 (Salida analogica) -> ESP32 D34  (GPIO 34)
    MB7388 pin 4  -> ESP32 D25  (GPIO25)
    MB7388 pin 5 (Tx)  -> ESP32 RX2  (GPIO16)
*/

//******************************** PINES **********************************/
const int PIN_SENSOR = 34;

const int PIN_CONTROL_SENSOR = 14; // En la placa: D25
const int PIN_RX_SENSOR = 16;      // En la placa: RX2

//**************************** VAR. ANÁLOGO *******************************/
// Mida este voltaje con un multimetro para mejorar la exactitud.
const float VCC_SENSOR_MV = 3293.0;

// Factor de escala:  (Vcc / 10240) por mm
// Para el MB7388: Vout = distancia_mm * (Vcc / 10240).
const float ESCALA_MB7388_MM = 10240.0;

// Distancia desde la cara del sensor hasta el nivel de referencia cero.
// Cambie este valor para su instalacion.
const float ALTURA_SENSOR_SOBRE_CERO_MM = 2000.0;

//***************************** VAR. SERIAL *******************************/
const int DISTANCIA_MAXIMA_MM = 9998;
HardwareSerial puertoSensor(2);

//***************************** TEMP *******************************/
unsigned long tv_ant = 0;
const long PUBLISH_FREQUENCY = 2000;
unsigned long tv_act = 0;

/************************************ FUNCiONES *************************************
************************************************************************************/

bool tramaValida(const String &trama)
{
  // La trama normal tiene esta forma: R1234
  if (trama.length() != 5 || trama[0] != 'R')
  {
    return false;
  }

  // Los cuatro caracteres posteriores a la R deben ser números.
  for (int i = 1; i < 5; i++)
  {
    if (!isDigit(trama[i]))
    {
      return false;
    }
  }

  return true;
}

void setup()
{
  Serial.begin(9600);

  // Mantener el pin 4 del sensor en LOW detiene las mediciones.
  pinMode(PIN_CONTROL_SENSOR, OUTPUT);
  digitalWrite(PIN_CONTROL_SENSOR, HIGH);

  //************************** CONF. ANÁLOGO *******************************/
  pinMode(PIN_SENSOR, INPUT);

  // El ADC entregara valores crudos entre 0 y 4095.
  analogReadResolution(12);

  // Permite medir el mayor intervalo de voltaje disponible en el ESP32.
  analogSetPinAttenuation(PIN_SENSOR, ADC_11db);

  //************************** CONF. SERIAL *******************************/

  // El MB7388 transmite a 9600 baudios, 8 bits, sin paridad y 1 bit de parada.
  puertoSensor.begin(9600, SERIAL_8N1, PIN_RX_SENSOR);
  puertoSensor.setTimeout(250);

  // El MB7388 necesita un corto tiempo para iniciar y tomar su primera medida.
  delay(1000);

  // Espera a que termine cualquier medición iniciada durante el encendido.
  delay(250);
  while (puertoSensor.available())
  {
    puertoSensor.read();
  }

  Serial.println("MB7388 listo");

  Serial.println("Lectura del MB7388: ");

  // Serial.println("ADC | Voltaje (mV) | Distancia (mm) ");
}

void analog()
{
  // Valor digital sin convertir: de 0 a 4095.
  int valor_adc = analogRead(PIN_SENSOR);

  // Lectura calibrada del mismo pin, expresada en milivoltios.
  uint32_t voltaje_mV = analogReadMilliVolts(PIN_SENSOR);

  // Despeje de la ecuacion del datasheet:
  // distancia_mm = Vout * 10240 / Vcc.
  float distancia_mm = voltaje_mV * ESCALA_MB7388_MM / VCC_SENSOR_MV;

  // El sensor mira hacia abajo: al subir el agua, la distancia disminuye.
  // float nivel_mm = ALTURA_SENSOR_SOBRE_CERO_MM - distancia_mm;

  Serial.print(valor_adc);
  Serial.print(" | ");
  Serial.print(voltaje_mV);
  Serial.print(" | ");
  Serial.println(distancia_mm, 1);
  // Serial.print(" | ");
  // Serial.println(nivel_mm, 1);
}

void serial()
{
  // El sensor responde: R + cuatro dígitos en mm + retorno de carro.
  // Ejemplo recibido: R1234\r
  String trama = puertoSensor.readStringUntil('\r');
  trama.trim(); // elimina espacios y caracteres de separación que hayan, por ejemplo: "  R1234  "  se convierte en: "R1234"

  if (!tramaValida(trama))
  { // Si la trama no es válida.
    Serial.println("No se recibió una trama R#### válida");
    delay(500);
    return;
  }
  Serial.print("Trama válida: ");
  Serial.println(tramaValida(trama));

  int distanciaMm = trama.substring(1).toInt(); // trama.substring(1) extrae el texto comenzando desde la posición 1.
                                                // .toInt() convierte el texto en el número entero
  Serial.print("Trama: ");
  Serial.print(trama);

  if (distanciaMm == 9999)
  {
    Serial.println("  -> sin objetivo detectado");
  }
  else if (distanciaMm <= DISTANCIA_MAXIMA_MM)
  {
    Serial.print("  -> distancia: ");
    Serial.print(distanciaMm);
    Serial.print(" mm (");
    Serial.print(distanciaMm / 1000.0, 3);
    Serial.println(" m)");

    if (distanciaMm < 500)
    {
      Serial.println("Aviso: está por debajo del rango especificado del MB7388.");
    }
  }
}

void loop()
{
  tv_act = millis();
  if (tv_act - tv_ant >= PUBLISH_FREQUENCY)
  {
    tv_ant = tv_act;
    // analog();
    serial();
  }
}
