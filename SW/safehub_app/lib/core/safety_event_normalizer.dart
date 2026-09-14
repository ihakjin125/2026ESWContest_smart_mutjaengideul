class SafetyEventNormalizer {
  static const bedroomTopic = 'safehub/csi/bedroom/event';
  static const bathroomTopic = 'safehub/csi/bathroom/event';

  static Map<String, dynamic>? normalize({
    required Object? decoded,
    required String topic,
  }) {
    if (topic != bedroomTopic && topic != bathroomTopic) {
      return null;
    }

    if (decoded is! Map<String, dynamic>) {
      return null;
    }

    final event = Map<String, dynamic>.from(decoded);

    final rawEventType = event['event'];
    if (rawEventType is! String) {
      return null;
    }

    final eventType = rawEventType.trim().toLowerCase();
    if (eventType.isEmpty) {
      return null;
    }

    event['event'] = eventType;
    event['location'] = topic == bedroomTopic ? 'bedroom' : 'bathroom';

    final rawPriority = event['priority'];
    int? priority;

    if (rawPriority is int) {
      priority = rawPriority;
    } else if (rawPriority is num &&
        rawPriority.isFinite &&
        rawPriority == rawPriority.roundToDouble()) {
      priority = rawPriority.toInt();
    } else if (rawPriority is String) {
      priority = int.tryParse(rawPriority.trim());
    }

    // 낙상은 priority가 누락되거나 잘못돼도 안전 우선으로 처리한다.
    if (priority == null && eventType == 'fall_detected') {
      priority = 9;
    }

    if (priority == null || priority < 1 || priority > 10) {
      return null;
    }

    event['priority'] = priority;
    return event;
  }
}
