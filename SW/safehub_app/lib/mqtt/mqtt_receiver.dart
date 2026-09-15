import 'dart:convert';

import 'package:mqtt_client/mqtt_client.dart';
import 'package:mqtt_client/mqtt_server_client.dart';

import '../core/event_manager.dart';
import '../core/safety_event_normalizer.dart';

class MqttReceiver {
  final String broker;
  final int port;
  final EventManager eventManager;

  // CSI 안전 이벤트 수신
  final void Function(Map<String, dynamic> event)? onEventReceived;

  // 수어 번역 결과 수신
  final void Function(String text)? onSignTextReceived;

  final void Function(String topic, Map<String, dynamic> data)? onDeviceCommand;

  // MQTT 연결 상태 변경
  final void Function(bool connected)? onConnectionChanged;

  late final MqttServerClient _client;

  MqttReceiver({
    required this.broker,
    required this.port,
    required this.eventManager,
    this.onEventReceived,
    this.onSignTextReceived,
    this.onDeviceCommand,
    this.onConnectionChanged,
  });

  Future<void> connect() async {
    final clientId = 'safehub_rpi5_${DateTime.now().millisecondsSinceEpoch}';

    print('[MQTT] connecting broker=$broker port=$port client=$clientId');

    _client = MqttServerClient.withPort(
      broker,
      clientId,
      port,
    );

    _client.keepAlivePeriod = 20;

    // 연결이 끊어지면 자동 재연결
    _client.autoReconnect = true;

    // 자동 재연결 성공 후 기존 MQTT 토픽 다시 구독
    _client.resubscribeOnAutoReconnect = true;

    _client.onConnected = () {
      print('[MQTT] connected broker=$broker port=$port');
      onConnectionChanged?.call(true);
    };

    _client.onDisconnected = () {
      print('[MQTT] disconnected state=${_client.connectionStatus?.state}');
      onConnectionChanged?.call(false);
    };

    _client.onSubscribed = (topic) {
      print('[MQTT] subscribed topic=$topic');
    };

    _client.onSubscribeFail = (topic) {
      print('[MQTT] subscribe failed topic=$topic');
    };

    _client.onAutoReconnect = () {
      print('[MQTT] auto reconnecting');
      onConnectionChanged?.call(false);
    };

    _client.onAutoReconnected = () {
      print('[MQTT] auto reconnected');
      onConnectionChanged?.call(true);
    };

    _client.connectionMessage =
        MqttConnectMessage().withClientIdentifier(clientId).startClean();

    try {
      await _client.connect();
    } catch (e) {
      print('[MQTT] connection failed: $e');
      _client.disconnect();
      rethrow;
    }

    if (_client.connectionStatus?.state != MqttConnectionState.connected) {
      _client.disconnect();
      throw Exception('MQTT 브로커 연결 실패');
    }

    // 침실 CSI 이벤트
    _client.subscribe(
      'safehub/csi/bedroom/event',
      MqttQos.atLeastOnce,
    );

    // 화장실 CSI 이벤트
    _client.subscribe(
      'safehub/csi/bathroom/event',
      MqttQos.atLeastOnce,
    );

    // 수어 번역 결과
    _client.subscribe(
      'safehub/vision/livingroom/translation',
      MqttQos.atMostOnce,
    );

    _client.updates?.listen(_onMessage);
    _client.subscribe('safehub/control/livingroom/aircon/command', MqttQos.atLeastOnce);
  }

  void _onMessage(
    List<MqttReceivedMessage<MqttMessage?>> messages,
  ) {
    for (final receivedMessage in messages) {
      _handleMessage(receivedMessage);
    }
  }

  void _handleMessage(MqttReceivedMessage<MqttMessage?> receivedMessage) {
    try {
      final message = receivedMessage.payload;

      if (message is! MqttPublishMessage) {
        return;
      }

      final topic = receivedMessage.topic;

      final payload = utf8.decode(
        message.payload.message,
      );

      print('[MQTT] received topic=$topic bytes=${payload.length}');

      final decoded = jsonDecode(payload);

      if (topic == 'safehub/control/livingroom/aircon/command') {
        if (decoded is Map<String, dynamic>) onDeviceCommand?.call(topic, decoded);
        return;
      }

      // 수어 번역 결과
      if (topic == 'safehub/vision/livingroom/translation') {
        if (decoded is! Map<String, dynamic>) {
          return;
        }

        final text = decoded['text'];

        if (text is! String || text.trim().isEmpty) {
          return;
        }

        onSignTextReceived?.call(text.trim());
        return;
      }

      final event = SafetyEventNormalizer.normalize(
        decoded: decoded,
        topic: topic,
      );

      if (event == null) {
        print(
          '[MQTT] ignored invalid safety event '
          'topic=$topic payload=$payload',
        );
        return;
      }

      eventManager.addEvent(event);

      print(
        '[MQTT] event queued event=${event['event']} '
        'location=${event['location']} priority=${event['priority']}',
      );

      onEventReceived?.call(event);
    } catch (e) {
      print('[MQTT] message handling failed: $e');
    }
  }

  void disconnect() {
    _client.disconnect();
  }
}
