class PpiProtocol {
  static const int plcAddr = 2;
  static const int pcAddr = 0;

  // Códigos de área de memoria Siemens S7-200
  static const int areaSM = 0x05;
  static const int areaI = 0x81;
  static const int areaQ = 0x82;
  static const int areaM = 0x83;
  static const int areaV = 0x84;

  static int calcFcs(List<int> payload) {
    return payload.fold(0, (sum, byte) => sum + byte) & 0xFF;
  }

  static bool isValidSd1(List<int> frame) {
    if (frame.length != 6 || frame[0] != 0x10 || frame[5] != 0x16) return false;
    return frame[4] == ((frame[1] + frame[2] + frame[3]) & 0xFF);
  }

  static bool isValidSd2(List<int> frame) {
    if (frame.length < 6 || frame[0] != 0x68 || frame.last != 0x16 || frame[1] != frame[2]) {
      return false;
    }
    int len = frame[1];
    if (frame.length != len + 6) return false;
    int payloadSum = frame.sublist(4, frame.length - 2).fold(0, (sum, b) => sum + b) & 0xFF;
    return frame[frame.length - 2] == payloadSum;
  }

  /// Construye una trama SD2 completa lista para enviar al ESP32
  static List<int> buildSd2Frame(List<int> pduBody) {
    List<int> payload = [plcAddr, pcAddr, 0x4C, ...pduBody];
    int fcs = calcFcs(payload);
    return [0x68, payload.length, payload.length, 0x68, ...payload, fcs, 0x16];
  }

  /// Construye la trama de sondeo SD1 para solicitar la respuesta
  static List<int> buildPollSd1() {
    int fcs = (plcAddr + pcAddr + 0x4C) & 0xFF;
    return [0x10, plcAddr, pcAddr, 0x4C, fcs, 0x16];
  }

  /// Construye la PDU para leer un bloque de memoria
  static List<int> buildReadMemoryPdu({
    required int areaCode,
    required int startByte,
    required int count,
    int seq = 1,
  }) {
    int startBit = startByte * 8;
    return [
      0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x0E, 0x00, 0x00,
      0x04, 0x01, 0x12, 0x0A, 0x10, 0x02,
      (count >> 8) & 0xFF, count & 0xFF,
      0x00, 0x00,
      areaCode,
      (startBit >> 16) & 0xFF, (startBit >> 8) & 0xFF, startBit & 0xFF,
    ];
  }

  /// Construye la PDU para conmutar modo (RUN: fc=0x28, STOP: fc=0x29 con parámetro P_PROGRAM)
  static List<int> buildModeCommandPdu(bool run) {
    int fc = run ? 0x28 : 0x29;
    List<int> pProg = [0x50, 0x5F, 0x50, 0x52, 0x4F, 0x47, 0x52, 0x41, 0x4D]; // "P_PROGRAM"
    List<int> param = run
        ? [0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFD, 0x00, 0x00, pProg.length, ...pProg]
        : [0x29, 0x00, 0x00, 0x00, 0x00, 0x00, pProg.length, ...pProg];
    return [
      0x32, 0x01, 0x00, 0x00, 0x00, fc,
      (param.length >> 8) & 0xFF, param.length & 0xFF,
      0x00, 0x00,
      ...param,
    ];
  }

  /// Construye la PDU para escribir un bit individual (Función 0x05 Write)
  /// areaCode: areaI (0x81), areaQ (0x82), areaM (0x83), areaV (0x84)
  static List<int> buildWriteBitPdu({
    required int areaCode,
    required int startByte,
    required int bitIndex,
    required bool value,
    int seq = 1,
  }) {
    int startBit = (startByte * 8) + bitIndex;
    return [
      0x32, 0x01, 0x00, 0x00, (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x0E, 0x00, 0x05,
      0x05, 0x01, 0x12, 0x0A, 0x10, 0x01, 0x00, 0x01, 0x00, 0x00,
      areaCode,
      (startBit >> 16) & 0xFF, (startBit >> 8) & 0xFF, startBit & 0xFF,
      0x00, 0x03, 0x00, 0x01, value ? 0x01 : 0x00,
    ];
  }

  /// Extrae el payload de datos de una respuesta SD2 válida
  static List<int>? extractDataPayload(List<int> frame, int count) {
    if (!isValidSd2(frame)) return null;
    if (frame.length >= (21 + count)) {
      return frame.sublist(frame.length - (2 + count), frame.length - 2);
    }
    return null;
  }
}
