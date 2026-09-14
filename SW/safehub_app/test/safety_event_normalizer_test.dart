import 'package:flutter_test/flutter_test.dart';
import 'package:safehub_app/core/safety_event_normalizer.dart';

void main() {
  group('SafetyEventNormalizer', () {
    test('화장실 낙상 숫자 priority를 처리한다', () {
      final event = SafetyEventNormalizer.normalize(
        topic: SafetyEventNormalizer.bathroomTopic,
        decoded: {
          'event': 'fall_detected',
          'priority': 9,
        },
      );

      expect(event, isNotNull);
      expect(event!['event'], 'fall_detected');
      expect(event['location'], 'bathroom');
      expect(event['priority'], 9);
    });

    test('문자열 priority를 정수로 변환한다', () {
      final event = SafetyEventNormalizer.normalize(
        topic: SafetyEventNormalizer.bedroomTopic,
        decoded: {
          'event': 'fall_detected',
          'priority': '9',
        },
      );

      expect(event, isNotNull);
      expect(event!['location'], 'bedroom');
      expect(event['priority'], 9);
    });

    test('낙상 event의 대문자와 공백을 정규화한다', () {
      final event = SafetyEventNormalizer.normalize(
        topic: SafetyEventNormalizer.bathroomTopic,
        decoded: {
          'event': ' FALL_DETECTED ',
          'priority': 9,
        },
      );

      expect(event, isNotNull);
      expect(event!['event'], 'fall_detected');
    });

    test('낙상 priority가 누락되면 안전 기본값 9를 사용한다', () {
      final event = SafetyEventNormalizer.normalize(
        topic: SafetyEventNormalizer.bathroomTopic,
        decoded: {
          'event': 'fall_detected',
        },
      );

      expect(event, isNotNull);
      expect(event!['priority'], 9);
    });

    test('관계없는 토픽은 무시한다', () {
      final event = SafetyEventNormalizer.normalize(
        topic: 'safehub/unknown',
        decoded: {
          'event': 'fall_detected',
          'priority': 9,
        },
      );

      expect(event, isNull);
    });

    test('잘못된 일반 이벤트 priority는 무시한다', () {
      final event = SafetyEventNormalizer.normalize(
        topic: SafetyEventNormalizer.bathroomTopic,
        decoded: {
          'event': 'motion',
          'priority': 'invalid',
        },
      );

      expect(event, isNull);
    });
  });
}
