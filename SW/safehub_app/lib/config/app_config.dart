class AppConfig {
  static const String mqttBroker = String.fromEnvironment('MQTT_BROKER');

  static const int mqttPort = int.fromEnvironment('MQTT_PORT');

  static const String disasterApiUrl =
      String.fromEnvironment('DISASTER_API_URL');

  static const String disasterApiKey =
      String.fromEnvironment('DISASTER_API_KEY');

  static const String ttsServerUrl = String.fromEnvironment('TTS_SERVER_URL');

  static const String sttServerUrl = String.fromEnvironment('STT_SERVER_URL');

  static const String cameraHost = String.fromEnvironment('CAMERA_HOST');

  static const int cameraPort =
      int.fromEnvironment('CAMERA_PORT', defaultValue: 5000);

  static void validate() {
    if (mqttBroker.isEmpty) {
      throw StateError(
        'MQTT_BROKER가 설정되지 않았습니다.',
      );
    }

    if (mqttPort <= 0) {
      throw StateError(
        'MQTT_PORT가 올바르지 않습니다.',
      );
    }

    if (disasterApiUrl.isEmpty) {
      throw StateError(
        'DISASTER_API_URL이 설정되지 않았습니다.',
      );
    }

    if (disasterApiKey.isEmpty) {
      throw StateError(
        'DISASTER_API_KEY가 설정되지 않았습니다.',
      );
    }

    // TTS_SERVER_URL은 선택 기능이므로 validate에서 강제하지 않는다.
  }
}
